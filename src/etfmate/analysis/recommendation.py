from __future__ import annotations

from typing import Any

from etfmate.analysis.layered_context import LayeredContext, normalize_context
from etfmate.analysis.rule_engine import decide_position
from etfmate.storage.models import GridConfig, MarketSnapshot, Position


def recommend(
    position: Position | None,
    grid: GridConfig | None,
    market: MarketSnapshot,
    all_positions: list[Position] | None = None,
    all_markets: list[MarketSnapshot] | None = None,
    layered_context: LayeredContext | dict[str, Any] | None = None,
) -> dict:
    action = "持有"
    reasons: list[str] = []
    risks: list[str] = []
    scores: list[str] = []

    boll_pos = _boll_position(market)
    bias6 = market.bias6 or 0
    holding_weight = position.market_value if position else 0
    portfolio_value = sum(item.market_value for item in (all_positions or []) if item.market_value > 0)
    position_weight_pct = position.position_pct if position and position.position_pct is not None else (holding_weight / portfolio_value * 100 if portfolio_value else 0)
    position_tier = _position_tier(position_weight_pct)
    above_ma20 = bool(market.ma20 and market.last_price >= market.ma20)
    above_ma60 = bool(market.ma60 and market.last_price >= market.ma60)
    vol_expanding = bool(market.vol_ma5 and market.vol_ma20 and market.vol_ma5 > market.vol_ma20 * 1.2)
    vol_shrinking = bool(market.vol_ma5 and market.vol_ma20 and market.vol_ma5 < market.vol_ma20 * 0.75)
    very_small_holding = bool(position and (position.quantity <= 200 or position_weight_pct <= 0.5))
    low_weight = bool(position and position_weight_pct < 2)
    high_weight = bool(position and position_weight_pct >= 5)
    very_high_weight = bool(position and position_weight_pct >= 8)
    low_zone = bool(boll_pos is not None and boll_pos <= 0.25) or bias6 <= -3
    high_zone = bool(boll_pos is not None and boll_pos >= 0.9) or bias6 >= 5
    overheat = bool(boll_pos is not None and boll_pos >= 0.98) or bias6 >= 6
    hard_weak = bool(market.ma20 and market.ma60 and market.last_price < market.ma20 and market.last_price < market.ma60)
    soft_weak = bool(market.ma60 and market.last_price < market.ma60)
    rule_decision = decide_position(position, grid, market, all_positions or [], all_markets or [])

    if boll_pos is not None:
        scores.append(f"BOLL分位 {boll_pos:.0%}")
    if market.atr14_pct:
        scores.append(f"ATR14 {market.atr14_pct:.2f}%")
    if market.bias6 is not None:
        scores.append(f"BIAS6 {market.bias6:.2f}%")
    if market.vol_ma5 and market.vol_ma20:
        scores.append(f"VOL5/20 {market.vol_ma5 / market.vol_ma20:.2f}倍")

    if not position:
        if low_zone and not hard_weak:
            action = "买入"
            reasons.append("无当前持仓且价格进入低位区，可按单格小仓位试探")
        else:
            reasons.append("无当前持仓，等待更明确的低位或趋势修复信号")
    elif very_small_holding:
        if low_zone and not hard_weak:
            action = "分批加仓"
            reasons.append("仓位极低且价格处于低位区，可小额补到观察仓")
        elif overheat:
            action = "持有"
            reasons.append("仓位极低，即使短线过热也不建议为了止盈把观察仓减到 0")
        elif hard_weak:
            action = "持有"
            risks.append("仓位极低且趋势偏弱，先观察，不扩大买入侧")
        else:
            reasons.append("仓位极低，当前以观察和保留网格纪律为主")
    elif low_zone and not hard_weak and not high_weight:
        action = "分批加仓"
        reasons.append("仓位不高且价格进入低位区，可小额分批加仓")
    elif (overheat or (high_zone and high_weight)) and (position.pnl_pct > 0 or high_weight):
        action = "减仓" if not very_small_holding else "持有"
        reasons.append("价格处于高位区且短线偏离较大，适合用网格或小比例兑现")
    elif hard_weak and (high_weight or position.pnl_pct <= -8):
        action = "暂停买入侧" if grid and grid.enabled else "持有"
        risks.append("价格同时低于 MA20/MA60，且仓位或亏损压力不低，先暂停新增买入")
    elif soft_weak and high_weight:
        action = "暂停买入侧" if grid and grid.enabled else "持有"
        risks.append("价格低于 MA60 且仓位偏高，买入侧先降速")
    else:
        reasons.append("仓位、趋势和波动暂未触发强动作信号")

    if above_ma20 and above_ma60:
        reasons.append("价格同时站上 MA20/MA60，趋势结构偏强")
    elif not above_ma20 and not above_ma60 and market.ma20 and market.ma60:
        risks.append("价格低于 MA20/MA60，趋势结构偏弱")
    elif not above_ma20 and market.ma20:
        risks.append("价格低于 MA20，短线仍需等待修复")

    if vol_expanding:
        reasons.append("VOL MA5 高于 MA20，近期成交活跃度抬升")
    elif vol_shrinking:
        risks.append("成交量低于近20日均量，反弹持续性需要验证")

    if position:
        note_signal = _note_signal(position.note)
        if note_signal == "positive" and above_ma20 and above_ma60 and not vol_shrinking:
            reasons.append("你的备注偏看好，且趋势/量能暂未冲突，可作为持仓依据之一")
        elif note_signal == "positive" and (not above_ma60 or vol_shrinking):
            risks.append("你的备注偏看好，但市场趋势或量能没有确认，先降低加仓强度")
        elif note_signal == "negative" and (not above_ma20 or not above_ma60):
            reasons.append("你的备注偏谨慎，且市场信号偏弱，减仓或暂停买入侧更匹配")
        elif note_signal == "negative" and above_ma20 and above_ma60:
            risks.append("你的备注偏谨慎，但市场趋势偏强，卖出前需避免过早离场")

        if position.pnl_pct <= -10:
            risks.append("持仓浮亏超过 10%，加仓前先确认仓位上限和趋势修复")
        elif position.pnl_pct >= 25 and bias6 > 2:
            if very_small_holding:
                risks.append("观察仓已有高浮盈，不扩大买入，也不为了止盈减到 0")
            else:
                reasons.append("已有较高浮盈且短线偏离为正，可考虑网格止盈或小幅减仓")
            if action == "持有" and not very_small_holding:
                action = "减仓"
        if holding_weight > 5000 and not above_ma20:
            risks.append("单只市值较高且短线弱于 MA20，避免继续集中补仓")
        if very_high_weight and action in {"买入", "分批买入", "分批加仓"}:
            action = "持有"
            risks.append("当前仓位占比已经偏高，即便低位也不建议继续扩大买入数量")
        if high_zone and very_small_holding and action == "减仓":
            action = "持有"
            risks.append("当前只是观察仓，不建议把小仓位减到 0")

    overlap_note = _overlap_note(position, all_positions or [])
    if overlap_note:
        risks.append(overlap_note)

    if market.data_quality != "ok":
        risks.append(f"行情数据完整性: {market.data_quality}")

    layer_payload = normalize_context(layered_context)
    if layer_payload:
        confidence = _num_or_zero(layer_payload.get("confidence"))
        total_score = _num_or_zero(layer_payload.get("total_score"))
        if confidence < 45 and action in {"买入", "卖出"}:
            action = "分批买入" if action == "买入" else "减仓"
            risks.append("七层证据置信度不足，强动作降级为分批或部分处理")
        elif confidence < 45 and action in {"分批买入", "分批加仓"}:
            risks.append("七层证据置信度不足，只适合小额试探，不适合扩大仓位")
        if total_score <= -2 and action in {"买入", "分批买入", "分批加仓"}:
            action = "持有"
            risks.append("多层证据偏弱，暂不把低位信号直接解释为加仓信号")
        elif total_score >= 2 and action == "减仓" and position and position.pnl_pct < 0:
            risks.append("多层证据未明显转弱，亏损仓位不宜一次性大幅减仓")

    action = _merge_rule_action(action, rule_decision)
    reasons = list(dict.fromkeys(rule_decision.get("reasons", []) + reasons))
    risks = list(dict.fromkeys((rule_decision.get("risks") or []) + risks))
    action_quantity, position_plan = _action_plan(action, position, grid)
    reasons = _clean_reasons_for_action(action, reasons)
    return {
        "code": market.code,
        "name": market.name,
        "quantity": position.quantity if position else None,
        "available_quantity": position.available_quantity if position else None,
        "market_value": position.market_value if position else None,
        "position_pct": position.position_pct if position else None,
        "position_tier": position_tier,
        "investor_note": position.note if position else None,
        "cost_price": position.cost_price if position else None,
        "last_price": market.last_price,
        "pct_chg": market.pct_chg,
        "pnl_pct": position.pnl_pct if position else None,
        "boll_position_pct": round(boll_pos * 100, 1) if boll_pos is not None else None,
        "boll_lower": market.boll_lower,
        "boll_mid": market.boll_mid,
        "boll_upper": market.boll_upper,
        "ma_status": _ma_status(market),
        "ma5": market.ma5,
        "ma10": market.ma10,
        "ma20": market.ma20,
        "ma60": market.ma60,
        "ma120": market.ma120,
        "ma200": market.ma200,
        "atr7_pct": market.atr7_pct,
        "atr14_pct": market.atr14_pct,
        "atr30_pct": market.atr30_pct,
        "atr60_pct": market.atr60_pct,
        "bias6": market.bias6,
        "bias12": market.bias12,
        "bias24": market.bias24,
        "volume": market.volume,
        "vol_ma5": market.vol_ma5,
        "vol_ma20": market.vol_ma20,
        "amount_avg20": market.amount_avg20,
        "amount_ratio20": market.amount_ratio20,
        "rsi14": market.rsi14,
        "ret3": market.ret3,
        "ret5": market.ret5,
        "ret20": market.ret20,
        "ret60": market.ret60,
        "max_drawdown_60": market.max_drawdown_60,
        "ma20_slope_pct": market.ma20_slope_pct,
        "kline_days": market.kline_days,
        "vol_ratio": market.vol_ratio,
        "turnover_pct": market.turnover_pct,
        "amplitude_pct": market.amplitude_pct,
        "current_status": _status(position, grid, market),
        "action": action,
        "action_quantity": action_quantity,
        "position_plan": position_plan,
        "reasons": reasons,
        "risks": risks or ["暂无明显新增风险"],
        "watch_price": _watch_price(market),
        "indicators": "；".join(scores) if scores else "指标不足",
        "layered_context": layer_payload,
        "layered_confidence": layer_payload.get("confidence") if layer_payload else None,
        "layered_score": layer_payload.get("total_score") if layer_payload else None,
        "rule_decision": rule_decision,
        "rule_total_score": rule_decision.get("total_score"),
        "rule_trend_score": rule_decision.get("trend_score"),
        "rule_momentum_score": rule_decision.get("momentum_score"),
        "rule_risk_score": rule_decision.get("risk_score"),
        "rule_filter_status": rule_decision.get("filter_status"),
    }


