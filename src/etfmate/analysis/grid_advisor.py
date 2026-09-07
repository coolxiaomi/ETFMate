from __future__ import annotations

from typing import Any

from etfmate.analysis.layered_context import LayeredContext, normalize_context
from etfmate.storage.models import GridConfig, MarketSnapshot, Position

STRATEGY_PROFILE = "条件单代替盯盘；胜率优先；不追求吃完整段行情；盈利看趋势管理；不深研标的时默认保守"
GRID_MODE_LABELS = {
    "TREND_ADD": "趋势加仓",
    "TREND_HOLD_GRID": "趋势持有",
    "PROFIT_PROTECTION": "高位保护",
    "BALANCED_GRID": "震荡滚动",
    "WEAK_REDUCE": "弱势减仓",
    "ONLY_SELL_OR_CLEAR": "只卖清仓",
    "PAUSE": "暂停",
}


def advise_grid(
    grid: GridConfig | None,
    market: MarketSnapshot,
    position: Position | None = None,
    layered_context: LayeredContext | dict[str, Any] | None = None,
    rule_decision: dict[str, Any] | None = None,
) -> dict:
    reasons: list[str] = []
    has_existing_grid = grid is not None
    rule_action = str((rule_decision or {}).get("action") or "")
    position_action = str((rule_decision or {}).get("position_action") or "")
    trend_score = _num_or_zero((rule_decision or {}).get("trend_score"))
    position_risk_level = str((rule_decision or {}).get("risk_level") or "")
    target_ratio = _num_or_zero((rule_decision or {}).get("target_position_ratio"))
    blocked = set((rule_decision or {}).get("blocked_actions") or [])
    overheat_level = str((rule_decision or {}).get("trend_overheat_level") or "NONE")
    grid_mode = _grid_mode_from_decision(trend_score, overheat_level, position_action, rule_action)
    layer_payload = normalize_context(layered_context)

    if grid is not None and getattr(grid, "condition_type", "grid") == "sell_only":
        return _sell_only_grid_advice(grid, market, position, reasons, layer_payload)

    if not _grid_applicable(has_existing_grid, position, rule_action, position_action):
        reasons.append("当前未持仓且规则未给出建仓/轻仓建仓信号，本次不生成可执行网格参数")
        return _inactive_grid_advice(market, grid, reasons, rule_decision, layer_payload)

    action = "维持"
    grid_purpose = "持仓网格" if position else "建仓网格"
    current_step = _current_step(grid)
    atr_pct = market.atr14_pct or current_step or 5.0
    suggested_buy_fall = _round_pct(_clamp(atr_pct * 0.9, 2.0, 8.0))
    suggested_sell_rise = _round_pct(_clamp(atr_pct * 0.8, 2.0, 8.0))
    suggested_buy_rebound: float | None = None
    suggested_sell_pullback: float | None = None
    current_qty = _current_quantity(grid)
    base_lot_qty = _round_qty(current_qty or _initial_quantity(position))
    suggested_buy_qty: float | None = base_lot_qty
    suggested_sell_qty: float | None = base_lot_qty
    if current_qty and current_qty != base_lot_qty:
        reasons.append("网格条件单委托股数必须至少 100 股且为 100 的倍数，建议按一手倍数修正")

    position_weight = position.position_pct if position and position.position_pct is not None else 0
    hard_weak = bool(market.ma20 and market.ma60 and market.last_price < market.ma20 and market.last_price < market.ma60)
    soft_weak = bool(market.ma60 and market.last_price < market.ma60)
    high_position = bool(position and position_weight >= 5)
    deep_loss = bool(position and position.pnl_pct <= -8)
    strong_positive = bool(market.boll_upper and market.last_price >= market.boll_upper * 0.95 and (market.bias6 or 0) > 2)
    low_zone = bool(market.boll_lower and market.last_price <= market.boll_lower * 1.08 and (market.bias6 or 0) < -1)
    hard_reduce_buy_side = bool(grid and grid.enabled and hard_weak and (high_position or deep_loss))
    reduce_buy_side = bool(grid and grid.enabled and (soft_weak or hard_reduce_buy_side))
    trend_profit_continuation = _is_profit_trend_continuation(
        position, trend_score, position_risk_level, hard_weak, soft_weak, position_action, rule_action
    )

    base_eval = _evaluate_base_price(grid, market, position, hard_weak, strong_positive, trend_profit_continuation)
    reasons.extend(base_eval["reasons"])

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
        reasons.append("价格同时低于 MA20/MA60，且仓位或亏损压力不低；本次改为买入侧降速并提示人工确认是否停用买触发")
        suggested_buy_qty = _round_qty(base_lot_qty * 0.5)
        suggested_sell_qty = base_lot_qty
        suggested_buy_fall = grid.buy_fall_pct
        suggested_sell_rise = grid.sell_rise_pct
    elif reduce_buy_side:
        action = "降低买入侧"
        reasons.append("价格低于 MA60 但尚未触发暂停条件，买入侧先降速，卖出侧保持")
        suggested_buy_qty = _round_qty(base_lot_qty * 0.5)
        suggested_sell_qty = base_lot_qty
    elif strong_positive:
        suggested_buy_qty = _round_qty(base_lot_qty * 0.5)
        if trend_profit_continuation:
            suggested_sell_qty = base_lot_qty
            if grid and grid.sell_rise_pct:
                suggested_sell_rise = max(suggested_sell_rise or grid.sell_rise_pct, grid.sell_rise_pct)
            reasons.append("已有盈利但趋势评分较高且风险等级低，不因浮盈提前减仓；买入侧不追高，卖出侧保留盈利空间")
        else:
            suggested_sell_qty = _round_qty(base_lot_qty * 1.5)
            suggested_sell_rise = _round_pct(_clamp((market.atr14_pct or suggested_sell_rise) * 0.6, 2.0, suggested_sell_rise))
            suggested_sell_pullback = _round_pct(_clamp((market.atr14_pct or suggested_sell_pullback) * 0.08, 0.15, suggested_sell_pullback or 0.6))
            reasons.append("价格接近 BOLL 上轨且短线正偏离，但趋势或风险确认不足，卖出侧应更积极保护利润")
    elif low_zone:
        suggested_buy_qty = base_lot_qty
        suggested_sell_qty = base_lot_qty
        suggested_buy_fall = _round_pct(_clamp((market.atr14_pct or suggested_buy_fall) * 0.7, 2.0, suggested_buy_fall))
        reasons.append("价格接近 BOLL 下轨且短线负偏离，可保留买入侧但控制总仓位")
    elif not has_existing_grid and position_action in {"OPEN", "LIGHT_OPEN"}:
        action = "新建网格"
        reasons.append("未持仓但规则允许建仓，本次只给当前时点的一套建仓网格参数")

    if position and position.quantity <= 200 and suggested_buy_qty and suggested_buy_qty > position.quantity:
        suggested_buy_qty = _round_qty(position.quantity)
        reasons.append("当前持仓很小，买入数量不应明显超过现有持仓，先用小份额验证")
    if position and suggested_sell_qty and suggested_sell_qty > position.quantity:
        suggested_sell_qty = _round_qty(position.quantity)
        reasons.append("卖出侧建议数量不得超过当前持仓数量，已按持仓上限收敛")

    if rule_decision:
        if rule_action in {"禁止交易"}:
            action = "降低买入侧"
            suggested_buy_qty = _round_qty(base_lot_qty * 0.5)
            suggested_sell_qty = base_lot_qty
            suggested_buy_fall = grid.buy_fall_pct if grid else suggested_buy_fall
            suggested_sell_rise = grid.sell_rise_pct if grid else suggested_sell_rise
            reasons.append("操作建议触发禁止交易；网格买入侧仅给一手倍数的保守降速建议")
        elif target_ratio <= 0 and position and (position_action in {"REDUCE", "TREND_REVIEW", "EXIT_TREND_POSITION", "RISK_REVIEW", "EXIT_SHORT_TERM"} or rule_action in {"减仓", "趋势复核", "风控复核", "退出短线仓位"} or position_risk_level == "HIGH"):
            action = "只保留卖出" if trend_score >= 30 else "暂停买入侧"
            suggested_buy_qty = None
            suggested_sell_qty = base_lot_qty
            suggested_buy_fall = grid.buy_fall_pct if grid else suggested_buy_fall
            suggested_sell_rise = grid.sell_rise_pct if grid else suggested_sell_rise
            reasons.append("目标仓位为 0 且仍有持仓，买入侧不再按正常数量建议；需人工停用买触发，并改按清仓/减仓策略处理")
        elif position_action in {"EXIT_TREND_POSITION", "TREND_REVIEW", "EXIT_SHORT_TERM", "RISK_REVIEW"} or rule_action in {"退出短线仓位", "趋势复核", "风控复核"} or trend_score < 45:
            action = "降低买入侧"
            suggested_buy_qty = _round_qty(base_lot_qty * 0.5)
            suggested_sell_qty = base_lot_qty
            suggested_buy_fall = grid.buy_fall_pct if grid else suggested_buy_fall
            suggested_sell_rise = grid.sell_rise_pct if grid else suggested_sell_rise
            reasons.append("短线趋势评分转弱或操作建议触发风控复核；买入侧改为保守降速，卖出侧纪律保留")
        elif position_action == "REDUCE" or rule_action == "减仓" or position_risk_level == "HIGH" or {"买入", "加仓", "提高网格买入侧"} & blocked:
            action = "降低买入侧" if action == "维持" else action
            suggested_buy_qty = _round_qty((suggested_buy_qty or base_lot_qty) * 0.5)
            suggested_sell_qty = max(suggested_sell_qty or base_lot_qty, base_lot_qty)
            reasons.append("操作建议偏减仓或风险等级偏高，网格买入侧按保守仓位执行")
        elif position_action in {"ADD", "OPEN", "LIGHT_OPEN", "HOLD_OR_ADD"} and trend_score >= 75 and position_risk_level == "LOW":
            if action == "维持":
                reasons.append("操作建议偏加仓/建仓且趋势评分不低于75，网格可维持运行，但仍按总仓位、单只上限和加仓确认控制买入侧")

    if layer_payload:
        confidence = _num_or_zero(layer_payload.get("confidence"))
        total_score = _num_or_zero(layer_payload.get("total_score"))
        if confidence < 45 and action in {"调宽网格", "调窄网格"}:
            action = "维持"
            suggested_buy_fall = grid.buy_fall_pct if grid else suggested_buy_fall
            suggested_sell_rise = grid.sell_rise_pct if grid else suggested_sell_rise
            reasons.append("七层证据置信度不足，本次不做过细网格调参")
        if total_score <= -2 and action != "维持网格并风险提示":
            reasons.append("多层证据偏弱，买入侧按保守仓位执行")
            if suggested_buy_qty is not None:
                suggested_buy_qty = _round_qty(suggested_buy_qty * 0.5)
        elif total_score >= 2 and action in {"降低买入侧", "维持网格并风险提示"}:
            reasons.append("多层证据未完全转弱，降低买入侧后仍保留卖出侧纪律并观察修复")

    if trend_profit_continuation and grid:
        if grid.sell_rise_pct and suggested_sell_rise is not None and suggested_sell_rise < grid.sell_rise_pct:
            suggested_sell_rise = grid.sell_rise_pct
            reasons.append("趋势健康且已有盈利，卖出触发不因 ATR 公式收紧，沿用现有卖出上升幅度以保留盈利空间")
        if suggested_sell_qty is not None:
            suggested_sell_qty = min(suggested_sell_qty, base_lot_qty)

    grid_purpose = _grid_purpose(action, position, position_action, rule_action, strong_positive, hard_weak, trend_profit_continuation)
    guardrails = _strategy_guardrails(
        position, market, layer_payload, position_risk_level, trend_score, action, has_existing_grid, trend_profit_continuation
    )
    if _should_win_rate_cut_buy(guardrails):
        old_buy_qty = suggested_buy_qty
        suggested_buy_qty = _round_qty((suggested_buy_qty or base_lot_qty) * 0.5) if suggested_buy_qty is not None else None
        if old_buy_qty != suggested_buy_qty:
            reasons.append("胜率优先护栏触发，买入侧再降一档，宁可少赚也不扩大不确定仓位")
    if _should_win_rate_boost_sell(position, strong_positive, grid_purpose, trend_profit_continuation):
        suggested_sell_qty = max(suggested_sell_qty or base_lot_qty, _round_qty(base_lot_qty * 1.5))
        reasons.append("盈利保护护栏触发且趋势/风险确认不足，卖出侧保持更积极，不等待趋势完全破坏")
    suggested_buy_fall, suggested_sell_rise, suggested_buy_qty, suggested_sell_qty, mode_reason = _apply_trend_grid_mode(
        grid_mode,
        market,
        position,
        grid,
        overheat_level,
        base_lot_qty,
        suggested_buy_fall,
        suggested_sell_rise,
        suggested_buy_qty,
        suggested_sell_qty,
    )
    reasons.append(mode_reason)
    suggested_buy_qty, suggested_sell_qty, execution_checks, buy_execution_status, sell_execution_status = _apply_execution_checks(
        grid_mode,
        position,
        market,
        suggested_buy_qty,
        suggested_sell_qty,
    )
    reasons.extend(check["message"] for check in execution_checks if check.get("message"))
    action = _action_from_grid_mode(grid_mode, action, has_existing_grid)
    grid_purpose = _grid_purpose(action, position, position_action, rule_action, strong_positive, hard_weak, trend_profit_continuation)
    confirmation_pct = _confirmation_pct(base_eval.get("suggested_base") or (grid.base_price if grid else None) or market.last_price)
    suggested_buy_rebound = confirmation_pct
    suggested_sell_pullback = confirmation_pct
    suggested_min_base = _suggest_min_base_quantity(grid, position)
    suggested_max_position = _suggest_max_position_quantity(grid, position, suggested_buy_qty, base_lot_qty)
    if not reasons:
        reasons.append("缺少完整波动率或网格参数，建议先补齐数据")
    if grid_mode in {"WEAK_REDUCE", "ONLY_SELL_OR_CLEAR", "PAUSE"}:
        return _execution_plan_advice(
            grid=grid,
            market=market,
            position=position,
            action=action,
            grid_mode=grid_mode,
            grid_purpose=grid_purpose,
            base_eval=base_eval,
            suggested_sell_rise=suggested_sell_rise,
            suggested_sell_pullback=suggested_sell_pullback,
            suggested_sell_qty=suggested_sell_qty,
            execution_checks=execution_checks,
            sell_execution_status=sell_execution_status,
            guardrails=guardrails,
            reasons=reasons,
            layer_payload=layer_payload,
            rule_decision=rule_decision,
        )
    if not _has_bidirectional_lots(suggested_buy_qty, suggested_sell_qty, buy_execution_status, sell_execution_status):
        reasons.append("买入侧和卖出侧未同时具备 100 股整数倍数量，不满足双边网格定义；本次不输出网格建议")
        return _execution_plan_advice(
            grid=grid,
            market=market,
            position=position,
            action="暂停",
            grid_mode="PAUSE",
            grid_purpose="暂停策略",
            base_eval=base_eval,
            suggested_sell_rise=suggested_sell_rise,
            suggested_sell_pullback=suggested_sell_pullback,
            suggested_sell_qty=suggested_sell_qty,
            execution_checks=execution_checks,
            sell_execution_status=sell_execution_status,
            guardrails=guardrails,
            reasons=reasons,
            layer_payload=layer_payload,
            rule_decision=rule_decision,
        )

    return {
        "code": grid.code if grid else market.code,
        "name": grid.name if grid else market.name,
        "action": action,
        "grid_mode": grid_mode,
        "grid_mode_label": _grid_mode_label(grid_mode),
        "execution_checks": execution_checks,
        "buy_execution_status": buy_execution_status,
        "sell_execution_status": sell_execution_status,
        "cash_constraint_status": _cash_constraint_status(position),
        "grid_applicable": True,
        "grid_purpose": grid_purpose,
        "strategy_profile": STRATEGY_PROFILE,
        "strategy_guardrails": guardrails,
        "has_existing_grid": has_existing_grid,
        "base_price_status": base_eval["status"],
        "base_price_reason": base_eval["reason"],
        "current_base_price": grid.base_price if grid else None,
        "suggested_base_price": base_eval["suggested_base"],
        "current_buy_fall_pct": grid.buy_fall_pct if grid else None,
        "suggested_buy_fall_pct": suggested_buy_fall,
        "current_buy_rebound_pct": grid.buy_rebound_pct if grid else None,
        "suggested_buy_rebound_pct": suggested_buy_rebound,
        "current_sell_rise_pct": grid.sell_rise_pct if grid else None,
        "suggested_sell_rise_pct": suggested_sell_rise,
        "current_sell_pullback_pct": grid.sell_pullback_pct if grid else None,
        "suggested_sell_pullback_pct": suggested_sell_pullback,
        "current_quantity": current_qty or None,
        "current_buy_quantity": grid.buy_quantity if grid else None,
        "current_sell_quantity": grid.sell_quantity if grid else None,
        "suggested_buy_quantity": suggested_buy_qty if suggested_buy_qty is not None else None,
        "suggested_sell_quantity": suggested_sell_qty if suggested_sell_qty is not None else None,
        "current_min_base_quantity": grid.min_base_quantity if grid else None,
        "suggested_min_base_quantity": suggested_min_base,
        "current_max_position_quantity": grid.max_position_quantity if grid else None,
        "suggested_max_position_quantity": suggested_max_position,
        "reasons": list(dict.fromkeys(reasons)),
        "layered_confidence": layer_payload.get("confidence") if layer_payload else None,
        "layered_score": layer_payload.get("total_score") if layer_payload else None,
        "rule_decision": rule_decision,
    }


