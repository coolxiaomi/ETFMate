from __future__ import annotations

from etfmate.storage.models import GridConfig, MarketSnapshot


def advise_grid(grid: GridConfig, market: MarketSnapshot) -> dict:
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
        action = "暂停网格" if action == "维持" else action
        reasons.append("价格低于 MA60，需要防止下跌趋势中机械补仓")
        suggested_buy_qty = _round_qty(current_qty * 0.5)
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
        "suggested_buy_quantity": suggested_buy_qty or None,
        "suggested_sell_quantity": suggested_sell_qty or None,
        "reasons": reasons,
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