def _status(position: Position | None, grid: GridConfig | None, market: MarketSnapshot) -> str:
    parts = [f"现价 {market.last_price:.3f}，涨跌幅 {market.pct_chg:.2f}%"]
    if position:
        parts.append(f"持仓 {position.quantity:g} 份，浮盈亏 {position.pnl_pct:.2f}%")
    if grid:
        parts.append("网格已启用" if grid.enabled else "网格暂停")
    return "；".join(parts)


def _position_tier(position_weight_pct: float | None) -> str:
    value = position_weight_pct or 0
    if value <= 0.5:
        return "观察仓"
    if value < 2:
        return "低仓位"
    if value < 5:
        return "中等仓位"
    if value < 8:
        return "偏高仓位"
    return "高仓位"


def _clean_reasons_for_action(action: str, reasons: list[str]) -> list[str]:
    if action == "持有":
        return reasons
    return [reason for reason in reasons if "暂未触发强动作信号" not in reason]


def _merge_rule_action(current_action: str, rule_decision: dict[str, Any]) -> str:
    rule_action = str(rule_decision.get("action") or "")
    blocked = set(rule_decision.get("blocked_actions") or [])
    if current_action in {"减仓", "卖出"} and {"减仓", "卖出"} & blocked:
        return "持有"
    if rule_action in {"禁止交易", "卖出", "减仓"}:
        return rule_action
    if current_action in {"暂停网格", "暂停买入侧"} and rule_action in {"观察", "持有", "减仓"}:
        return current_action
    if rule_action in {"分批买入", "分批加仓", "观察"}:
        return rule_action
    return current_action


