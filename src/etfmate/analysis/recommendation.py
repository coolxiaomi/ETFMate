from __future__ import annotations

from etfmate.storage.models import GridConfig, MarketSnapshot, Position


def recommend(position: Position | None, grid: GridConfig | None, market: MarketSnapshot) -> dict:
    action = "持有"
    reasons: list[str] = []
    risks: list[str] = []
    scores: list[str] = []

    boll_pos = _boll_position(market)
    bias6 = market.bias6 or 0
    position_pct = position.pnl_pct if position else 0
    holding_weight = position.market_value if position else 0
    above_ma20 = bool(market.ma20 and market.last_price >= market.ma20)
    above_ma60 = bool(market.ma60 and market.last_price >= market.ma60)
    vol_expanding = bool(market.vol_ma5 and market.vol_ma20 and market.vol_ma5 > market.vol_ma20 * 1.2)

    if boll_pos is not None:
        scores.append(f"BOLL分位 {boll_pos:.0%}")
    if market.atr14_pct:
        scores.append(f"ATR14 {market.atr14_pct:.2f}%")
    if market.bias6 is not None:
        scores.append(f"BIAS6 {market.bias6:.2f}%")

    if market.boll_lower and market.last_price <= market.boll_lower * 1.03 and bias6 < -3:
        action = "分批买入" if position else "买入"
        reasons.append("价格接近 BOLL 下轨且 BIAS6 明显负偏离")
    elif market.boll_upper and market.last_price >= market.boll_upper * 0.98 and bias6 > 3:
        action = "减仓"
        reasons.append("价格接近 BOLL 上轨且短线正偏离较大")
    elif market.ma60 and market.last_price < market.ma60:
        action = "暂停网格" if grid and grid.enabled else "持有"
        risks.append("价格低于 MA60，下跌趋势中机械补仓风险上升")
    else:
        reasons.append("趋势和波动暂未触发强动作信号")

    if above_ma20 and above_ma60:
        reasons.append("价格同时站上 MA20/MA60，趋势结构偏强")
    elif not above_ma20 and not above_ma60 and market.ma20 and market.ma60:
        risks.append("价格低于 MA20/MA60，趋势结构偏弱")
    elif not above_ma20 and market.ma20:
        risks.append("价格低于 MA20，短线仍需等待修复")

    if vol_expanding:
        reasons.append("VOL MA5 高于 MA20，近期成交活跃度抬升")
    elif market.vol_ma5 and market.vol_ma20 and market.vol_ma5 < market.vol_ma20 * 0.75:
        risks.append("成交量低于近20日均量，反弹持续性需要验证")

    if position:
        if position.pnl_pct <= -10:
            risks.append("持仓浮亏超过 10%，加仓前先确认仓位上限")
        elif position.pnl_pct >= 25 and bias6 > 2:
            reasons.append("已有较高浮盈且短线偏离为正，可考虑网格止盈或小幅减仓")
            if action == "持有":
                action = "减仓"
        if holding_weight > 5000 and not above_ma20:
            risks.append("单只市值较高且短线弱于 MA20，避免继续集中补仓")

    if market.data_quality != "ok":
        risks.append(f"行情数据完整性: {market.data_quality}")

    return {
        "code": market.code,
        "name": market.name,
        "quantity": position.quantity if position else None,
        "market_value": position.market_value if position else None,
        "position_pct": position.position_pct if position else None,
        "cost_price": position.cost_price if position else None,
        "last_price": market.last_price,
        "pnl_pct": position.pnl_pct if position else None,
        "boll_position_pct": round(boll_pos * 100, 1) if boll_pos is not None else None,
        "ma_status": _ma_status(market),
        "atr14_pct": market.atr14_pct,
        "bias6": market.bias6,
        "current_status": _status(position, grid, market),
        "action": action,
        "reasons": reasons,
        "risks": risks or ["暂无明显新增风险"],
        "watch_price": _watch_price(market),
        "indicators": "；".join(scores) if scores else "指标不足",
    }


def _status(position: Position | None, grid: GridConfig | None, market: MarketSnapshot) -> str:
    parts = [f"现价 {market.last_price:.3f}，涨跌幅 {market.pct_chg:.2f}%"]
    if position:
        parts.append(f"持仓 {position.quantity:g} 份，浮盈亏 {position.pnl_pct:.2f}%")
    if grid:
        parts.append("网格已启用" if grid.enabled else "网格暂停")
    return "；".join(parts)


def _watch_price(market: MarketSnapshot) -> str:
    prices = []
    if market.boll_lower:
        prices.append(f"BOLL 下轨 {market.boll_lower:.3f}")
    if market.ma20:
        prices.append(f"MA20 {market.ma20:.3f}")
    if market.boll_upper:
        prices.append(f"BOLL 上轨 {market.boll_upper:.3f}")
    return " / ".join(prices) if prices else "等待补齐 K 线指标"


def _ma_status(market: MarketSnapshot) -> str:
    states = []
    if market.ma20:
        states.append("上MA20" if market.last_price >= market.ma20 else "下MA20")
    if market.ma60:
        states.append("上MA60" if market.last_price >= market.ma60 else "下MA60")
    return "/".join(states) if states else "均线不足"


def _boll_position(market: MarketSnapshot) -> float | None:
    if not market.boll_upper or not market.boll_lower or market.boll_upper == market.boll_lower:
        return None
    return (market.last_price - market.boll_lower) / (market.boll_upper - market.boll_lower)
