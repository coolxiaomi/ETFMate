from __future__ import annotations

from typing import Any

from etfmate.analysis.layered_context import LayeredContext, normalize_context
from etfmate.storage.models import GridConfig, MarketSnapshot, Position


def advise_grid(
    grid: GridConfig,
    market: MarketSnapshot,
    position: Position | None = None,
    layered_context: LayeredContext | dict[str, Any] | None = None,
    rule_decision: dict[str, Any] | None = None,
) -> dict:
    reasons: list[str] = []
    action = "维持"
    current_step = grid.grid_step_pct or _avg(grid.buy_fall_pct, grid.sell_rise_pct)
    suggested_buy_fall = _round_pct(_clamp((market.atr14_pct or current_step or 5.0) * 0.9, 2.0, 8.0))
    suggested_sell_rise = _round_pct(_clamp((market.atr14_pct or current_step or 5.0) * 0.8, 2.0, 8.0))
    current_qty = grid.order_quantity or grid.buy_quantity or grid.sell_quantity or grid.grid_step_amount or 0
    base_lot_qty = _round_qty(current_qty or 100)
    suggested_buy_qty = base_lot_qty
    suggested_sell_qty = base_lot_qty
    if current_qty and current_qty != base_lot_qty:
        reasons.append("网格条件单委托股数必须至少 100 股且为 100 的倍数，建议按一手倍数修正")

    position_weight = position.position_pct if position and position.position_pct is not None else 0
    hard_weak = bool(market.ma20 and market.ma60 and market.last_price < market.ma20 and market.last_price < market.ma60)
    soft_weak = bool(market.ma60 and market.last_price < market.ma60)
    high_position = bool(position and position_weight >= 5)
    deep_loss = bool(position and position.pnl_pct <= -8)
    strong_positive = bool(market.boll_upper and market.last_price >= market.boll_upper * 0.95 and (market.bias6 or 0) > 2)
    low_zone = bool(market.boll_lower and market.last_price <= market.boll_lower * 1.08 and (market.bias6 or 0) < -1)

    hard_reduce_buy_side = grid.enabled and hard_weak and (high_position or deep_loss)
    reduce_buy_side = grid.enabled and (soft_weak or hard_reduce_buy_side)

    if current_step and market.atr14_pct and not hard_reduce_buy_side:
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

    if hard_reduce_buy_side:
        action = "降低买入侧"
        reasons = [reason for reason in reasons if "网格间距" not in reason]
        reasons.append("价格同时低于 MA20/MA60，且仓位或亏损压力不低；Touker 数量不设为 0，本次改为买入侧降速并提示人工确认是否停用买触发")
        suggested_buy_qty = _round_qty(base_lot_qty * 0.5)
        suggested_sell_qty = base_lot_qty
        suggested_buy_fall = grid.buy_fall_pct
        suggested_sell_rise = grid.sell_rise_pct
    elif reduce_buy_side:
        action = "降低买入侧"
        reasons.append("价格低于 MA60 但尚未触发暂停条件，买入侧先降速，卖出侧保持")
        suggested_buy_qty = _round_qty(current_qty * 0.5)
        suggested_sell_qty = _round_qty(current_qty)
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
    if position and suggested_sell_qty and suggested_sell_qty > position.quantity:
        suggested_sell_qty = _round_qty(position.quantity)
        reasons.append("卖出侧建议数量不得超过当前持仓数量，已按持仓上限收敛")

    if rule_decision:
        rule_action = str(rule_decision.get("action") or "")
        position_action = str(rule_decision.get("position_action") or "")
        blocked = set(rule_decision.get("blocked_actions") or [])
        risk_score = _num_or_zero(rule_decision.get("risk_score"))
        trend_score = _num_or_zero(rule_decision.get("trend_score"))
        position_risk_level = str(rule_decision.get("risk_level") or "")
        if rule_action in {"禁止交易"}:
            action = "降低买入侧"
            suggested_buy_qty = _round_qty(base_lot_qty * 0.5)
            suggested_sell_qty = base_lot_qty
            suggested_buy_fall = grid.buy_fall_pct
            suggested_sell_rise = grid.sell_rise_pct
            reasons.append("操作建议触发禁止交易；Touker 数量不设为 0，网格买入侧仅给一手倍数的保守降速建议")
        elif position_action in {"EXIT_SHORT_TERM", "RISK_REVIEW"} or rule_action in {"退出短线仓位", "风控复核"} or trend_score < 45:
            action = "降低买入侧"
            suggested_buy_qty = _round_qty(base_lot_qty * 0.5)
            suggested_sell_qty = base_lot_qty
            suggested_buy_fall = grid.buy_fall_pct
            suggested_sell_rise = grid.sell_rise_pct
            reasons.append("短线趋势评分转弱或操作建议触发风控复核；不输出 0 数量，买入侧改为保守降速，卖出侧纪律保留")
        elif position_action == "REDUCE" or rule_action == "减仓" or risk_score >= 70 or position_risk_level == "HIGH" or {"买入", "加仓", "提高网格买入侧"} & blocked:
            if action != "维持网格并风险提示":
                action = "降低买入侧"
            suggested_buy_qty = _round_qty((suggested_buy_qty or base_lot_qty) * 0.5)
            suggested_sell_qty = max(suggested_sell_qty or base_lot_qty, base_lot_qty)
            reasons.append("操作建议偏减仓或风险等级偏高，网格买入侧按保守仓位执行")
        elif position_action in {"ADD", "OPEN", "LIGHT_OPEN", "HOLD_OR_ADD"} and trend_score >= 75 and position_risk_level == "LOW":
            if action == "维持":
                reasons.append("操作建议偏加仓/建仓且趋势评分不低于75，网格可维持运行，但仍按仓位上限控制买入侧")

    layer_payload = normalize_context(layered_context)
    if layer_payload:
        confidence = _num_or_zero(layer_payload.get("confidence"))
        total_score = _num_or_zero(layer_payload.get("total_score"))
        if confidence < 45 and action in {"调宽网格", "调窄网格"}:
            action = "维持"
            suggested_buy_fall = grid.buy_fall_pct
            suggested_sell_rise = grid.sell_rise_pct
            reasons.append("七层证据置信度不足，本次不做过细网格调参")
        if total_score <= -2 and action != "维持网格并风险提示":
            reasons.append("多层证据偏弱，买入侧按保守仓位执行")
            suggested_buy_qty = _round_qty((suggested_buy_qty or current_qty) * 0.5)
        elif total_score >= 2 and action in {"降低买入侧", "维持网格并风险提示"}:
            reasons.append("多层证据未完全转弱，降低买入侧后仍保留卖出侧纪律并观察修复")

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
        "rule_decision": rule_decision,
    }


def _avg(left: float | None, right: float | None) -> float | None:
    values = [value for value in (left, right) if value is not None]
    return sum(values) / len(values) if values else None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round_pct(value: float) -> float:
    return round(value, 2)


def _round_qty(value: float) -> float:
    return max(100, round(value / 100) * 100)


def _num_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