def _execution_plan_advice(
    grid: GridConfig | None,
    market: MarketSnapshot,
    position: Position | None,
    action: str,
    grid_mode: str,
    grid_purpose: str,
    base_eval: dict[str, Any],
    suggested_sell_rise: float | None,
    suggested_sell_pullback: float | None,
    suggested_sell_qty: float | None,
    execution_checks: list[dict[str, Any]],
    sell_execution_status: str,
    guardrails: list[str],
    reasons: list[str],
    layer_payload: dict[str, Any],
    rule_decision: dict[str, Any] | None,
) -> dict[str, Any]:
    if grid_mode == "ONLY_SELL_OR_CLEAR":
        plan_type = "CLEAR_PLAN"
        plan_label = "清仓/退出策略"
        plan_summary = "趋势失效或目标仓位归零，本次不再给网格建议；建议删除或暂停原双边网格，另按卖出计划处理。"
    elif grid_mode == "WEAK_REDUCE":
        plan_type = "REDUCE_PLAN"
        plan_label = "反弹减仓策略"
        plan_summary = "趋势不强，本次不再给网格建议；建议暂停原双边网格，按反弹减仓计划降低暴露。"
    else:
        plan_type = "PAUSE_PLAN"
        plan_label = "暂停策略"
        plan_summary = "交易条件不足或数据不可用，本次不生成网格建议。"
    reasons = _execution_plan_reasons(plan_summary, reasons)
    return {
        "code": grid.code if grid else market.code,
        "name": grid.name if grid else market.name,
        "action": action,
        "grid_mode": grid_mode,
        "grid_mode_label": _grid_mode_label(grid_mode),
        "execution_plan_type": plan_type,
        "execution_plan_label": plan_label,
        "execution_plan_summary": plan_summary,
        "execution_checks": execution_checks,
        "buy_execution_status": "DISABLED",
        "sell_execution_status": sell_execution_status,
        "cash_constraint_status": "NO_BUY",
        "grid_applicable": False,
        "grid_purpose": plan_label,
        "strategy_profile": STRATEGY_PROFILE,
        "strategy_guardrails": guardrails,
        "has_existing_grid": grid is not None,
        "base_price_status": base_eval["status"],
        "base_price_reason": base_eval["reason"],
        "current_base_price": grid.base_price if grid else None,
        "suggested_base_price": base_eval["suggested_base"],
        "current_buy_fall_pct": grid.buy_fall_pct if grid else None,
        "suggested_buy_fall_pct": None,
        "current_buy_rebound_pct": grid.buy_rebound_pct if grid else None,
        "suggested_buy_rebound_pct": None,
        "current_sell_rise_pct": grid.sell_rise_pct if grid else None,
        "suggested_sell_rise_pct": suggested_sell_rise,
        "current_sell_pullback_pct": grid.sell_pullback_pct if grid else None,
        "suggested_sell_pullback_pct": suggested_sell_pullback,
        "current_quantity": _current_quantity(grid) or None,
        "current_buy_quantity": grid.buy_quantity if grid else None,
        "current_sell_quantity": grid.sell_quantity if grid else None,
        "suggested_buy_quantity": None,
        "suggested_sell_quantity": suggested_sell_qty if suggested_sell_qty is not None else None,
        "current_min_base_quantity": grid.min_base_quantity if grid else None,
        "suggested_min_base_quantity": None,
        "current_max_position_quantity": grid.max_position_quantity if grid else None,
        "suggested_max_position_quantity": None,
        "reasons": reasons,
        "layered_confidence": layer_payload.get("confidence") if layer_payload else None,
        "layered_score": layer_payload.get("total_score") if layer_payload else None,
        "rule_decision": rule_decision,
    }


