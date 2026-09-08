from __future__ import annotations

from etfmate.analysis.rule_engine import decide_position
from etfmate.storage.models import GridConfig, MarketSnapshot, Position


def recommend(
    position: Position | None, grid: GridConfig | None, market: MarketSnapshot,
    all_positions: list[Position] | None = None, all_markets: list[MarketSnapshot] | None = None,
) -> dict:
    from dataclasses import asdict
    rule = decide_position(position, grid, market, all_positions, all_markets)
    plan = "；".join(rule["reasons"])
    return {
        **asdict(market),
        "strategy_role": rule["strategy_role"], "strategy_label": rule["strategy_label"],
        "funding_plan": rule["funding_plan"],
        "pair_target_weight": rule["pair_target_weight"], "pair_progress": rule["pair_progress"],
        "candidate_source": "真实持仓" if position else "指定目标" if rule["strategy_role"] != "LEGACY_EXIT" else "现有网格",
        "quantity": position.quantity if position else None,
        "market_value": position.market_value if position else None,
        "position_pct": position.position_pct if position else None,
        "holding_pct": position.holding_pct if position else None,
        "position_pct_source": position.position_pct_source if position else None,
        "account_total_asset": position.account_total_asset if position else None,
        "pnl": position.pnl if position else None, "pnl_pct": position.pnl_pct if position else None,
        "cost_price": position.cost_price if position else None,
        "investor_note": position.note if position else None,
        "action": rule["action"], "action_quantity": None,
        "candidate_liquidation_quantity": position.quantity if position and rule["position_action"] == "LIQUIDATE_CONDITIONAL" else None,
        "position_plan": plan, "entry_plan": plan,
        "current_status": _status(position, grid, market),
        "ma_status": _ma_status(market), "rule_decision": rule, "sell_policy": rule["sell_policy"],
        "reasons": rule["reasons"], "risks": rule["risks"],
        **{key: rule.get(key) for key in ("account_mode", "position_action", "execution_mode",
            "target_position_pct", "current_position_ratio", "target_position_ratio", "new_position_ratio",
            "adjust_ratio", "current_position_pct", "new_position_pct", "adjust_pct")},
        "position_risk_level": rule["risk_level"], "rule_trend_score": rule["trend_score"],
    }


def _status(position: Position | None, grid: GridConfig | None, market: MarketSnapshot) -> str:
    parts = [f"现价 {market.last_price:.3f}，涨跌幅 {market.pct_chg:.2f}%"]
    if position:
        parts.append(f"持仓 {position.quantity:g} 份，浮盈亏 {position.pnl_pct:.2f}%")
    if grid:
        parts.append("网格已启用" if grid.enabled else "网格暂停")
    return "；".join(parts)


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