def _watch_price(market: MarketSnapshot) -> str:
    if not market.boll_lower or not market.boll_upper or not market.ma20:
        return "等待补齐 K 线指标"
    if market.last_price >= market.boll_upper:
        return f"偏高：接近或高于 BOLL 上轨 {market.boll_upper:.3f}，优先看止盈/减仓"
    if market.last_price <= market.boll_lower:
        return f"偏低：接近或低于 BOLL 下轨 {market.boll_lower:.3f}，只适合小额分批观察"
    if market.last_price < market.ma20:
        return f"偏弱：先看能否重新站上 MA20 {market.ma20:.3f}"
    return f"中性偏强：上方看 BOLL 上轨 {market.boll_upper:.3f}，跌破 MA20 {market.ma20:.3f} 转谨慎"


def _ma_status(market: MarketSnapshot) -> str:
    states = []
    if market.ma5:
        states.append("上MA5" if market.last_price >= market.ma5 else "下MA5")
    if market.ma10:
        states.append("上MA10" if market.last_price >= market.ma10 else "下MA10")
    if market.ma20:
        states.append("上MA20" if market.last_price >= market.ma20 else "下MA20")
    if market.ma60:
        states.append("上MA60" if market.last_price >= market.ma60 else "下MA60")
    if market.ma200:
        states.append("上MA200" if market.last_price >= market.ma200 else "下MA200")
    return "/".join(states) if states else "均线不足"


