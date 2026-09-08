"""User-confirmed account roles; group weights are never account allocations."""
from __future__ import annotations

from math import isfinite
from typing import Any

from etfmate.storage.models import Position

ANALYSIS_CONTRACT = "etf_account_transition_v4"
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
            "note": "成长40%／价值60%为组内市值目标；逐步建仓，低配侧满足低吸条件才优先补入。暂不机械卖出高配侧，也不因暂时达标切换维护期。"}


def account_overview(recommendations: list[dict], summary: dict | None = None) -> dict:
    summary = summary or {}
    held = [r for r in recommendations if (r.get("quantity") or 0) > 0]
    legacy = [r for r in held if r.get("strategy_role") == "LEGACY_EXIT"]
    market_value = sum(r.get("market_value") or 0 for r in held)
    asset = summary.get("total_asset") or next((r.get("account_total_asset") for r in held if r.get("account_total_asset")), None)
    return {"held_count": len(held), "target_count": len(TARGETS), "max_target_count": 5,
            "legacy_count": len(legacy), "market_value": market_value,
            "total_asset": asset, "available_cash": summary.get("available_cash"),
            "external_cash_flow_policy": "NO_DEPOSITS_NO_WITHDRAWALS",
            "funding_priority": FUNDING_PRIORITY,
            "cash_note": "资金不追加也不转出，账户净值仍随盈亏变化。" + FUNDING_PRIORITY_NOTE,
            "pair": next((r.get("pair_progress") for r in recommendations if r.get("pair_progress")), None),
            "direction": "现有资金优先支持待退出ETF的回本管理；目标组合使用满足该优先安排后剩余的可用资金逐步建立。",
            "tasks": ["逐只检查现有持仓：继续持有、反弹分批卖出、受控波动回补或盈利退出。",
                      "先明确待退出ETF的回补和周转预留，逐笔分配实际可用资金，不提前使用未成交回款。",
                      "扣除上述安排后仍有可用资金，且价格合适时，再考虑目标组合；不挤占旧仓回本管理资金。"]}