def _sell_only_grid_advice(
    grid: GridConfig,
    market: MarketSnapshot,
    position: Position | None,
    reasons: list[str],
    layer_payload: dict[str, Any],
) -> dict[str, Any]:
    plan_label = "分批减仓策略"
    plan_summary = "Touker 已有单边卖出条件单（分批出货），不是双边网格；本次不再输出网格参数，只按卖出执行策略处理。"
    reasons = _execution_plan_reasons(plan_summary, reasons)
    current_qty = _current_quantity(grid)
    return {
        "code": grid.code,
        "name": grid.name,
        "action": "只保留卖出",
        "grid_mode": "ONLY_SELL_OR_CLEAR",
        "grid_mode_label": _grid_mode_label("ONLY_SELL_OR_CLEAR"),
        "execution_plan_type": "REDUCE_PLAN",
        "execution_plan_label": plan_label,
        "execution_plan_summary": plan_summary,
        "execution_checks": [],
        "buy_execution_status": "DISABLED",
        "sell_execution_status": "ACTIVE" if grid.enabled else "DISABLED",
        "cash_constraint_status": "NO_BUY",
        "grid_applicable": False,
        "grid_purpose": plan_label,
        "strategy_profile": STRATEGY_PROFILE,
        "strategy_guardrails": ["单边卖出不是网格，只能作为减仓/清仓执行策略"],
        "has_existing_grid": True,
        "base_price_status": "单边条件单不评估基准价",
        "base_price_reason": "分批出货条件单只保留卖出侧，不生成买入网格参数",
        "current_base_price": grid.base_price,
        "suggested_base_price": None,
        "current_buy_fall_pct": None,
        "suggested_buy_fall_pct": None,
        "current_buy_rebound_pct": None,
        "suggested_buy_rebound_pct": None,
        "current_sell_rise_pct": grid.sell_rise_pct,
        "suggested_sell_rise_pct": grid.sell_rise_pct,
        "current_sell_pullback_pct": grid.sell_pullback_pct,
        "suggested_sell_pullback_pct": grid.sell_pullback_pct,
        "current_quantity": current_qty or None,
        "current_buy_quantity": None,
        "current_sell_quantity": grid.sell_quantity or None,
        "suggested_buy_quantity": None,
        "suggested_sell_quantity": current_qty or None,
        "current_min_base_quantity": None,
        "suggested_min_base_quantity": None,
        "current_max_position_quantity": None,
        "suggested_max_position_quantity": None,
        "reasons": reasons,
        "layered_confidence": layer_payload.get("confidence") if layer_payload else None,
        "layered_score": layer_payload.get("total_score") if layer_payload else None,
        "rule_decision": None,
    }


