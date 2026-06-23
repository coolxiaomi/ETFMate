from __future__ import annotations

from typing import Any

from etfmate.storage.models import GridConfig, MarketSnapshot, Position

ACTION_NAMES = {
    "NO_ACTION": "不操作",
    "WATCH": "观察",
    "OPEN": "建仓",
    "LIGHT_OPEN": "轻仓建仓",
    "HOLD": "持有",
    "ADD": "加仓",
    "HOLD_OR_ADD": "持有观察",
    "HOLD_OR_REDUCE": "持有或小幅减仓",
    "REDUCE": "减仓",
    "RISK_REVIEW": "风控复核",
    "EXIT_SHORT_TERM": "退出短线仓位",
}


def decide_position(
    position: Position | None,
    grid: GridConfig | None,
    market: MarketSnapshot,
    all_positions: list[Position] | None = None,
    all_markets: list[MarketSnapshot] | None = None,
) -> dict[str, Any]:
    category = classify_etf(market.name or (position.name if position else ""))
    filters = _trade_filters(market, position, category)
    trend = _trend_score(market)
    momentum = _momentum_score(market, all_markets or [])
    risk = _risk_score(market)
    total = round(trend["score"] * 0.45 + momentum["score"] * 0.35 - risk["score"] * 0.20, 1)
    portfolio = _portfolio_state(position, all_positions or [], category)
    decision = _position_decision_from_short_trend(position, market, filters, trend, portfolio)
    return {
        "action": decision["action_name"],
        "position_action": decision["position_action"],
        "action_name": decision["action_name"],
        "category": category,
        "trend_score": trend["score"],
        "trend_level": trend["name"],
        "trend_code": trend["level"],
        "trend_tags": trend["tags"],
        "trend_scores": trend["scores"],
        "trend_indicators": trend["indicators"],
        "trend_data_sufficient": trend["data_sufficient"],
        "momentum_score": momentum["score"],
        "risk_score": risk["score"],
        "risk_level": decision["risk_level"],
        "total_score": total,
        "filter_status": filters["status"],
        "blocked_actions": filters["blocked_actions"],
        "current_position_ratio": round(decision["current_position_ratio"], 4),
        "target_position_ratio": round(decision["target_position_ratio"], 4),
        "new_position_ratio": round(decision["new_position_ratio"], 4),
        "adjust_ratio": round(decision["adjust_ratio"], 4),
        "current_position_pct": round(decision["current_position_ratio"] * 100, 2),
        "target_position_pct": round(decision["target_position_ratio"] * 100, 2),
        "new_position_pct": round(decision["new_position_ratio"] * 100, 2),
        "adjust_pct": round(decision["adjust_ratio"] * 100, 2),
        "high_risk": decision["high_risk"],
        "no_high_risk": decision["no_high_risk"],
        "portfolio": portfolio,
        "reasons": decision["reasons"][:6],
        "risks": decision["warnings"][:6],
        "evidence": {
            "trend": trend["evidence"],
            "momentum": momentum["evidence"],
            "risk": risk["evidence"],
            "filters": filters["reasons"],
        },
    }


def classify_etf(name: str) -> str:
    text = str(name or "")
    if any(word in text for word in ("货币", "现金", "短融")):
        return "货币ETF"
    if any(word in text for word in ("债", "国债", "政金债", "信用债", "可转债")):
        return "债券ETF"
    if any(word in text for word in ("黄金", "有色", "商品", "豆粕", "能源化工")):
        return "商品ETF"
    if any(word in text for word in ("纳指", "标普", "德国", "法国", "日经", "恒生", "港股", "中概", "QDII")):
        return "跨境ETF"
    if any(word in text for word in ("沪深300", "中证500", "中证1000", "创业板", "科创", "上证50", "A500", "红利")):
        return "宽基ETF"
    if any(word in text for word in ("证券", "银行", "保险", "医药", "半导体", "芯片", "新能源", "电池", "软件", "军工", "传媒", "消费", "地产", "煤炭", "钢铁")):
        return "行业主题ETF"
    return "主题ETF"


