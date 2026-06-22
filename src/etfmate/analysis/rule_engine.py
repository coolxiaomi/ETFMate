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
        "trend_level": _trend_level(trend["score"]),
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
    score = 0
    evidence: list[str] = []
    if market.ma20 and market.last_price > market.ma20:
        score += 20
        evidence.append("现价高于MA20")
    if market.ma20 and market.ma60 and market.ma20 > market.ma60:
        score += 20
        evidence.append("MA20高于MA60")
    if market.ma60 and market.ma120 and market.ma60 > market.ma120:
        score += 20
        evidence.append("MA60高于MA120")
    if market.ma20_slope_pct is not None and market.ma20_slope_pct > 0:
        score += 20
        evidence.append("MA20近5日斜率向上")
    if market.ma120 and market.last_price > market.ma120:
        score += 20
        evidence.append("现价高于MA120")
    return {"score": score, "evidence": evidence or ["趋势指标不足或未确认"]}


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


def _trend_level(score: int) -> str:
    if score >= 80:
        return "强趋势"
    if score >= 60:
        return "中等趋势"
    if score >= 40:
        return "震荡"
    return "弱趋势"


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