def _inactive_grid_advice(
    market: MarketSnapshot,
    grid: GridConfig | None,
    reasons: list[str],
    rule_decision: dict[str, Any] | None,
    layer_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "code": grid.code if grid else market.code,
        "name": grid.name if grid else market.name,
        "action": "暂不设网格",
        "grid_mode": "PAUSE",
        "grid_mode_label": _grid_mode_label("PAUSE"),
        "execution_checks": [],
        "cash_constraint_status": "NO_BUY",
        "grid_applicable": False,
        "grid_purpose": "暂不设网格",
        "strategy_profile": STRATEGY_PROFILE,
        "strategy_guardrails": ["未持仓且不适合建仓时不生成条件单，避免把观察标的误当可执行计划"],
        "has_existing_grid": grid is not None,
        "base_price_status": "暂不设网格",
        "current_base_price": grid.base_price if grid else None,
        "suggested_base_price": None,
        "reasons": list(dict.fromkeys(reasons)),
        "layered_confidence": layer_payload.get("confidence") if layer_payload else None,
        "layered_score": layer_payload.get("total_score") if layer_payload else None,
        "rule_decision": rule_decision,
    }


def _execution_plan_reasons(plan_summary: str, reasons: list[str]) -> list[str]:
    result = [plan_summary]
    for reason in reasons:
        text = str(reason)
        if not text or text == plan_summary:
            continue
        if "当前网格间距" in text or "买数量不按单只仓位上限" in text:
            continue
        if "可保留买入侧" in text or "买入侧先降速" in text or "买入侧降速" in text:
            text = "趋势或价格结构转弱，本次不新增买入，先按卖出执行策略降低暴露"
        text = text.replace("网格买入", "买入")
        text = text.replace("网格切换为弱势减仓", "执行策略切换为反弹减仓")
        text = text.replace("网格切换为只卖清仓", "执行策略切换为清仓/退出")
        text = text.replace("趋势偏弱或暂停模式下", "执行策略模式下")
        result.append(text)
    return list(dict.fromkeys(result))