def _trade_filters(market: MarketSnapshot, position: Position | None, category: str) -> dict[str, Any]:
    reasons: list[str] = []
    blocked: set[str] = set()
    status = "可交易"
    if market.last_price <= 0:
        return {"status": "禁止交易", "blocked_actions": ["全部"], "reasons": ["无有效最新价"]}
    if (market.kline_days or 0) < 120:
        status = "限制交易"
        blocked.update({"买入", "加仓", "提高网格买入侧"})
        reasons.append("K线不足120日，趋势/回撤评分不完整")
    if market.pct_chg >= 9.5:
        status = "禁止追买"
        blocked.update({"买入", "加仓", "提高网格买入侧"})
        reasons.append("接近涨停，不追高买入")
    if market.pct_chg <= -9.5:
        status = "禁止接跌"
        blocked.update({"买入", "加仓", "提高网格买入侧"})
        reasons.append("接近跌停，不接下跌流动性风险")
    amount_avg20 = market.amount_avg20 or market.amount
    threshold = _liquidity_threshold(category)
    if amount_avg20 and amount_avg20 < threshold:
        status = "限制交易" if status == "可交易" else status
        blocked.update({"买入", "加仓", "提高网格买入侧"})
        reasons.append(f"20日成交额低于{threshold / 100000000:.1f}亿门槛，新增买入需降级")
    elif not amount_avg20:
        status = "限制交易" if status == "可交易" else status
        blocked.update({"买入", "加仓", "提高网格买入侧"})
        reasons.append("缺少成交额数据，新增买入需降级")
    return {"status": status, "blocked_actions": sorted(blocked), "reasons": reasons}


def _trend_score(market: MarketSnapshot) -> dict[str, Any]:
    close = _num_or_none(market.last_price)
    ma5 = _num_or_none(market.ma5)
    ma10 = _num_or_none(market.ma10)
    ma20 = _num_or_none(market.ma20)
    ma5_slope_3 = _num_or_none(market.ma5_slope_3)
    vol_ratio_1_5 = _num_or_none(market.vol_ratio_1_5)
    vol_ratio_5_20 = _num_or_none(market.vol_ratio_5_20)
    boll_position = _num_or_none(market.boll_position)
    bias5 = _num_or_none(market.bias5_ratio)
    rsi6 = _num_or_none(market.rsi6)
    atr14 = _num_or_none(market.atr14)
    atr_expansion_ratio = _num_or_none(market.atr_expansion_ratio)

    core_values = [close, ma5, ma10, ma20, ma5_slope_3, boll_position, bias5, rsi6, atr14, atr_expansion_ratio]
    data_sufficient = bool((market.kline_days or 0) >= 60 and all(value is not None for value in core_values))
    tags: list[str] = []

    ma_score = 0
    if None not in (close, ma5, ma10, ma20, ma5_slope_3):
        if close > ma5 and ma5 > ma10 and ma10 > ma20 and ma5_slope_3 > 0:
            ma_score = 30
        elif close > ma5 and ma5 > ma10 and ma5_slope_3 > 0:
            ma_score = 25
        elif close > ma5 and ma5_slope_3 > 0:
            ma_score = 18
        elif close > ma5:
            ma_score = 12
        elif close < ma5 and ma5 < ma10:
            ma_score = 0
        else:
            ma_score = 5

    vol_score = 0
    if vol_ratio_1_5 is not None and vol_ratio_5_20 is not None:
        if vol_ratio_1_5 >= 1.3 and vol_ratio_5_20 >= 1.0:
            vol_score = 15
        elif vol_ratio_1_5 >= 1.1:
            vol_score = 12
        elif vol_ratio_1_5 >= 0.9:
            vol_score = 8
        else:
            vol_score = 4

    boll_score = 0
    if boll_position is not None:
        boll_position = _clamp(boll_position, 0, 1)
        if 0.60 <= boll_position <= 0.90:
            boll_score = 20
        elif 0.90 < boll_position <= 1.00:
            boll_score = 15
        elif 0.50 <= boll_position < 0.60:
            boll_score = 12
        elif 0.35 <= boll_position < 0.50:
            boll_score = 6
        else:
            boll_score = 2

    bias_score = 0
    if bias5 is not None:
        if 0 < bias5 <= 0.025:
            bias_score = 10
        elif 0.025 < bias5 <= 0.04:
            bias_score = 8
        elif 0.04 < bias5 <= 0.06:
            bias_score = 5
        elif bias5 > 0.06:
            bias_score = 2
        elif -0.02 <= bias5 <= 0:
            bias_score = 5
        else:
            bias_score = 2

    rsi_score = 0
    if rsi6 is not None:
        if 50 < rsi6 <= 75:
            rsi_score = 15
        elif 75 < rsi6 <= 85:
            rsi_score = 10
        elif rsi6 > 85:
            rsi_score = 5
        elif 40 <= rsi6 <= 50:
            rsi_score = 8
        else:
            rsi_score = 2

    atr_risk_deduct = 0
    if atr_expansion_ratio is not None:
        if atr_expansion_ratio >= 1.8:
            atr_risk_deduct = 10
        elif atr_expansion_ratio >= 1.5:
            atr_risk_deduct = 7
        elif atr_expansion_ratio >= 1.2:
            atr_risk_deduct = 3

    score = round(_clamp(ma_score + vol_score + boll_score + bias_score + rsi_score - atr_risk_deduct, 0, 100), 2)
    level, name = _short_trend_level(score, atr_risk_deduct)

    if rsi6 is not None and rsi6 > 85:
        tags.append("RSI短线过热")
    if bias5 is not None and bias5 > 0.06:
        tags.append("BIAS严重偏离MA5")
    if boll_position is not None and boll_position > 0.95:
        tags.append("接近或突破布林上轨")
    if atr_expansion_ratio is not None and atr_expansion_ratio >= 1.5:
        tags.append("ATR波动放大")
    if vol_ratio_1_5 is not None and bias5 is not None and vol_ratio_1_5 >= 1.5 and bias5 > 0.04:
        tags.append("放量急涨")
    if close is not None and ma5 is not None and close < ma5:
        tags.append("跌破MA5")
    if None not in (close, ma5, ma10, ma20) and close > ma5 and ma5 > ma10 and ma10 > ma20:
        tags.append("短线均线多头")
    if vol_ratio_1_5 is not None and vol_ratio_1_5 < 0.9:
        tags.append("短线量能不足")
    if boll_position is not None and boll_position < 0.35:
        tags.append("布林弱势区")
    if not data_sufficient:
        tags.append("数据不足")

    scores = {
        "ma_score": ma_score,
        "vol_score": vol_score,
        "boll_score": boll_score,
        "bias_score": bias_score,
        "rsi_score": rsi_score,
        "atr_risk_deduct": atr_risk_deduct,
    }
    indicators = {
        "ma5_slope_3": ma5_slope_3,
        "vol_ratio_1_5": vol_ratio_1_5,
        "vol_ratio_5_20": vol_ratio_5_20,
        "boll_position": boll_position,
        "bias5": bias5,
        "rsi6": rsi6,
        "atr_expansion_ratio": atr_expansion_ratio,
    }
    evidence = [
        f"短线趋势{name} {score:.0f}",
        "分项 "
        + "/".join(
            [
                f"MA{ma_score}",
                f"VOL{vol_score}",
                f"BOLL{boll_score}",
                f"BIAS{bias_score}",
                f"RSI{rsi_score}",
                f"ATR-{atr_risk_deduct}",
            ]
        ),
    ]
    if tags:
        evidence.append("标签 " + "、".join(tags[:4]))
    return {
        "score": score,
        "level": level,
        "name": name,
        "data_sufficient": data_sufficient,
        "scores": scores,
        "indicators": indicators,
        "tags": tags,
        "evidence": evidence,
    }