def _boll_position(market: MarketSnapshot) -> float | None:
    if not market.boll_upper or not market.boll_lower or market.boll_upper == market.boll_lower:
        return None
    return (market.last_price - market.boll_lower) / (market.boll_upper - market.boll_lower)


def _action_plan(action: str, position: Position | None, grid: GridConfig | None) -> tuple[float | None, str]:
    quantity = position.quantity if position else None
    grid_qty = grid.order_quantity if grid else None
    if not position:
        if action in {"买入", "分批买入"}:
            return grid_qty or 100, "无当前持仓，只适合按单格小仓位试探"
        if action in {"观察", "禁止交易"}:
            return None, "无当前持仓，暂不新开仓"
        return None, "无当前持仓"
    if action == "禁止交易":
        return None, "触发硬过滤条件，本次不新增交易动作"
    if action == "观察":
        return None, "保留观察，不新增买入或卖出动作"
    if action in {"减仓", "卖出"}:
        if action == "减仓":
            target = min(grid_qty or quantity * 0.2, quantity * 0.5)
        else:
            target = min(grid_qty or quantity * 0.5, quantity)
        suggested = min(quantity, _round_lot(target))
        keep = max(0, quantity - suggested)
        if action == "卖出":
            return suggested, f"先卖出约 {suggested:g} 份；趋势未修复时可继续降仓，保留底仓 {min(keep, quantity * 0.2):g} 份以内"
        return suggested, f"先减约 {suggested:g} 份，剩余约 {keep:g} 份作为底仓继续观察"
    if action in {"买入", "分批买入", "分批加仓"}:
        base = grid_qty or quantity * 0.2
        cap = max(100, quantity * (0.5 if action == "分批加仓" else 0.3))
        suggested = min(_round_lot(base), _round_lot(cap))
        return suggested, f"参考加仓 {suggested:g} 份，分批执行，不一次打满"
    if action in {"暂停网格", "暂停买入侧"}:
        return 0, "暂停买入侧；已有持仓保留底仓，优先等趋势修复"
    return None, "维持当前仓位，按网格纪律执行"


def _round_lot(value: float) -> float:
    if value <= 0:
        return 0
    return max(100, round(value / 100) * 100)


def _num_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _note_signal(note: str | None) -> str:
    text = (note or "").lower()
    if any(word in text for word in ("看好", "长期", "低估", "配置", "加仓", "买入", "强")):
        return "positive"
    if any(word in text for word in ("谨慎", "不看好", "风险", "高估", "减仓", "卖出", "弱")):
        return "negative"
    return "neutral"


def _overlap_note(position: Position | None, positions: list[Position]) -> str | None:
    if not position:
        return None
    theme = _theme_key(position.name)
    if not theme:
        return None
    peers = [item for item in positions if item.code != position.code and _theme_key(item.name) == theme]
    if not peers:
        return None
    names = "、".join(f"{item.code} {item.name}" for item in peers[:3])
    return f"可能与同主题 ETF 持仓重合较高：{names}；建议保留流动性/费率/跟踪误差更优的一只，另一只逐步降权或只保留观察仓"


def _theme_key(name: str) -> str | None:
    rules = {
        "软件": ("软件", "云计算", "信创"),
        "半导体": ("半导体", "芯片", "集成电路"),
        "新能源": ("新能源", "电池", "储能", "光伏"),
        "有色金属": ("有色", "稀有金属", "工业金属"),
        "科创创业": ("科创创业", "双创"),
        "港股医药": ("港股创新药", "创新药", "医药"),
    }
    for key, words in rules.items():
        if any(word in name for word in words):
            return key
    return None
