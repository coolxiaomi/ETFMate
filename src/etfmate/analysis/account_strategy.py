"""User-confirmed account roles; group weights are never account allocations."""
from __future__ import annotations

from math import isfinite
from typing import Any

from etfmate.storage.models import Position

ANALYSIS_CONTRACT = "etf_account_transition_v7"
FUNDING_PRIORITY = "LEGACY_RECOVERY_FIRST"
FUNDING_PRIORITY_NOTE = "现有资金优先用于待退出ETF的回本管理；先安排合理的回补与周转预留，目标组合仅使用之后确认剩余的可用资金。未成交回款不能预支，资金优先不等于无条件补仓。"
TARGETS = {
    "510500": {"name": "南方中证500ETF", "role": "VOLATILITY", "label": "宽基赚波动"},
    "159141": {"name": "永赢科创创业人工智能ETF", "role": "SECTOR_DIP", "label": "赛道低吸"},
    "159259": {"name": "易方达国证成长100ETF", "role": "PAIR_GROWTH", "label": "成长逐步建仓", "pair_weight": 0.4},
    "159263": {"name": "易方达国证价值100ETF", "role": "PAIR_VALUE", "label": "价值逐步建仓", "pair_weight": 0.6},
}


def role_for(code: str) -> dict[str, Any]:
    return dict(TARGETS.get(code, {"role": "LEGACY_EXIT", "label": "现有持仓管理与退出"}))


def pair_progress(positions: list[Position]) -> dict:
    values = {code: sum(p.market_value for p in positions if p.code == code and p.quantity > 0)
              for code in ("159259", "159263")}
    total = sum(values.values())
    valid = all(isfinite(v) and v >= 0 for v in values.values()) and total > 0
    weights = {code: values[code] / total if valid else None for code in values}
    underweight = min(values, key=lambda c: weights[c] - TARGETS[c]["pair_weight"]) if valid else None
    if valid and abs(weights["159259"] - 0.4) < 1e-6:
        underweight = None
    return {"phase": "BUILDING", "total_market_value": total if valid else 0,
            "current_weights": weights, "target_weights": {"159259": 0.4, "159263": 0.6},
            "dip_buy_priority": underweight,
            "note": "40/60仅指组内市值；低配侧低吸优先，不强卖高配侧，暂时达标≠建仓完成。"}


def account_overview(recommendations: list[dict], summary: dict | None = None) -> dict:
    summary = summary or {}
    held = [r for r in recommendations if (r.get("quantity") or 0) > 0]
    legacy = [r for r in held if r.get("strategy_role") == "LEGACY_EXIT"]
    market_value = sum(r.get("market_value") or 0 for r in held)
    asset = summary.get("total_asset") or next((r.get("account_total_asset") for r in held if r.get("account_total_asset")), None)
    portfolios = [(r.get("rule_decision") or {}).get("portfolio") or {} for r in recommendations]
    totals = [p.get("total_position_pct") for p in portfolios if p.get("position_pct_confidence") == "high"]
    totals = [value for value in totals if isinstance(value, (int, float)) and isfinite(value)]
    total = max(totals) if totals else None
    position_note = (f"账户仓位 {total:.2f}%，已达80%保护线：本批次不安排新增买入或回补，部分卖出仍可单独评估。"
                     if total is not None and total >= 80 else
                     f"账户仓位 {total:.2f}%；买入份额仍需核实可用资金与累计占用。" if total is not None else
                     "账户仓位口径未确认，买入份额需核实可用资金与累计占用。")
    return {"held_count": len(held), "target_count": len(TARGETS), "max_target_count": 5,
            "legacy_count": len(legacy), "market_value": market_value,
            "total_asset": asset, "available_cash": summary.get("available_cash"),
            "position_note": position_note, "total_position_pct": total,
            "external_cash_flow_policy": "NO_DEPOSITS_NO_WITHDRAWALS",
            "funding_priority": FUNDING_PRIORITY,
            "cash_note": "资金净流入=0；净值随盈亏变化。",
            "pair": next((r.get("pair_progress") for r in recommendations if r.get("pair_progress")), None),
            "direction": "先管理旧仓 → 预留回补与周转 → 余款分批配置目标。",
            "tasks": ["逐只复评：持有 / 分批卖出 / 受控回补 / 回本退出。",
                      "先留旧仓回补＋周转资金；未成交回款不预支。",
                      "余款>0＋价格合适 → 分批建目标仓。"]}