def _momentum_score(market: MarketSnapshot, all_markets: list[MarketSnapshot]) -> dict[str, Any]:
    score = 0
    evidence: list[str] = []
    if market.ret20 is not None and market.ret20 > 0:
        score += 20
        evidence.append(f"RET20 {market.ret20:+.2f}%")
    if market.ret60 is not None and market.ret60 > 0:
        score += 20
        evidence.append(f"RET60 {market.ret60:+.2f}%")
    if _top_percentile(market, all_markets, "ret20", 0.30):
        score += 25
        evidence.append("RET20处于本次持仓池前30%")
    if _top_percentile(market, all_markets, "ret60", 0.30):
        score += 25
        evidence.append("RET60处于本次持仓池前30%")
    amount_ratio = market.amount_ratio20 or market.vol_ratio
    if not (market.pct_chg < -2 and amount_ratio and amount_ratio > 1.5):
        score += 10
        evidence.append("未出现放量大跌")
    return {"score": min(100, score), "evidence": evidence or ["动量数据不足"]}


def _risk_score(market: MarketSnapshot) -> dict[str, Any]:
    score = 0
    evidence: list[str] = []
    if market.rsi14 is not None and market.rsi14 > 80:
        score += 20
        evidence.append(f"RSI14 {market.rsi14:.1f}，短线过热")
    if market.ma20 and abs(market.last_price / market.ma20 - 1) > 0.08:
        score += 20
        evidence.append("现价偏离MA20超过8%")
    if market.max_drawdown_60 is not None and market.max_drawdown_60 <= -15:
        score += 20
        evidence.append(f"60日回撤 {market.max_drawdown_60:.2f}%")
    if market.atr14_pct is not None and market.atr14_pct > 3:
        score += 20
        evidence.append(f"ATR14/价格 {market.atr14_pct:.2f}%")
    if market.ret3 is not None and market.ret3 <= -5:
        score += 20
        evidence.append(f"近3日跌幅 {market.ret3:.2f}%")
    return {"score": min(100, score), "evidence": evidence or ["未触发主要风险项"]}


