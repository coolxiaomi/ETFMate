from __future__ import annotations

from typing import Any

from etfmate.analysis.layered_context import LayeredContext, normalize_context
from etfmate.storage.models import GridConfig, MarketSnapshot, Position


def advise_grid(
    grid: GridConfig,
    market: MarketSnapshot,
    position: Position | None = None,
    layered_context: LayeredContext | dict[str, Any] | None = None,
) -> dict:
    reasons: list[str] = []
    action = "维持"
    current_step = grid.grid_step_pct or _avg(grid.buy_fall_pct, grid.sell_rise_pct)
    suggested_buy_fall = _round_pct(_clamp((market.atr14_pct or current_step or 5.0) * 0.9, 2.0, 8.0))
    suggested_sell_rise = _round_pct(_clamp((market.atr14_pct or current_step or 5.0) * 0.8, 2.0, 8.0))
    current_qty = grid.order_quantity or grid.grid_step_amount or 0
    suggested_buy_qty = current_qty
    suggested_sell_qty = current_qty

    weak_trend = bool(market.ma60 and market.last_price < market.ma60)
    strong_positive = bool(market.boll_upper and market.last_price >= market.boll_upper * 0.95 and (market.bias6 or 0) > 2)
    low_zone = bool(market.boll_lower and market.last_price <= market.boll_lower * 1.08 and (market.bias6 or 0) < -1)

    if current_step and market.atr14_pct:
        if current_step < 0.6 * market.atr14_pct:
            action = "调宽网格"
            reasons.append("当前网格间距小于 0.6 倍 ATR14，容易产生噪音交易")
            suggested_buy_fall = _round_pct(_clamp(market.atr14_pct * 0.9, 2.0, 8.0))
            suggested_sell_rise = _round_pct(_clamp(market.atr14_pct * 0.8, 2.0, 8.0))
        elif current_step > 1.8 * market.atr14_pct:
            action = "调窄网格"
            reasons.append("当前网格间距大于 1.8 倍 ATR14，触发频率可能过低")
            suggested_buy_fall = _round_pct(_clamp(market.atr14_pct * 0.9, 2.0, current_step))
            suggested_sell_rise = _round_pct(_clamp(market.atr14_pct * 0.8, 2.0, current_step))
        else:
            reasons.append("当前网格间距与 ATR14 波动率基本匹配")

    if weak_trend and grid.enabled:
        action = "暂停网格"
        reasons = [reason for reason in reasons if "网格间距" not in reason]
        reasons.append("价格低于 MA60，先暂停买入侧，避免下跌趋势中机械补仓")
        suggested_buy_qty = 0
        suggested_sell_qty = _round_qty(current_qty * 1.2)
        suggested_buy_fall = max(suggested_buy_fall, _round_pct((market.atr14_pct or suggested_buy_fall) * 1.1))
    elif strong_positive:
        suggested_buy_qty = _round_qty(current_qty * 0.5)
        suggested_sell_qty = _round_qty(current_qty * 1.5)
        suggested_sell_rise = _round_pct(_clamp((market.atr14_pct or suggested_sell_rise) * 0.6, 2.0, suggested_sell_rise))
        reasons.append("价格接近 BOLL 上轨且短线正偏离，卖出侧应更积极")
    elif low_zone:
        suggested_buy_qty = _round_qty(current_qty)
        suggested_sell_qty = _round_qty(current_qty)
        suggested_buy_fall = _round_pct(_clamp((market.atr14_pct or suggested_buy_fall) * 0.7, 2.0, suggested_buy_fall))
        reasons.append("价格接近 BOLL 下轨且短线负偏离，可保留买入侧但控制总仓位")

    if position and position.quantity <= 200 and suggested_buy_qty and suggested_buy_qty > position.quantity:
        suggested_buy_qty = _round_qty(position.quantity)
        reasons.append("当前持仓很小，买入数量不应明显超过现有持仓，先用小份额验证")

    layer_payload = normalize_context(layered_context)
    if layer_payload:
        confidence = _num_or_zero(layer_payload.get("confidence"))
        total_score = _num_or_zero(layer_payload.get("total_score"))
        if confidence < 45 and action in {"调宽网格", "调窄网格"}:
            action = "维持"
            suggested_buy_fall = grid.buy_fall_pct
            suggested_sell_rise = grid.sell_rise_pct
            reasons.append("七层证据置信度不足，本次不做过细网格调参")
        if total_score <= -2 and action != "暂停网格":
            reasons.append("多层证据偏弱，买入侧按保守仓位执行")
            suggested_buy_qty = _round_qty((suggested_buy_qty or current_qty) * 0.5)
        elif total_score >= 2 and action == "暂停网格":
            reasons.append("多层证据未完全转弱，暂停后仍保留卖出侧纪律并观察修复")

    if not reasons:
        reasons.append("缺少完整波动率或网格参数，建议先补齐数据")
    return {
        "code": grid.code,
        "name": grid.name,
        "action": action,
        "current_buy_fall_pct": grid.buy_fall_pct,
        "suggested_buy_fall_pct": suggested_buy_fall,
        "current_sell_rise_pct": grid.sell_rise_pct,
        "suggested_sell_rise_pct": suggested_sell_rise,
        "current_quantity": current_qty or None,
        "suggested_buy_quantity": suggested_buy_qty if suggested_buy_qty is not None else None,
        "suggested_sell_quantity": suggested_sell_qty if suggested_sell_qty is not None else None,
        "reasons": reasons,
        "layered_confidence": layer_payload.get("confidence") if layer_payload else None,
        "layered_score": layer_payload.get("total_score") if layer_payload else None,
    }


def _avg(left: float | None, right: float | None) -> float | None:
    values = [value for value in (left, right) if value is not None]
    return sum(values) / len(values) if values else None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round_pct(value: float) -> float:
    return round(value, 2)


def _round_qty(value: float) -> float:
    if value <= 0:
        return 0
    return max(100, round(value / 100) * 100)


def _num_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
