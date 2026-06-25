from __future__ import annotations

from typing import Any

from etfmate.analysis.layered_context import LayeredContext, normalize_context
from etfmate.storage.models import GridConfig, MarketSnapshot, Position

STRATEGY_PROFILE = "条件单代替盯盘；胜率优先；不追求吃完整段行情；盈利看趋势管理；不深研标的时默认保守"


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
    layer_payload = normalize_context(layered_context)

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
            reasons.append("目标仓位为 0 且仍有持仓，网格买入不再按正常数量建议；需人工停用买触发或只保留卖出纪律")
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
    confirmation_pct = _confirmation_pct(base_eval.get("suggested_base") or (grid.base_price if grid else None) or market.last_price)
    suggested_buy_rebound = confirmation_pct
    suggested_sell_pullback = confirmation_pct
    suggested_min_base = _suggest_min_base_quantity(grid, position)
    suggested_max_position = _suggest_max_position_quantity(grid, position, suggested_buy_qty, base_lot_qty)
    if not reasons:
        reasons.append("缺少完整波动率或网格参数，建议先补齐数据")

    return {
        "code": grid.code if grid else market.code,
        "name": grid.name if grid else market.name,
        "action": action,
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


def _grid_applicable(has_existing_grid: bool, position: Position | None, rule_action: str, position_action: str) -> bool:
    if has_existing_grid or position:
        return True
    return rule_action in {"建仓", "轻仓建仓"} or position_action in {"OPEN", "LIGHT_OPEN"}


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
    if action in {"只保留卖出", "暂停买入侧"} or position_action in {"REDUCE", "TREND_REVIEW", "EXIT_TREND_POSITION", "RISK_REVIEW", "EXIT_SHORT_TERM"} or rule_action in {"减仓", "趋势复核", "风控复核", "退出短线仓位"}:
        return "止盈/退出网格"
    if strong_positive and position.pnl_pct > 0 and not trend_profit_continuation:
        return "止盈网格"
    if hard_weak:
        return "防守网格"
    if position_action in {"ADD", "HOLD_WAIT_ADD"}:
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
        guardrails.append("七层证据未完整接入，仅作复核提示，不单独压低强趋势买入")
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


def _num_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