def _position_decision_from_short_trend(
    position: Position | None,
    market: MarketSnapshot,
    filters: dict[str, Any],
    trend: dict[str, Any],
    portfolio: dict[str, Any],
) -> dict[str, Any]:
    score = _num_or_none(trend.get("score")) or 0.0
    current_ratio = _current_position_ratio(position, portfolio)
    holding = current_ratio > 0
    no_high_risk = _no_high_risk(trend)
    high_risk = _has_high_risk(trend)
    risk_level = _position_risk_level(score, trend)
    target_ratio = 0.0
    new_ratio = current_ratio
    adjust_ratio = 0.0
    action = "WATCH"
    reasons = [
        f"趋势评分 {score:.0f}，当前仓位 {current_ratio:.2%}",
    ]
    warnings = list(filters["reasons"])
    blocked = set(filters["blocked_actions"])
    if filters["status"] == "禁止交易":
        return _build_position_decision(
            current_ratio,
            target_ratio,
            new_ratio,
            adjust_ratio,
            "NO_ACTION",
            risk_level,
            high_risk,
            no_high_risk,
            reasons + ["触发硬过滤，本次不生成可执行交易动作"],
            warnings,
            action_name="禁止交易",
        )

    if not holding:
        if score >= 85 and no_high_risk:
            action = "OPEN"
            target_ratio = 0.30
            reasons.append("未持仓且短线趋势评分不低于85、无高风险标签，进入初始建仓区")
        elif score >= 75 and no_high_risk:
            action = "LIGHT_OPEN"
            target_ratio = 0.20
            reasons.append("未持仓且短线趋势评分不低于75、无高风险标签，可轻仓建仓观察")
        else:
            action = "WATCH"
            target_ratio = 0.00
            reasons.append("未持仓且短线趋势强度或风险状态不足，继续观察")
        adjust_ratio = target_ratio
        new_ratio = target_ratio
    else:
        base_target = _base_target_position(score, no_high_risk)
        target_ratio = _downgrade_target_position(base_target) if high_risk else base_target
        gap = target_ratio - current_ratio
        serious_risk = _is_serious_short_risk(score, market)
        reasons.append(f"基础目标仓位 {base_target:.0%}，风险调整后目标仓位 {target_ratio:.0%}")

        if serious_risk:
            action = "EXIT_SHORT_TERM" if (_num_or_none(market.atr_expansion_ratio) or 0) >= 1.5 else "RISK_REVIEW"
            reasons.append("短线评分低于45且价格跌破MA5、MA5低于MA10，触发风控复核")
        elif abs(gap) < 0.05:
            action = "HOLD"
            reasons.append("目标仓位与当前仓位差小于5%，不做频繁微调")
        elif gap > 0:
            action = "ADD"
            reasons.append("目标仓位高于当前仓位，可按阶梯方式加仓")
        else:
            action = "REDUCE"
            reasons.append("目标仓位低于当前仓位，建议降低部分仓位")

        if action == "ADD":
            if not _can_add_by_trend(market, trend):
                action = "HOLD_OR_ADD"
                adjust_ratio = 0.0
                new_ratio = current_ratio
                reasons = [reason for reason in reasons if "可按阶梯方式加仓" not in reason]
                warnings.append("加仓条件未完全满足，需继续观察 MA5/MA10、ATR 和 BIAS 后再执行")
            else:
                adjust_ratio = min(max(gap, 0.0), 0.20)
                new_ratio = min(current_ratio + adjust_ratio, target_ratio)
        elif action in {"REDUCE", "RISK_REVIEW", "EXIT_SHORT_TERM"}:
            max_reduce_step = 0.50 if serious_risk and (_num_or_none(market.atr_expansion_ratio) or 0) >= 1.5 else 0.30
            reduce_gap = max(0.0, current_ratio - target_ratio)
            adjust_ratio = min(reduce_gap, max_reduce_step)
            new_ratio = max(current_ratio - adjust_ratio, target_ratio, 0.0)
        else:
            adjust_ratio = 0.0
            new_ratio = current_ratio

    action, target_ratio, new_ratio, adjust_ratio = _apply_filter_constraints(
        action, target_ratio, new_ratio, adjust_ratio, current_ratio, holding, blocked, warnings
    )
    reasons.extend(_action_copy(action, high_risk, score))
    return _build_position_decision(
        current_ratio,
        target_ratio,
        new_ratio,
        adjust_ratio,
        action,
        risk_level,
        high_risk,
        no_high_risk,
        reasons,
        warnings or ["该建议仅为趋势评分结果，不构成交易指令"],
    )


