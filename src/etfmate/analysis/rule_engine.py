from __future__ import annotations

from typing import Any
from math import isfinite

from etfmate.storage.models import GridConfig, MarketSnapshot, Position
from etfmate.analysis.sell_policy import assess_sell_policy
from etfmate.analysis.account_strategy import role_for, pair_progress, FUNDING_PRIORITY, FUNDING_PRIORITY_NOTE

def decide_position(
    position: Position | None, grid: GridConfig | None, market: MarketSnapshot,
    all_positions: list[Position] | None = None, all_markets: list[MarketSnapshot] | None = None,
) -> dict[str, Any]:
    role = role_for(market.code)
    positions = all_positions if all_positions is not None else ([position] if position else [])
    category = "行业主题ETF" if role["role"] == "SECTOR_DIP" else classify_etf(market.name)
    filters = _trade_filters(market, position, category)
    trend = _trend_score(market)
    portfolio = _portfolio_state(position, positions, category)
    policy = assess_sell_policy(position, market)
    held = bool(position and position.quantity > 0)
    current = position.position_pct / 100 if held and position.position_pct is not None else None
    overheat = _trend_overheat_level(market, trend)
    high_risk = trend["score"] < 45 or "全部" in filters["blocked_actions"] or overheat == "SEVERE_OVERHEATED"
    blocked = set(filters["blocked_actions"])
    reasons = []
    risks = list(filters["reasons"])
    total = portfolio.get("total_position_pct")
    if total is not None and total >= 80:
        blocked.add("买入")
        risks.append("组合达到现有80%保护上限，暂停新增买入。")
    if high_risk:
        blocked.add("买入")
        risks.append("趋势或行情风险较高，暂停新增投入；不据此自动亏损清仓。")
    if role["role"] == "LEGACY_EXIT":
        action, state = "持有并做波动改善，反弹分批退出", "MANAGE_EXISTING"
        if high_risk:
            action = "暂停回补，等待反弹分批回收资金"
        if not held:
            blocked.update({"买入", "加仓", "提高网格买入侧"})
            action, state = "停用已退出标的计划", "RETIRE_GRID"
        elif policy["sell_allowed"]:
            action, state = "盈利或回本清仓候选，执行前复核", "LIQUIDATE_CONDITIONAL"
        reasons.append("最终退出不代表现在只等清仓：继续根据行情提供持有、波动改善、反弹分批卖出与最终退出建议。")
        if held:
            reasons.append("回补仅是先卖后买、份额不超过已卖份额的条件方案，须核实实际回款；不自动扩大旧仓。")
            risks.append(policy["reason"] + "清仓核验缺口不阻断部分卖出的行情与数量候选。")
    else:
        action, state = "等待回落，分批建仓", "WAIT_DIP"
        if role["role"] == "VOLATILITY":
            action = "保留底仓，等待低频波动" if held else "等待分批建立波动底仓"
            reasons.append("510500用于隔日或每周数次的波动交易；实际频率由行情决定，不承诺触发次数。")
        else:
            reasons.append("跌多分批买入，可用较小涨幅部分卖出；买卖触发不对称不等于必然净增仓。")
        if "买入" in blocked or "全部" in blocked:
            action, state = "暂停新增投入，等待复核", "WAIT_BUY_REVIEW"
        risks.append("角色预算、实际可用现金及全部网格预留未统一核实，暂不输出可直接下单的买入份额。")
    pair = pair_progress(positions) if role["role"].startswith("PAIR_") else None
    if pair:
        reasons.insert(0, pair["note"])
        priority = pair["dip_buy_priority"]
        if priority and priority != market.code:
            blocked.add("买入")
            reasons.append(f"当前组内高配，暂缓新增买入；优先等待低配侧 {priority} 的回落条件，不机械卖出本标的。")
            if state == "WAIT_DIP":
                action, state = "暂缓补入高配侧，保留持仓", "WAIT_PAIR_BALANCE"
    funding = None if role["role"] == "LEGACY_EXIT" else {
        "mode": "PRICE_AND_AVAILABLE_CASH", "allow_existing_cash": True,
        "priority": FUNDING_PRIORITY,
        "requires_legacy_reserve_first": True,
        "target_funding_scope": "VERIFIED_SURPLUS_AFTER_LEGACY_RESERVE",
        "primary_future_source": "EXECUTED_LEGACY_PROCEEDS", "count_unfilled_proceeds": False,
        "note": FUNDING_PRIORITY_NOTE,
    }
    if funding:
        reasons.insert(0, funding["note"])
    return {
        "funding_plan": funding,
        "strategy_role": role["role"], "strategy_label": role["label"],
        "pair_target_weight": role.get("pair_weight"), "pair_progress": pair,
        "sell_policy": policy, "signal_position_action": state,
        "account_mode": "ROLE_BASED_ACCUMULATION", "action": action, "action_name": action,
        "position_action": state, "category": category,
        "trend_score": trend["score"], "trend_level": trend["name"], "trend_code": trend["level"],
        "trend_tags": trend["tags"], "trend_scores": trend["scores"],
        "trend_indicators": trend["indicators"], "trend_data_sufficient": trend["data_sufficient"],
        "trend_overheat_level": overheat,
        "trend_trade_mode": "低频条件计划", "execution_mode": "CONDITIONAL_PLAN",
        "risk_level": "HIGH" if high_risk else "MEDIUM", "filter_status": filters["status"],
        "blocked_actions": sorted(blocked | ({"清仓"} if not policy["sell_allowed"] else set())),
        "current_position_ratio": current, "target_position_ratio": 0 if high_risk or role["role"] == "LEGACY_EXIT" else None,
        "new_position_ratio": current, "adjust_ratio": 0,
        "current_position_pct": current * 100 if current is not None else None,
        "target_position_pct": 0 if high_risk or role["role"] == "LEGACY_EXIT" else None,
        "new_position_pct": current * 100 if current is not None else None, "adjust_pct": 0,
        "high_risk": high_risk, "no_high_risk": not high_risk, "portfolio": portfolio,
        "reasons": reasons, "risks": risks,
        "evidence": {"trend": trend["evidence"], "filters": filters["reasons"]},
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
    if not isfinite(market.last_price) or market.last_price <= 0:
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


def _trend_overheat_level(market: MarketSnapshot, trend: dict[str, Any]) -> str:
    indicators = trend.get("indicators") or {}
    boll_position = _num_or_none(indicators.get("boll_position")) or _num_or_none(market.boll_position)
    rsi6 = _num_or_none(indicators.get("rsi6")) or _num_or_none(market.rsi6)
    bias5 = _num_or_none(indicators.get("bias5")) or _num_or_none(market.bias5_ratio)
    bias6 = _num_or_none(market.bias6)
    bias12 = _num_or_none(indicators.get("bias12")) or _num_or_none(market.bias12)
    bias24 = _num_or_none(indicators.get("bias24")) or _num_or_none(market.bias24)
    close = _num_or_none(market.last_price)
    boll_upper = _num_or_none(market.boll_upper)

    severe = any(
        (
            boll_position is not None and boll_position >= 1.0,
            close is not None and boll_upper is not None and close > boll_upper,
            rsi6 is not None and rsi6 >= 85,
            bias6 is not None and bias6 >= 6,
            bias12 is not None and bias12 >= 10,
            bias24 is not None and bias24 >= 12,
        )
    )
    if severe:
        return "SEVERE_OVERHEATED"
    overheated = any(
        (
            boll_position is not None and boll_position >= 0.95,
            close is not None and boll_upper is not None and close >= boll_upper * 0.995,
            rsi6 is not None and rsi6 >= 75,
            bias12 is not None and bias12 >= 7,
            bias24 is not None and bias24 >= 8,
            bias5 is not None and bias5 >= 0.06,
        )
    )
    return "OVERHEATED" if overheated else "NONE"


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