def _has_bidirectional_lots(
    buy_qty: float | None,
    sell_qty: float | None,
    buy_status: str,
    sell_status: str,
) -> bool:
    return (
        buy_status == "ACTIVE"
        and sell_status == "ACTIVE"
        and buy_qty is not None
        and sell_qty is not None
        and buy_qty >= 100
        and sell_qty >= 100
        and buy_qty % 100 == 0
        and sell_qty % 100 == 0
    )


def _grid_applicable(has_existing_grid: bool, position: Position | None, rule_action: str, position_action: str) -> bool:
    if has_existing_grid or position:
        return True
    return rule_action in {"建仓", "轻仓建仓"} or position_action in {"OPEN", "LIGHT_OPEN"}


def _grid_mode_from_decision(trend_score: float, overheat_level: str, position_action: str, rule_action: str) -> str:
    if position_action in {"NO_ACTION"} or rule_action in {"禁止交易"}:
        return "PAUSE"
    if trend_score < 45 or position_action in {"EXIT_TREND_POSITION", "EXIT_SHORT_TERM"} or rule_action in {"退出短线仓位"}:
        return "ONLY_SELL_OR_CLEAR"
    if trend_score < 60 or position_action in {"REDUCE", "TREND_REVIEW", "RISK_REVIEW"} or rule_action in {"减仓", "趋势复核", "风控复核"}:
        return "WEAK_REDUCE"
    if overheat_level in {"OVERHEATED", "SEVERE_OVERHEATED"}:
        return "PROFIT_PROTECTION"
    if trend_score >= 85:
        if position_action == "HOLD":
            return "TREND_HOLD_GRID"
        return "TREND_ADD"
    if trend_score >= 75:
        return "TREND_HOLD_GRID"
    return "BALANCED_GRID"


def _grid_mode_label(mode: str) -> str:
    return GRID_MODE_LABELS.get(mode, mode or "待定")