def _build_position_decision(
    current_ratio: float,
    target_ratio: float,
    new_ratio: float,
    adjust_ratio: float,
    action: str,
    risk_level: str,
    high_risk: bool,
    no_high_risk: bool,
    reasons: list[str],
    warnings: list[str],
    action_name: str | None = None,
) -> dict[str, Any]:
    return {
        "current_position_ratio": current_ratio,
        "target_position_ratio": target_ratio,
        "new_position_ratio": new_ratio,
        "adjust_ratio": adjust_ratio,
        "position_action": action,
        "action_name": action_name or ACTION_NAMES[action],
        "risk_level": risk_level,
        "high_risk": high_risk,
        "no_high_risk": no_high_risk,
        "reasons": list(dict.fromkeys(reasons)),
        "warnings": list(dict.fromkeys(warnings)),
    }


def _current_position_ratio(position: Position | None, portfolio: dict[str, Any]) -> float:
    if not position or position.quantity <= 0 or position.market_value <= 0:
        return 0.0
    pct = _num_or_none(position.position_pct)
    if pct is None or pct <= 0:
        pct = _num_or_none(portfolio.get("position_pct")) or 0.0
    return _clamp(pct / 100.0, 0.0, 1.0)


def _base_target_position(score: float, no_high_risk: bool) -> float:
    if score >= 85 and no_high_risk:
        return 0.60
    if score >= 75 and no_high_risk:
        return 0.40
    if score >= 60:
        return 0.25
    if score >= 45:
        return 0.10
    return 0.00


def _downgrade_target_position(base_target: float) -> float:
    if base_target >= 0.60:
        return 0.40
    if base_target >= 0.40:
        return 0.25
    if base_target >= 0.25:
        return 0.10
    if base_target >= 0.10:
        return 0.00
    return 0.00


def _has_high_risk(trend: dict[str, Any]) -> bool:
    tags = set(trend.get("tags") or [])
    high_risk_tags = {"RSI短线过热", "BIAS严重偏离MA5", "ATR波动放大", "放量急涨", "接近或突破布林上轨"}
    return bool(tags & high_risk_tags)


def _no_high_risk(trend: dict[str, Any]) -> bool:
    tags = set(trend.get("tags") or [])
    scores = trend.get("scores") or {}
    indicators = trend.get("indicators") or {}
    atr_deduct = _num_or_none(scores.get("atr_risk_deduct")) or 0
    rsi6 = _num_or_none(indicators.get("rsi6"))
    bias5 = _num_or_none(indicators.get("bias5"))
    return (
        atr_deduct == 0
        and (rsi6 is None or rsi6 <= 85)
        and (bias5 is None or bias5 <= 0.06)
        and "放量急涨" not in tags
        and "ATR波动放大" not in tags
    )


def _is_serious_short_risk(score: float, market: MarketSnapshot) -> bool:
    close = _num_or_none(market.last_price)
    ma5 = _num_or_none(market.ma5)
    ma10 = _num_or_none(market.ma10)
    return bool(score < 45 and close is not None and ma5 is not None and ma10 is not None and close < ma5 < ma10)


def _can_add_by_trend(market: MarketSnapshot, trend: dict[str, Any]) -> bool:
    score = _num_or_none(trend.get("score")) or 0.0
    close = _num_or_none(market.last_price)
    ma5 = _num_or_none(market.ma5)
    ma10 = _num_or_none(market.ma10)
    tags = set(trend.get("tags") or [])
    return bool(
        score >= 75
        and close is not None
        and ma5 is not None
        and ma10 is not None
        and close > ma5 > ma10
        and "ATR波动放大" not in tags
        and "BIAS严重偏离MA5" not in tags
    )


