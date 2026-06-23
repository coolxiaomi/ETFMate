from __future__ import annotations

from typing import Any

from etfmate.storage.models import GridConfig, MarketSnapshot, Position


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
    action, reasons, risks = _action_from_scores(position, grid, market, filters, trend, momentum, risk, total, portfolio)
    return {
        "action": action,
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
        "risk_level": _risk_level(risk["score"]),
        "total_score": total,
        "filter_status": filters["status"],
        "blocked_actions": filters["blocked_actions"],
        "target_position_pct": _target_position_pct(total, risk["score"], category),
        "portfolio": portfolio,
        "reasons": reasons[:5],
        "risks": risks[:5],
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
    if position and position.available_quantity is not None and position.available_quantity <= 0:
        blocked.update({"卖出", "减仓"})
        reasons.append("可用数量为0，今日不应给可立即卖出的执行建议")
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


def _action_from_scores(
    position: Position | None,
    grid: GridConfig | None,
    market: MarketSnapshot,
    filters: dict[str, Any],
    trend: dict[str, Any],
    momentum: dict[str, Any],
    risk: dict[str, Any],
    total: float,
    portfolio: dict[str, Any],
) -> tuple[str, list[str], list[str]]:
    reasons = [f"趋势{trend['score']}，动量{momentum['score']}，风险{risk['score']}，综合{total}"]
    risks = list(filters["reasons"])
    blocked = set(filters["blocked_actions"])
    if filters["status"] == "禁止交易":
        return "禁止交易", reasons, risks

    has_position = bool(position and position.market_value > 0 and position.quantity > 0)
    high_weight = bool(portfolio["position_pct"] >= 5)
    very_high_weight = bool(portfolio["position_pct"] >= 8)
    target_pct = _target_position_pct(total, risk["score"], portfolio["category"])

    if has_position:
        if market.ma60 and market.ma20 and market.last_price < market.ma60 and market.ma20 < market.ma60 and trend["score"] < 40:
            if {"卖出", "减仓"} & blocked:
                return "持有", reasons + ["趋势转弱但当前可用数量不足，先记录风险等待可交易"], risks
            if portfolio["category"] in {"宽基ETF", "债券ETF", "货币ETF"} or "卖出" in blocked:
                return "减仓", reasons + ["中长期趋势转弱，核心/防守类优先降仓而非直接清零"], risks
            return "卖出", reasons + ["趋势跌破且均线空头，非核心主题仓位优先退出"], risks
        if position and position.pnl_pct <= -8 and market.ma20 and market.last_price < market.ma20:
            if {"卖出", "减仓"} & blocked:
                return ("暂停买入侧" if grid and grid.enabled else "持有"), reasons + ["亏损且趋势弱，但当前可用数量不足，先暂停新增买入"], risks
            if high_weight and trend["score"] < 60 and "减仓" not in blocked:
                return "减仓", reasons + ["浮亏超过8%且跌破MA20，先降低风险暴露"], risks
            return ("暂停买入侧" if grid and grid.enabled else "持有"), reasons + ["亏损仓位先停止新增买入，等待趋势修复"], risks
        if market.ma20 and market.last_price < market.ma20 and trend["score"] < 60 and "减仓" not in blocked:
            return "减仓", reasons + ["跌破MA20且趋势分不足，减仓优先于补仓"], risks
        if position and position.pnl_pct > 15 and (market.rsi14 or 0) > 80 and _ma20_deviation(market) > 10 and "减仓" not in blocked:
            return "减仓", reasons + ["浮盈较高且RSI/偏离过热，分批兑现"], risks
        if very_high_weight:
            return "持有", reasons + ["仓位已高于8%，即使评分较好也不继续加仓"], risks
        if portfolio["position_pct"] < target_pct and trend["score"] >= 80 and momentum["score"] >= 70 and risk["score"] < 60 and not ({"买入", "加仓"} & blocked):
            return "分批加仓", reasons + [f"当前仓位低于目标仓位{target_pct:.1f}%"], risks
        return "持有", reasons + ["未触发加仓或减仓的高优先级条件"], risks

    if trend["score"] >= 80 and momentum["score"] >= 70 and risk["score"] < 60 and not ({"买入", "加仓"} & blocked):
        if _ma20_deviation(market) <= 8:
            return "分批买入", reasons + ["趋势和动量达标，且未明显远离MA20"], risks
        return "观察", reasons + ["趋势达标但价格远离MA20，等待回踩"], risks
    return "观察", reasons + ["无持仓且评分未满足新买入条件"], risks


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


def _target_position_pct(total_score: float, risk_score: float, category: str) -> float:
    if category in {"货币ETF", "债券ETF"}:
        base = 12.0
    elif category == "宽基ETF":
        base = 10.0
    elif category == "跨境ETF":
        base = 6.0
    else:
        base = 5.0
    if total_score >= 80:
        base *= 1.5
    elif total_score < 50:
        base *= 0.6
    if risk_score >= 50:
        base *= 0.5
    return min(base, 15.0)


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


def _risk_level(score: int) -> str:
    if score >= 70:
        return "高风险"
    if score >= 40:
        return "中风险"
    return "低风险"


def _ma20_deviation(market: MarketSnapshot) -> float:
    if not market.ma20:
        return 0.0
    return abs(market.last_price / market.ma20 - 1) * 100


def _top_percentile(market: MarketSnapshot, all_markets: list[MarketSnapshot], field: str, pct: float) -> bool:
    values = sorted(
        [(getattr(item, field), item.code) for item in all_markets if getattr(item, field, None) is not None],
        reverse=True,
    )
    if len(values) < 3:
        return False
    cutoff = max(1, round(len(values) * pct))
    return market.code in {code for _, code in values[:cutoff]}