def _action_from_grid_mode(mode: str, current_action: str, has_existing_grid: bool) -> str:
    if mode == "PAUSE":
        return "暂停"
    if mode == "ONLY_SELL_OR_CLEAR":
        return "只卖清仓"
    if mode == "WEAK_REDUCE":
        return "弱势减仓"
    if mode == "PROFIT_PROTECTION":
        return "高位保护"
    if mode == "TREND_ADD":
        return "趋势加仓" if has_existing_grid else "新建网格"
    if mode == "TREND_HOLD_GRID":
        return "趋势持有"
    if mode == "BALANCED_GRID":
        return "震荡滚动"
    return current_action


def _apply_trend_grid_mode(
    mode: str,
    market: MarketSnapshot,
    position: Position | None,
    grid: GridConfig | None,
    overheat_level: str,
    base_lot_qty: float,
    buy_fall: float | None,
    sell_rise: float | None,
    buy_qty: float | None,
    sell_qty: float | None,
) -> tuple[float | None, float | None, float | None, float | None, str]:
    atr_pct = market.atr14_pct or _current_step(grid) or 3.0
    current_qty = _round_lot_down(position.quantity) if position else 0
    base_qty = _round_lot_down(base_lot_qty) or 100
    if mode == "TREND_ADD":
        next_buy = max(base_qty, _round_lot_down(sell_qty or base_qty))
        next_sell = _round_lot_down(min(sell_qty or base_qty, current_qty / 3)) if current_qty else sell_qty
        return (
            _round_pct(_clamp(atr_pct * 0.85, 1.8, 2.8)),
            _round_pct(max(sell_rise or 0, _clamp(atr_pct * 1.4, 4.0, 6.0))),
            next_buy,
            next_sell or 0,
            "趋势强且未过热，网格切换为趋势加仓：买入积极，卖出放慢并保留趋势仓",
        )
    if mode == "TREND_HOLD_GRID":
        return (
            _round_pct(_clamp(atr_pct * 0.9, 2.5, 3.3)),
            _round_pct(_clamp(atr_pct * 0.9, 2.6, 3.8)),
            base_qty,
            _round_lot_down(min(sell_qty or base_qty, current_qty)) if current_qty else sell_qty,
            "趋势仍在，网格切换为趋势持有：买卖均衡但不追高",
        )
    if mode == "PROFIT_PROTECTION":
        severe = overheat_level == "SEVERE_OVERHEATED"
        next_buy = 100 if current_qty else None
        if not severe:
            next_buy = min(_round_lot_down(buy_qty or base_qty), 100)
        sell_floor = current_qty / 2 if severe and current_qty else sell_qty or base_qty
        next_sell = _round_lot_down(max(sell_qty or base_qty, sell_floor))
        return (
            _round_pct(_clamp(atr_pct * 1.2, 3.5, 5.0)),
            _round_pct(_clamp(atr_pct * 0.8, 2.5, 3.5)),
            next_buy,
            next_sell,
            "短线过热，网格切换为高位保护：降低买入，卖出更积极",
        )
    if mode == "BALANCED_GRID":
        return (
            _round_pct(_clamp(atr_pct * 0.9, 2.5, 3.5)),
            _round_pct(_clamp(atr_pct * 0.9, 2.5, 4.0)),
            base_qty,
            _round_lot_down(min(sell_qty or base_qty, current_qty)) if current_qty else sell_qty,
            "震荡偏强，网格切换为震荡滚动：小额均衡，不扩大单边暴露",
        )
    if mode == "WEAK_REDUCE":
        next_sell = _round_lot_down(max(sell_qty or base_qty, current_qty / 3)) if current_qty else sell_qty
        return (
            buy_fall,
            sell_rise,
            0,
            next_sell,
            "趋势不强，执行策略切换为反弹减仓：买入侧停用，反弹分批卖出",
        )
    if mode == "ONLY_SELL_OR_CLEAR":
        return (
            buy_fall,
            sell_rise,
            0,
            current_qty,
            "趋势失效，执行策略切换为清仓/退出：买入侧停用，卖出不超过当前持仓",
        )
    return buy_fall, sell_rise, 0, 0, "规则禁止交易或数据不可用，本次暂停网格"


def _apply_execution_checks(
    mode: str,
    position: Position | None,
    market: MarketSnapshot,
    buy_qty: float | None,
    sell_qty: float | None,
) -> tuple[float | None, float | None, list[dict[str, Any]], str, str]:
    checks: list[dict[str, Any]] = []
    current_qty = _round_lot_down(position.quantity) if position else 0
    buy_status = "ACTIVE"
    sell_status = "ACTIVE"
    if mode in {"WEAK_REDUCE", "ONLY_SELL_OR_CLEAR", "PAUSE"}:
        normalized_buy = None
        buy_status = "DISABLED"
        checks.append({"check": "buy_side_disabled", "status": "fixed", "message": "趋势偏弱或暂停模式下，买入侧已标记为停用，不输出零股条件单"})
    elif market.last_price <= 0:
        normalized_buy = None
        buy_status = "INVALID_PRICE"
        checks.append({"check": "valid_price", "status": "fixed", "message": "最新价无效，买入侧已标记为不可执行"})
    elif buy_qty is not None and buy_qty <= 0:
        normalized_buy = None
        buy_status = "DISABLED"
        checks.append({"check": "buy_side_disabled", "status": "fixed", "message": "买入侧数量小于一手，已标记为停用，不输出零股条件单"})
    elif buy_qty is None:
        normalized_buy = None
        buy_status = "DISABLED"
    else:
        normalized_buy = _round_order_lot(buy_qty)

    if not position or current_qty < 100:
        normalized_sell = None
        sell_status = "NO_TRADABLE_LOT"
        checks.append({"check": "sell_side_has_lot", "status": "fixed", "message": "当前持仓不足一手，卖出侧不输出零股条件单"})
    elif sell_qty is None or sell_qty <= 0:
        normalized_sell = None
        sell_status = "DISABLED"
    else:
        normalized_sell = _round_lot_down(sell_qty)
        if normalized_sell < 100:
            normalized_sell = None
            sell_status = "BELOW_MIN_LOT"
            checks.append({"check": "sell_side_min_lot", "status": "fixed", "message": "卖出侧不足一手，已标记为暂不设置卖出条件单"})
        elif normalized_sell > current_qty:
            normalized_sell = current_qty
            checks.append({"check": "sell_qty_lte_position", "status": "fixed", "message": "卖出数量超过当前持仓，已按持仓上限自动修正"})
        else:
            checks.append({"check": "sell_qty_lte_position", "status": "ok", "message": ""})

    if _was_lot_fixed(buy_qty, normalized_buy) or _was_lot_fixed(sell_qty, normalized_sell):
        checks.append({"check": "round_lot", "status": "fixed", "message": "买卖数量已按 100 股整数倍修正，且不输出零股条件单"})
    checks.append({"check": "buy_cash", "status": "unknown", "message": "当前未采集可用现金，买入数量不按单只仓位上限放大"})
    return normalized_buy, normalized_sell, checks, buy_status, sell_status


