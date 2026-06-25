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
    "HOLD_WAIT_ADD": "持有待加仓确认",
    "HOLD_OR_REDUCE": "持有或小幅减仓",
    "REDUCE": "减仓",
    "TREND_REVIEW": "趋势复核",
    "EXIT_TREND_POSITION": "退出短线仓位",
    # Legacy aliases kept for old analysis.json / report re-render compatibility.
    "HOLD_OR_ADD": "持有观察",
    "RISK_REVIEW": "趋势复核",
    "EXIT_SHORT_TERM": "退出短线仓位",
}
MAX_TOTAL_POSITION_RATIO = 0.80
MAX_CATEGORY_POSITION_RATIO = 0.15
MAX_SINGLE_POSITION_RATIO = 0.30


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
        "risk_level": decision["risk_level"],
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
    bias12 = _num_or_none(market.bias12)
    bias24 = _num_or_none(market.bias24)
    rsi6 = _num_or_none(market.rsi6)
    rsi14 = _num_or_none(market.rsi14)

    core_values = [close, ma5, ma10, ma20, ma5_slope_3, vol_ratio_1_5, vol_ratio_5_20, boll_position, bias5, rsi6]
    data_sufficient = bool((market.kline_days or 0) >= 60 and all(value is not None for value in core_values))
    tags: list[str] = []

    ma_score = 0
    if None not in (close, ma5, ma10, ma20, ma5_slope_3):
        if close > ma5 and ma5 > ma10 and ma10 > ma20 and ma5_slope_3 > 0:
            ma_score = 35
        elif close > ma5 and ma5 > ma10 and ma5_slope_3 > 0:
            ma_score = 30
        elif close > ma5 and ma5_slope_3 > 0:
            ma_score = 22
        elif close > ma5:
            ma_score = 15
        elif close < ma5 and ma5 < ma10:
            ma_score = 0
        else:
            ma_score = 8

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
            rsi_score = 20
        elif 75 < rsi6 <= 85:
            rsi_score = 14
        elif rsi6 > 85:
            rsi_score = 8
        elif 40 <= rsi6 <= 50:
            rsi_score = 10
        else:
            rsi_score = 3

    score = round(_clamp(ma_score + boll_score + vol_score + rsi_score + bias_score, 0, 100), 2)
    level, name = _short_trend_level(score)

    if rsi6 is not None and rsi6 > 85:
        tags.append("RSI短线过热")
    elif rsi6 is not None and rsi6 >= 70:
        tags.append("RSI短线偏热")
    if bias5 is not None and bias5 > 0.06:
        tags.append("BIAS严重偏离MA5")
    if bias12 is not None and bias12 >= 6:
        tags.append("BIAS12明显正乖离")
    if bias24 is not None and bias24 >= 10:
        tags.append("BIAS24严重正乖离")
    if boll_position is not None and boll_position >= 0.90:
        tags.append("接近或突破布林上轨")
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
        "short_trend_score": score,
    }
    indicators = {
        "ma5_slope_3": ma5_slope_3,
        "vol_ratio_1_5": vol_ratio_1_5,
        "vol_ratio_5_20": vol_ratio_5_20,
        "boll_position": boll_position,
        "bias5": bias5,
        "bias12": bias12,
        "bias24": bias24,
        "rsi6": rsi6,
        "rsi14": rsi14,
    }
    evidence = [
        f"短线趋势{name} {score:.0f}",
        "分项 "
        + "/".join(
            [
                f"MA{ma_score}",
                f"BOLL{boll_score}",
                f"VOL{vol_score}",
                f"RSI{rsi_score}",
                f"BIAS{bias_score}",
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


def _position_decision_from_short_trend(
    position: Position | None,
    market: MarketSnapshot,
    filters: dict[str, Any],
    trend: dict[str, Any],
    portfolio: dict[str, Any],
) -> dict[str, Any]:
    score = _num_or_none(trend.get("score")) or 0.0
    current_ratio = _current_position_ratio(position, portfolio)
    holding = bool(position and position.quantity > 0 and position.market_value > 0)
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
    if portfolio.get("position_pct_confidence") == "low":
        warnings.append("资金仓位缺少账户总资产口径，持仓内部占比仅作集中度参考；新增买入默认降级")
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
        if score >= 85 and no_high_risk and not _portfolio_blocks_add(portfolio):
            action = "OPEN"
            target_ratio = _apply_portfolio_caps(0.15, current_ratio, portfolio, warnings)
            reasons.append("未持仓且短线趋势评分不低于85、无高风险标签，进入初始建仓区")
        elif score >= 75 and no_high_risk and not _portfolio_blocks_add(portfolio):
            action = "LIGHT_OPEN"
            target_ratio = _apply_portfolio_caps(0.10, current_ratio, portfolio, warnings)
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
        target_ratio = _apply_portfolio_caps(target_ratio, current_ratio, portfolio, warnings)
        gap = target_ratio - current_ratio
        serious_risk = _is_serious_short_risk(score, market)
        reasons.append(f"基础目标仓位 {base_target:.0%}，风险调整后目标仓位 {target_ratio:.0%}")

        if serious_risk:
            action = "EXIT_TREND_POSITION"
            reasons.append("短线评分低于45且价格跌破MA5、MA5低于MA10，触发退出短线仓位")
        elif target_ratio <= 0 and current_ratio > 0:
            action = "REDUCE"
            reasons.append("目标仓位为 0 且仍有持仓，主动作必须明确为减仓/退出观察，趋势复核只作为辅助提示")
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
                action = "HOLD_WAIT_ADD"
                adjust_ratio = 0.0
                new_ratio = current_ratio
                reasons = [reason for reason in reasons if "可按阶梯方式加仓" not in reason]
                warnings.append("加仓条件未完全满足，需继续观察 MA5/MA10、ATR 和 BIAS 后再执行")
            else:
                adjust_ratio = min(max(gap, 0.0), 0.20)
                new_ratio = min(current_ratio + adjust_ratio, target_ratio)
        elif action in {"REDUCE", "TREND_REVIEW", "EXIT_TREND_POSITION"}:
            max_reduce_step = 0.50 if serious_risk else 0.30
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
        return 0.30
    if score >= 75 and no_high_risk:
        return 0.20
    if score >= 60:
        return 0.10
    if score >= 45:
        return 0.05
    return 0.00


def _downgrade_target_position(base_target: float) -> float:
    if base_target >= 0.30:
        return 0.20
    if base_target >= 0.20:
        return 0.10
    if base_target >= 0.10:
        return 0.05
    if base_target >= 0.05:
        return 0.00
    return 0.00


def _apply_portfolio_caps(target_ratio: float, current_ratio: float, portfolio: dict[str, Any], warnings: list[str]) -> float:
    capped = min(target_ratio, MAX_SINGLE_POSITION_RATIO)
    if target_ratio > capped:
        warnings.append("单只 ETF 目标仓位按 30% 上限压缩")
    if portfolio.get("position_pct_confidence") == "low":
        if capped > current_ratio:
            warnings.append("资金仓位口径置信度低，新增买入目标先按 4% 以内试探")
            capped = max(current_ratio, min(capped, 0.04))
        return capped
    total_ratio = (_num_or_none(portfolio.get("total_position_pct")) or 0.0) / 100.0
    category_ratio = (_num_or_none(portfolio.get("category_pct")) or 0.0) / 100.0
    if total_ratio >= MAX_TOTAL_POSITION_RATIO and capped > current_ratio:
        warnings.append("组合总仓位已达到 80% 上限，必须至少保留 20% 现金，禁止新增加仓")
        capped = current_ratio
    if category_ratio >= MAX_CATEGORY_POSITION_RATIO and capped > current_ratio:
        warnings.append("同类 ETF 仓位已达到 15% 上限，禁止继续提高该方向仓位")
        capped = current_ratio
    return capped


def _portfolio_blocks_add(portfolio: dict[str, Any]) -> bool:
    if portfolio.get("position_pct_confidence") == "low":
        return False
    total_ratio = (_num_or_none(portfolio.get("total_position_pct")) or 0.0) / 100.0
    category_ratio = (_num_or_none(portfolio.get("category_pct")) or 0.0) / 100.0
    return total_ratio >= MAX_TOTAL_POSITION_RATIO or category_ratio >= MAX_CATEGORY_POSITION_RATIO


def _has_high_risk(trend: dict[str, Any]) -> bool:
    tags = set(trend.get("tags") or [])
    high_risk_tags = {
        "RSI短线过热",
        "RSI短线偏热",
        "BIAS严重偏离MA5",
        "BIAS12明显正乖离",
        "BIAS24严重正乖离",
        "放量急涨",
        "接近或突破布林上轨",
    }
    return bool(tags & high_risk_tags)


def _no_high_risk(trend: dict[str, Any]) -> bool:
    tags = set(trend.get("tags") or [])
    indicators = trend.get("indicators") or {}
    rsi6 = _num_or_none(indicators.get("rsi6"))
    bias5 = _num_or_none(indicators.get("bias5"))
    bias12 = _num_or_none(indicators.get("bias12"))
    bias24 = _num_or_none(indicators.get("bias24"))
    boll_position = _num_or_none(indicators.get("boll_position"))
    return (
        (rsi6 is None or rsi6 < 70)
        and (bias5 is None or bias5 <= 0.06)
        and (bias12 is None or bias12 < 6)
        and (bias24 is None or bias24 < 10)
        and (boll_position is None or boll_position < 0.90)
        and "RSI短线过热" not in tags
        and "RSI短线偏热" not in tags
        and "BIAS严重偏离MA5" not in tags
        and "BIAS12明显正乖离" not in tags
        and "BIAS24严重正乖离" not in tags
        and "接近或突破布林上轨" not in tags
        and "放量急涨" not in tags
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
        and "放量急涨" not in tags
        and "RSI短线过热" not in tags
        and "RSI短线偏热" not in tags
        and "BIAS严重偏离MA5" not in tags
        and "BIAS12明显正乖离" not in tags
        and "BIAS24严重正乖离" not in tags
        and "接近或突破布林上轨" not in tags
    )


def _position_risk_level(score: float, trend: dict[str, Any]) -> str:
    tags = set(trend.get("tags") or [])
    if {"BIAS严重偏离MA5", "BIAS24严重正乖离"} & tags or score < 45:
        return "HIGH"
    if {"RSI短线过热", "RSI短线偏热", "BIAS12明显正乖离", "接近或突破布林上轨"} & tags or score < 60:
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
    buy_actions = {"OPEN", "LIGHT_OPEN", "ADD", "HOLD_OR_ADD", "HOLD_WAIT_ADD"}
    if action in buy_actions and {"买入", "加仓", "提高网格买入侧"} & blocked:
        warnings.append("交易过滤限制新增买入，仓位动作降级为观察/持有")
        return ("HOLD" if holding else "WATCH"), current_ratio, current_ratio, 0.0
    return action, target_ratio, new_ratio, adjust_ratio


def _action_copy(action: str, high_risk: bool, score: float) -> list[str]:
    if action == "OPEN":
        return ["短线趋势较强且无明显过热或波动放大，可进入建仓观察区；首笔不建议一次性重仓"]
    if action == "LIGHT_OPEN":
        return ["短线趋势偏强，可轻仓建仓观察，后续继续看 MA5、量能和短线动能稳定性"]
    if action == "WATCH":
        if high_risk and score >= 75:
            return ["趋势评分较高但存在短线过热或偏离过大，不适合直接追高"]
        return ["短线趋势强度不足或交易过滤受限，暂不进入建仓区"]
    if action == "HOLD":
        return ["当前仓位与目标仓位基本匹配，继续持有观察"]
    if action == "ADD":
        return ["短线趋势评分较高且目标仓位高于当前仓位，可按单次上限分步加仓"]
    if action == "HOLD_OR_ADD":
        return ["目标仓位高于当前仓位，但加仓确认条件不足，先持有观察"]
    if action == "HOLD_WAIT_ADD":
        return ["目标仓位高于当前仓位，但加仓确认条件不足，先持有并等待加仓确认"]
    if action == "REDUCE":
        return ["目标仓位低于当前仓位，建议降低部分仓位"]
    if action in {"TREND_REVIEW", "RISK_REVIEW"}:
        return ["短线趋势出现异常变化，触发持仓趋势复核"]
    if action in {"EXIT_TREND_POSITION", "EXIT_SHORT_TERM"}:
        return ["短线趋势明显转弱，建议退出短线仓位或降至观察仓位"]
    return []


def _portfolio_state(position: Position | None, positions: list[Position], category: str) -> dict[str, Any]:
    total_value = sum(item.market_value for item in positions if item.market_value > 0)
    confident_positions = [item for item in positions if item.market_value > 0 and _is_confident_position_pct(item)]
    low_confidence = bool(positions) and len(confident_positions) != len([item for item in positions if item.market_value > 0])
    total_position_pct = sum((item.position_pct or 0) for item in confident_positions)
    position_pct = position.position_pct if position and position.position_pct is not None else 0
    category_value = sum(item.market_value for item in positions if classify_etf(item.name) == category)
    category_position_pct = sum((item.position_pct or 0) for item in confident_positions if classify_etf(item.name) == category)
    fallback_total_pct = sum((item.position_pct or 0) for item in positions if item.market_value > 0)
    fallback_category_pct = sum((item.position_pct or 0) for item in positions if item.market_value > 0 and classify_etf(item.name) == category)
    return {
        "category": category,
        "position_pct": position_pct or 0,
        "total_position_pct": total_position_pct or 0,
        "category_pct": category_position_pct or (category_value / total_value * total_position_pct if total_value and total_position_pct else 0),
        "position_pct_confidence": "low" if low_confidence else "high",
        "position_pct_source": position.position_pct_source if position else None,
        "fallback_holding_total_pct": fallback_total_pct or 0,
        "fallback_holding_category_pct": fallback_category_pct or 0,
    }


def _is_confident_position_pct(position: Position) -> bool:
    source = str(position.position_pct_source or "")
    return source in {"ths_account_total_asset", "ths_position_fund_pct"}


def _liquidity_threshold(category: str) -> float:
    if category == "宽基ETF":
        return 200_000_000
    if category == "行业主题ETF":
        return 80_000_000
    if category in {"债券ETF", "货币ETF"}:
        return 30_000_000
    return 50_000_000


def _short_trend_level(score: float) -> tuple[str, str]:
    if score >= 85:
        return "STRONG_TREND", "短线强趋势"
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
