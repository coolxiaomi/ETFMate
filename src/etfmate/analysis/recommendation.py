from __future__ import annotations

from typing import Any

from etfmate.analysis.layered_context import LayeredContext, normalize_context
from etfmate.analysis.rule_engine import decide_position
from etfmate.storage.models import GridConfig, MarketSnapshot, Position, WatchItem


def recommend(
    position: Position | None,
    grid: GridConfig | None,
    market: MarketSnapshot,
    all_positions: list[Position] | None = None,
    all_markets: list[MarketSnapshot] | None = None,
    layered_context: LayeredContext | dict[str, Any] | None = None,
    watch_item: WatchItem | None = None,
) -> dict:
    scores: list[str] = []

    boll_pos = _boll_position(market)
    holding_weight = position.market_value if position else 0
    portfolio_value = sum(item.market_value for item in (all_positions or []) if item.market_value > 0)
    position_weight_pct = position.position_pct if position and position.position_pct is not None else 0
    position_tier = _position_tier(position_weight_pct)
    rule_decision = decide_position(position, grid, market, all_positions or [], all_markets or [])
    action = str(rule_decision.get("action") or "观察")
    reasons: list[str] = list(rule_decision.get("reasons") or [])
    risks: list[str] = list(rule_decision.get("risks") or [])
    source = _candidate_source(position, grid, watch_item)

    if boll_pos is not None:
        scores.append(f"BOLL分位 {boll_pos:.0%}")
    if market.atr14_pct:
        scores.append(f"ATR14 {market.atr14_pct:.2f}%")
    if market.bias6 is not None:
        scores.append(f"BIAS6 {market.bias6:.2f}%")
    if market.macd_dif is not None and market.macd_dea is not None:
        scores.append(f"MACD DIF {market.macd_dif:.3f}/DEA {market.macd_dea:.3f}")
    if market.vol_ma5 and market.vol_ma20:
        scores.append(f"VOL5/20 {market.vol_ma5 / market.vol_ma20:.2f}倍")

    if not position and watch_item:
        reasons.append("来自同花顺自选 ETF 池，按短线趋势评分进入建仓/等待观察队列")
    if position:
        note_signal = _note_signal(position.note)
        above_ma20 = bool(market.ma20 and market.last_price >= market.ma20)
        above_ma60 = bool(market.ma60 and market.last_price >= market.ma60)
        vol_shrinking = bool(market.vol_ma5 and market.vol_ma20 and market.vol_ma5 < market.vol_ma20 * 0.75)
        if note_signal == "positive" and above_ma20 and above_ma60 and not vol_shrinking:
            reasons.append("你的备注偏看好，且趋势/量能暂未冲突，可作为持仓依据之一")
        elif note_signal == "positive" and (not above_ma60 or vol_shrinking):
            risks.append("你的备注偏看好，但市场趋势或量能没有确认，需降低动作强度")
        elif note_signal == "negative" and (not above_ma20 or not above_ma60):
            reasons.append("你的备注偏谨慎，且市场信号偏弱，与保守动作方向一致")
        elif note_signal == "negative" and above_ma20 and above_ma60:
            risks.append("你的备注偏谨慎，但市场趋势偏强，减仓前需避免过早离场")

    overlap_note = _overlap_note(position, all_positions or [])
    if overlap_note:
        risks.append(overlap_note)

    if market.data_quality != "ok":
        risks.append(f"行情数据完整性: {market.data_quality}")
    if position and position.position_pct_source == "positions_market_value_fallback":
        risks.append("资金仓位缺少账户总资产，当前按持仓市值合计估算；组合仓位上限需谨慎解读")
    elif position and position.position_pct_source == "missing":
        risks.append("缺少资金仓位口径，仓位约束只能降级为保守判断")

    layer_payload = normalize_context(layered_context)
    if layer_payload:
        confidence = _num_or_zero(layer_payload.get("confidence"))
        total_score = _num_or_zero(layer_payload.get("total_score"))
        if confidence < 45:
            risks.append("七层证据未完整接入，仅作复核提示，不单独压低强趋势动作")
        if total_score <= -2 and action in {"建仓", "轻仓建仓", "加仓", "持有或加仓", "持有待加仓确认", "持有观察"}:
            action = "观察" if not position else "持有"
            risks.append("多层证据偏弱，暂不把短线趋势信号直接解释为加仓信号")
        elif total_score >= 2 and action in {"减仓", "退出短线仓位"} and position and position.pnl_pct < 0:
            risks.append("多层证据未明显转弱，亏损仓位不宜一次性大幅减仓")

    if action != rule_decision.get("action"):
        rule_decision = {
            **rule_decision,
            "raw_action": rule_decision.get("action"),
            "action": action,
            "action_name": action,
        }
    action_quantity, position_plan = _action_plan(action, position, grid, rule_decision)
    reasons = _clean_reasons_for_action(action, list(dict.fromkeys(reasons)))
    risks = list(dict.fromkeys(risks))
    return {
        "code": market.code,
        "name": market.name,
        "candidate_source": source,
        "is_watchlist_candidate": bool(watch_item),
        "watchlist_source_key": watch_item.source_key if watch_item else None,
        "watchlist_include_reason": watch_item.include_reason if watch_item else None,
        "quantity": position.quantity if position else None,
        "market_value": position.market_value if position else None,
        "position_pct": position.position_pct if position else None,
        "holding_pct": position.holding_pct if position else None,
        "position_pct_source": position.position_pct_source if position else None,
        "account_total_asset": position.account_total_asset if position else None,
        "position_tier": position_tier,
        "investor_note": position.note if position else None,
        "cost_price": position.cost_price if position else None,
        "last_price": market.last_price,
        "pct_chg": market.pct_chg,
        "pnl_pct": position.pnl_pct if position else None,
        "boll_position_pct": round(boll_pos * 100, 1) if boll_pos is not None else None,
        "boll_position": market.boll_position,
        "boll_lower": market.boll_lower,
        "boll_mid": market.boll_mid,
        "boll_upper": market.boll_upper,
        "ma_status": _ma_status(market),
        "ma5": market.ma5,
        "ma5_slope_3": market.ma5_slope_3,
        "ma10": market.ma10,
        "ma20": market.ma20,
        "ma60": market.ma60,
        "ma120": market.ma120,
        "ma200": market.ma200,
        "atr7_pct": market.atr7_pct,
        "atr14_pct": market.atr14_pct,
        "atr30_pct": market.atr30_pct,
        "atr60_pct": market.atr60_pct,
        "atr20_avg": market.atr20_avg,
        "atr_expansion_ratio": market.atr_expansion_ratio,
        "bias5_ratio": market.bias5_ratio,
        "bias6": market.bias6,
        "bias12": market.bias12,
        "bias24": market.bias24,
        "volume": market.volume,
        "vol_ma5": market.vol_ma5,
        "vol_ma20": market.vol_ma20,
        "vol_ratio_1_5": market.vol_ratio_1_5,
        "vol_ratio_5_20": market.vol_ratio_5_20,
        "amount_avg20": market.amount_avg20,
        "amount_ratio20": market.amount_ratio20,
        "rsi6": market.rsi6,
        "rsi14": market.rsi14,
        "macd_dif": market.macd_dif,
        "macd_dea": market.macd_dea,
        "macd_hist": market.macd_hist,
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
        "entry_plan": _entry_plan(market, action, rule_decision, bool(watch_item) and not position),
        "reasons": reasons,
        "risks": risks or ["暂无明显新增风险"],
        "watch_price": _watch_price(market),
        "indicators": "；".join(scores) if scores else "指标不足",
        "layered_context": layer_payload,
        "layered_confidence": layer_payload.get("confidence") if layer_payload else None,
        "layered_score": layer_payload.get("total_score") if layer_payload else None,
        "rule_decision": rule_decision,
        "rule_trend_score": rule_decision.get("trend_score"),
        "rule_filter_status": rule_decision.get("filter_status"),
        "target_position_pct": rule_decision.get("target_position_pct"),
        "current_position_ratio": rule_decision.get("current_position_ratio"),
        "target_position_ratio": rule_decision.get("target_position_ratio"),
        "new_position_ratio": rule_decision.get("new_position_ratio"),
        "adjust_ratio": rule_decision.get("adjust_ratio"),
        "current_position_pct": rule_decision.get("current_position_pct"),
        "new_position_pct": rule_decision.get("new_position_pct"),
        "adjust_pct": rule_decision.get("adjust_pct"),
        "position_action": rule_decision.get("position_action"),
        "position_risk_level": rule_decision.get("risk_level"),
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


def _candidate_source(position: Position | None, grid: GridConfig | None, watch_item: WatchItem | None) -> str:
    if position and watch_item:
        return "持仓+自选ETF池"
    if position:
        return "同花顺持仓"
    if watch_item and grid:
        return "自选ETF池+Touker网格"
    if watch_item:
        return "自选ETF池"
    if grid:
        return "Touker网格"
    return "行情池"


def _action_plan(action: str, position: Position | None, grid: GridConfig | None, rule_decision: dict[str, Any] | None = None) -> tuple[float | None, str]:
    quantity = position.quantity if position else None
    grid_qty = grid.order_quantity if grid else None
    target_pct = _num_or_zero((rule_decision or {}).get("target_position_pct"))
    new_pct = _num_or_zero((rule_decision or {}).get("new_position_pct"))
    adjust_pct = _num_or_zero((rule_decision or {}).get("adjust_pct"))
    if not position:
        if action in {"建仓", "轻仓建仓"}:
            target_text = f"，目标仓位约 {target_pct:.1f}%" if target_pct else ""
            qty = _round_lot(grid_qty or 100)
            return qty, f"无当前持仓{target_text}；首笔只做目标仓位的约1/3或单格小仓位，后续按趋势评分分批"
        if action in {"观察", "禁止交易"}:
            target_text = f"，规则目标仓位约 {target_pct:.1f}%" if target_pct else ""
            return None, f"无当前持仓{target_text}；当前暂不新开仓，等待入场条件"
        return None, "无当前持仓，先纳入观察池"
    if action == "禁止交易":
        return None, "触发硬过滤条件，本次不新增交易动作"
    if action == "观察":
        return None, "保留观察，不新增买入或卖出动作"
    if action in {"减仓", "退出短线仓位", "风控复核"}:
        if action == "风控复核":
            return None, f"触发风控复核；目标仓位约 {target_pct:.1f}%，先人工确认趋势状态"
        ratio_qty = quantity * min(max(adjust_pct, 0.0), 100.0) / max(_num_or_zero((rule_decision or {}).get("current_position_pct")), 0.01)
        fallback = quantity * (0.5 if action == "退出短线仓位" else 0.3)
        target = min(grid_qty or ratio_qty or fallback, quantity * (0.5 if action == "退出短线仓位" else 0.3))
        suggested = min(quantity, _round_lot(target))
        keep = max(0, quantity - suggested)
        if action == "退出短线仓位":
            return suggested, f"先退出短线进攻仓约 {suggested:g} 份；新仓位参考 {new_pct:.1f}%，趋势未修复前降至观察仓"
        return suggested, f"先减约 {suggested:g} 份，剩余约 {keep:g} 份作为底仓继续观察；新仓位参考 {new_pct:.1f}%"
    if action in {"加仓", "持有或加仓", "持有待加仓确认", "持有观察"}:
        if action in {"持有或加仓", "持有待加仓确认", "持有观察"}:
            return None, f"目标仓位约 {target_pct:.1f}%，但确认条件不足；先持有，等待回踩或量能/ATR确认"
        ratio_qty = quantity * min(max(adjust_pct, 0.0), 100.0) / max(_num_or_zero((rule_decision or {}).get("current_position_pct")), 0.01)
        base = grid_qty or ratio_qty or quantity * 0.2
        cap = max(100, quantity * 0.5)
        suggested = min(_round_lot(base), _round_lot(cap))
        return suggested, f"参考加仓 {suggested:g} 份，分批执行；目标仓位约 {target_pct:.1f}%，本次后参考 {new_pct:.1f}%"
    if action in {"暂停网格", "暂停买入侧"}:
        return None, "暂停新增买入；已有持仓保留底仓，优先等趋势修复"
    return None, "维持当前仓位，按网格纪律执行"


def _entry_plan(market: MarketSnapshot, action: str, rule_decision: dict[str, Any], watch_only: bool) -> str:
    target_pct = _num_or_zero(rule_decision.get("target_position_pct"))
    target_text = f"目标仓位 {target_pct:.1f}%" if target_pct else "目标仓位待规则确认"
    refs = []
    if market.ma20:
        refs.append(f"MA20 {market.ma20:.3f}")
    if market.boll_mid:
        refs.append(f"BOLL中轨 {market.boll_mid:.3f}")
    if market.boll_lower:
        refs.append(f"BOLL下轨 {market.boll_lower:.3f}")
    ref_text = "，参考 " + " / ".join(refs) if refs else "，等待补齐 K 线参考价"
    if action in {"建仓", "轻仓建仓", "加仓", "持有或加仓", "持有待加仓确认", "持有观察"}:
        prefix = "未持仓建仓" if watch_only else "加仓"
        if action in {"持有或加仓", "持有待加仓确认", "持有观察"}:
            prefix = "持有观察"
        return f"{prefix}: {target_text}，首笔不超过目标的1/3{ref_text}；不在明显远离 MA20 时追价"
    if action in {"观察", "持有"} and watch_only:
        return f"等待: {target_text}{ref_text}，等趋势修复或回踩确认后再建仓"
    if action in {"禁止交易"}:
        return "触发硬过滤，本次不设入场价"
    return f"{target_text}{ref_text}"


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
    return f"可能与同主题 ETF 持仓重合较高：{names}；仅作持仓重合提示，需结合成分、流动性、费率和跟踪误差人工筛选，不自动触发降仓"


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