def _cash_constraint_status(position: Position | None) -> str:
    if position and position.account_total_asset:
        return "NO_AVAILABLE_CASH_FIELD"
    return "UNKNOWN_NO_CASH_FIELD"


def _grid_purpose(
    action: str,
    position: Position | None,
    position_action: str,
    rule_action: str,
    strong_positive: bool,
    hard_weak: bool,
    trend_profit_continuation: bool,
) -> str:
    if not position:
        return "建仓网格"
    if action in {"只保留卖出", "暂停买入侧", "只卖清仓", "弱势减仓"} or position_action in {"REDUCE", "TREND_REVIEW", "EXIT_TREND_POSITION", "RISK_REVIEW", "EXIT_SHORT_TERM"} or rule_action in {"减仓", "趋势复核", "风控复核", "退出短线仓位"}:
        return "止盈/退出网格"
    if strong_positive and position.pnl_pct > 0 and not trend_profit_continuation:
        return "止盈网格"
    if hard_weak:
        return "防守网格"
    if action == "高位保护":
        return "止盈网格"
    if action == "震荡滚动":
        return "持仓网格"
    if position_action in {"ADD", "HOLD_WAIT_ADD"} or action == "趋势加仓":
        return "加仓网格"
    return "持仓网格"


def _strategy_guardrails(
    position: Position | None,
    market: MarketSnapshot,
    layer_payload: dict[str, Any],
    risk_level: str,
    trend_score: float,
    action: str,
    has_existing_grid: bool,
    trend_profit_continuation: bool,
) -> list[str]:
    guardrails = ["条件单用于替代盯盘，只给当前时点一套可执行参数"]
    confidence = _num_or_zero(layer_payload.get("confidence")) if layer_payload else 0
    if confidence < 60:
        guardrails.append("七层证据未完整接入，仅作复核提示")
    if risk_level == "HIGH" or trend_score < 60 or "降低" in action or "暂停" in action:
        guardrails.append("趋势或风险未确认，宁可少赚，不用网格扩大不确定仓位")
    if position and position.pnl_pct > 0:
        if trend_profit_continuation:
            guardrails.append("已有盈利但趋势健康，浮盈不是卖出充分条件，网格保留继续盈利空间")
        else:
            guardrails.append("已有盈利且趋势/风险未完全确认时，优先保留分批兑现纪律")
    if position and (position.position_pct or 0) >= 5:
        guardrails.append("仓位偏高时不提高买入侧，优先控制回撤和重复暴露")
    if not has_existing_grid and not position:
        guardrails.append("未持仓建仓只做小额试探，不假设现金充足")
    return list(dict.fromkeys(guardrails))


def _should_win_rate_cut_buy(guardrails: list[str]) -> bool:
    text = "；".join(guardrails)
    return any(token in text for token in ("风险未确认", "仓位偏高"))


def _should_win_rate_boost_sell(
    position: Position | None,
    strong_positive: bool,
    grid_purpose: str,
    trend_profit_continuation: bool,
) -> bool:
    if trend_profit_continuation:
        return False
    return bool(position and position.pnl_pct >= 3 and (strong_positive or grid_purpose in {"止盈网格", "止盈/退出网格"}))