def _position_risk_level(score: float, trend: dict[str, Any]) -> str:
    tags = set(trend.get("tags") or [])
    if {"ATR波动放大", "BIAS严重偏离MA5"} & tags or score < 45:
        return "HIGH"
    if {"RSI短线过热", "接近或突破布林上轨"} & tags or score < 60:
        return "MEDIUM"
    return "LOW"


def _apply_filter_constraints(
    action: str,
    target_ratio: float,
    new_ratio: float,
    adjust_ratio: float,
    current_ratio: float,
    holding: bool,
    blocked: set[str],
    warnings: list[str],
) -> tuple[str, float, float, float]:
    buy_actions = {"OPEN", "LIGHT_OPEN", "ADD", "HOLD_OR_ADD"}
    if action in buy_actions and {"买入", "加仓", "提高网格买入侧"} & blocked:
        warnings.append("交易过滤限制新增买入，仓位动作降级为观察/持有")
        return ("HOLD" if holding else "WATCH"), current_ratio, current_ratio, 0.0
    return action, target_ratio, new_ratio, adjust_ratio


def _action_copy(action: str, high_risk: bool, score: float) -> list[str]:
    if action == "OPEN":
        return ["短线趋势较强且无明显过热或波动放大，可进入建仓观察区；首笔不建议一次性重仓"]
    if action == "LIGHT_OPEN":
        return ["短线趋势偏强，可轻仓建仓观察，后续继续看 MA5、量能和 ATR 稳定性"]
    if action == "WATCH":
        if high_risk and score >= 75:
            return ["趋势评分较高但存在短线过热或波动放大，不适合直接追高"]
        return ["短线趋势强度不足或交易过滤受限，暂不进入建仓区"]
    if action == "HOLD":
        return ["当前仓位与目标仓位基本匹配，继续持有观察"]
    if action == "ADD":
        return ["短线趋势评分较高且目标仓位高于当前仓位，可按单次上限分步加仓"]
    if action == "HOLD_OR_ADD":
        return ["目标仓位高于当前仓位，但加仓确认条件不足，先持有观察"]
    if action == "REDUCE":
        return ["目标仓位低于当前仓位，建议降低部分仓位"]
    if action == "RISK_REVIEW":
        return ["短线趋势明显转弱，触发持仓风控复核"]
    if action == "EXIT_SHORT_TERM":
        return ["短线趋势转弱且波动风险放大，建议退出短线进攻仓位或降至观察仓位"]
    return []


def _portfolio_state(position: Position | None, positions: list[Position], category: str) -> dict[str, Any]:
    total_value = sum(item.market_value for item in positions if item.market_value > 0)
    position_pct = position.position_pct if position and position.position_pct is not None else 0
    if not position_pct and position and total_value:
        position_pct = position.market_value / total_value * 100
    category_value = sum(item.market_value for item in positions if classify_etf(item.name) == category)
    return {
        "category": category,
        "position_pct": position_pct or 0,
        "category_pct": category_value / total_value * 100 if total_value else 0,
    }


def _liquidity_threshold(category: str) -> float:
    if category == "宽基ETF":
        return 200_000_000
    if category == "行业主题ETF":
        return 80_000_000
    if category in {"债券ETF", "货币ETF"}:
        return 30_000_000
    return 50_000_000


def _short_trend_level(score: float, atr_risk_deduct: int) -> tuple[str, str]:
    if score >= 85 and atr_risk_deduct == 0:
        return "STRONG_ATTACK", "强势进攻区"
    if score >= 75:
        return "UPTREND", "短线上升趋势"
    if score >= 60:
        return "WEAK_UPTREND", "震荡偏强"
    if score >= 45:
        return "SIDEWAYS", "震荡观察"
    return "WEAK", "短线转弱"


def _num_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _top_percentile(market: MarketSnapshot, all_markets: list[MarketSnapshot], field: str, pct: float) -> bool:
    values = sorted(
        [(getattr(item, field), item.code) for item in all_markets if getattr(item, field, None) is not None],
        reverse=True,
    )
    if len(values) < 3:
        return False
    cutoff = max(1, round(len(values) * pct))
    return market.code in {code for _, code in values[:cutoff]}