def _evaluate_base_price(
    grid: GridConfig | None,
    market: MarketSnapshot,
    position: Position | None,
    hard_weak: bool,
    strong_positive: bool,
    trend_profit_continuation: bool,
) -> dict[str, Any]:
    if not grid or not grid.base_price:
        suggested = _new_base_price(market, position)
        return {
            "status": "新建建议基准",
            "suggested_base": suggested,
            "reason": "无现有 Touker 基准价，按当前价、MA20/BOLL中轨和建仓状态给出建议基准",
            "reasons": ["无现有 Touker 基准价，需新建建议基准"],
        }
    base = grid.base_price
    current = market.last_price
    atr_pct = market.atr14_pct or grid.grid_step_pct or _avg(grid.buy_fall_pct, grid.sell_rise_pct) or 3.0
    deviation_pct = abs(base / current - 1) * 100 if current > 0 else 0
    threshold = max(2 * atr_pct, 6.0)
    outside_range = bool((grid.lower_price and current < grid.lower_price) or (grid.upper_price and current > grid.upper_price))
    reasons: list[str] = []
    if strong_positive and position and position.pnl_pct > 0 and base < current and deviation_pct <= max(3 * atr_pct, 10.0):
        if trend_profit_continuation:
            reasons.append("已有盈利且趋势健康，基准价不追高上移；保留现有卖出纪律和继续盈利空间")
        else:
            reasons.append("已有盈利且价格接近上轨但趋势/风险确认不足，基准价不轻易上移，优先保留分批止盈纪律")
        return {
            "status": "维持现有基准",
            "suggested_base": _round_price(base),
            "reason": "盈利持仓结合趋势管理，现有基准仍可用",
            "reasons": reasons,
        }
    if deviation_pct > threshold or outside_range:
        if hard_weak and position and position.pnl_pct < 0:
            suggested = _round_price(_reference_price(market, prefer_upper=True) or current)
            reasons.append("现有基准与当前波动区间偏离较大；弱势浮亏场景下调整基准只配合降低买入侧，不用于鼓励补仓")
        else:
            suggested = _round_price(_reference_price(market) or current)
            reasons.append("现有基准价与当前价格/技术中枢偏离较大，买卖触发可能失真，建议调整基准")
        return {
            "status": "建议调整基准",
            "suggested_base": suggested,
            "reason": f"基准偏离当前价 {deviation_pct:.2f}%，阈值约 {threshold:.2f}%",
            "reasons": reasons,
        }
    reasons.append("现有 Touker 基准价仍在当前 ATR 波动容忍范围内")
    return {
        "status": "维持现有基准",
        "suggested_base": _round_price(base),
        "reason": f"基准偏离当前价 {deviation_pct:.2f}%，未超过约 2 倍 ATR14 容忍范围",
        "reasons": reasons,
    }


def _new_base_price(market: MarketSnapshot, position: Position | None) -> float:
    if position:
        ref = _reference_price(market) or market.last_price
        if position.pnl_pct < 0:
            return _round_price(max(ref, market.last_price))
        return _round_price(ref)
    refs = [value for value in (market.ma20, market.boll_mid, market.last_price) if value]
    if not refs:
        return _round_price(market.last_price)
    if market.ma20 and market.last_price > market.ma20:
        return _round_price(min(market.last_price, max(value for value in refs if value)))
    return _round_price(market.last_price)


def _reference_price(market: MarketSnapshot, prefer_upper: bool = False) -> float | None:
    refs = [value for value in (market.ma20, market.boll_mid, market.ma60 if prefer_upper else None, market.last_price) if value]
    if not refs:
        return None
    return max(refs) if prefer_upper else sum(refs) / len(refs)


def _is_profit_trend_continuation(
    position: Position | None,
    trend_score: float,
    risk_level: str,
    hard_weak: bool,
    soft_weak: bool,
    position_action: str,
    rule_action: str,
) -> bool:
    if not position or position.pnl_pct <= 0:
        return False
    if trend_score < 75 or risk_level != "LOW":
        return False
    if hard_weak or soft_weak:
        return False
    if position_action in {"REDUCE", "TREND_REVIEW", "EXIT_TREND_POSITION", "RISK_REVIEW", "EXIT_SHORT_TERM"}:
        return False
    if rule_action in {"减仓", "趋势复核", "风控复核", "退出短线仓位"}:
        return False
    return True


def _suggest_min_base_quantity(grid: GridConfig | None, position: Position | None) -> float:
    if position and position.quantity > 0:
        keep_ratio = 0.5 if (position.position_pct or 0) >= 2 else 0.0
        return _round_qty(position.quantity * keep_ratio) if keep_ratio else 0
    return grid.min_base_quantity if grid and grid.min_base_quantity is not None else 0


def _suggest_max_position_quantity(grid: GridConfig | None, position: Position | None, suggested_buy_qty: float | None, base_lot_qty: float) -> float:
    if grid and grid.max_position_quantity:
        return _round_qty(grid.max_position_quantity)
    step = suggested_buy_qty or base_lot_qty
    if position and position.quantity > 0:
        return _round_qty(max(position.quantity + step * 3, position.quantity * 1.5))
    return _round_qty(step * 3)


def _current_step(grid: GridConfig | None) -> float | None:
    if not grid:
        return None
    return grid.grid_step_pct or _avg(grid.buy_fall_pct, grid.sell_rise_pct)


def _current_quantity(grid: GridConfig | None) -> float:
    if not grid:
        return 0
    return grid.order_quantity or grid.buy_quantity or grid.sell_quantity or grid.grid_step_amount or 0


def _initial_quantity(position: Position | None) -> float:
    if not position or position.quantity <= 0:
        return 100
    return min(max(100, position.quantity * 0.2), position.quantity)


def _avg(left: float | None, right: float | None) -> float | None:
    values = [value for value in (left, right) if value is not None]
    return sum(values) / len(values) if values else None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _confirmation_pct(base_price: float | None) -> float | None:
    if base_price is None:
        return None
    if base_price <= 1:
        return 0.20
    if base_price <= 2:
        return 0.15
    if base_price <= 3:
        return 0.10
    if base_price <= 5:
        return 0.07
    if base_price <= 8:
        return 0.05
    return 0.03


def _round_pct(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _round_price(value: float) -> float:
    return round(value, 4)


def _round_qty(value: float) -> float:
    return max(100, round(value / 100) * 100)


def _round_order_lot(value: float | None) -> float | None:
    if value is None or value <= 0:
        return None
    return max(100, _round_lot_down(value) or 100)


def _round_lot_down(value: float | None) -> float:
    if value is None or value <= 0:
        return 0
    return (int(value) // 100) * 100


def _was_lot_fixed(original: float | None, normalized: float | None) -> bool:
    if original is None or original <= 0:
        return False
    if normalized is None:
        return True
    return abs(float(original) - float(normalized)) > 1e-9


def _num_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
