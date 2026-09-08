from __future__ import annotations

from typing import Any

from etfmate.storage.models import GridConfig, MarketSnapshot, Position
from etfmate.analysis.sell_policy import assess_sell_policy

def advise_grid(
    grid: GridConfig | None, market: MarketSnapshot, position: Position | None = None,
    rule_decision: dict[str, Any] | None = None,
) -> dict:
    from math import isfinite, ceil
    from etfmate.analysis.account_strategy import role_for
    role = role_for(market.code)
    rule = rule_decision or {}
    held = position.quantity if position else 0
    held = held if isfinite(held) and held > 0 else 0
    advice = {
        "code": market.code, "name": market.name, "strategy_role": role["role"],
        "strategy_profile": "隔日或每周数次的低频条件计划；实际触发次数取决于行情",
        "grid_applicable": False, "execution_plan_type": "CONDITIONAL_PLAN",
        "action": "按行情调整条件计划", "grid_mode": "CONDITIONAL", "grid_mode_label": "低频条件计划",
        "buy_execution_status": "PENDING_BUDGET", "sell_execution_status": "PENDING_INVENTORY",
        "cash_constraint_status": "UNVERIFIED", "suggested_buy_quantity": None,
        "suggested_sell_quantity": None, "suggested_max_position_quantity": None,
        "suggested_min_base_quantity": None, "candidate_buy_quantity": None,
        "candidate_sell_quantity": None, "minimum_sell_price": None,
        "execution_checks": [], "reasons": [], "strategy_guardrails": [],
        "current_base_price": grid.base_price if grid else None,
        "current_buy_quantity": grid.buy_quantity if grid else None,
        "current_sell_quantity": grid.sell_quantity if grid else None,
        "current_min_base_quantity": grid.min_base_quantity if grid else None,
        "current_max_position_quantity": grid.max_position_quantity if grid else None,
        "min_base_status": "CONFIGURED" if grid and grid.min_base_quantity is not None else "UNSET",
        "max_position_status": "CONFIGURED" if grid and grid.max_position_quantity is not None else "UNSET",
        "buy_quantity_note": "缺少有效行情，暂不计算",
        "sell_quantity_note": "缺少有效行情，暂不计算",
        "buyback_quantity_note": "暂不安排回补",
    }
    legacy = role["role"] == "LEGACY_EXIT"
    if legacy and not held:
        policy = assess_sell_policy(position, market)
        advice.update(action="停用买入侧，等待清仓核验", grid_mode="LEGACY_EXIT",
                      grid_mode_label="过渡退出", buy_execution_status="DISABLED",
                      sell_execution_status="LIQUIDATION_REVIEW", sell_policy=policy,
                      minimum_sell_price=policy["minimum_sell_price"],
                      buy_quantity_note="旧网格停止新增买入", sell_quantity_note="未持仓",
                      reasons=["旧持仓不再补仓摊低成本；旧网格不能自动清空库存。", policy["reason"]])
        return advice
    atr = market.atr14_pct
    if atr is None or not isfinite(atr) or atr <= 0 or not isfinite(market.last_price) or market.last_price <= 0:
        advice.update(action="等待有效行情", reasons=["缺少有效价格或ATR，不能生成百分比参数。"])
        return advice
    # Starting heuristics only: no fitted returns or guaranteed trigger frequency.
    building = role["role"] in {"SECTOR_DIP", "PAIR_GROWTH", "PAIR_VALUE"}
    fall = round(max(3.0 if building else 2.0, atr * (1.8 if building else 1.4)), 2)
    if fall >= 100:
        advice.update(action="等待波动数据复核", reasons=["计算出的下跌间距达到100%，不能生成有效买入价格。"])
        return advice
    rise = round(max(1.5, atr * (0.9 if building else 1.2)), 2)
    rebound = round(min(0.8, max(0.15, atr * 0.15)), 2)
    pullback = round(min(0.6, max(0.1, atr * 0.10)), 2)
    base = grid.base_price if grid and grid.base_price and isfinite(grid.base_price) and grid.base_price > 0 else market.last_price
    if legacy:
        base = market.last_price  # A new staged-exit proposal, not a change to the live grid.
    # Never silently rebase a live grid. Material drift needs manual review.
    stale_base = abs(market.last_price / base - 1) * 100 > 2 * max(fall, rise)
    reserve = max(100, ceil(held * 0.5 / 100) * 100) if held > 0 else 100
    if legacy:
        reserve = 100
    if grid and grid.min_base_quantity is not None and isfinite(grid.min_base_quantity):
        reserve = max(reserve, ceil(grid.min_base_quantity / 100) * 100)
    raw_sell = (grid.sell_quantity if grid and grid.sell_quantity is not None else grid.order_quantity if grid else None)
    if legacy and raw_sell is None:
        raw_sell = held * 0.25  # Staged-exit candidate derived from actual inventory.
    sell = int(min(raw_sell, max(0, held - reserve)) // 100) * 100 if raw_sell is not None and isfinite(raw_sell) and raw_sell > 0 else 0
    raw_buy = (grid.buy_quantity if grid and grid.buy_quantity is not None else grid.order_quantity if grid else None)
    candidate_buy = int(raw_buy // 100) * 100 if raw_buy is not None and isfinite(raw_buy) and raw_buy > 0 else None
    if building and sell > 0:
        candidate_buy = max(candidate_buy or 0, sell * 2)
    # An omitted optional ceiling adds no fixed limit. Respect an explicit zero.
    ceiling = grid.max_position_quantity if grid else None
    if ceiling is not None and isfinite(ceiling) and candidate_buy is not None:
        candidate_buy = min(candidate_buy, int(max(0, ceiling - held) // 100) * 100) or None
    blocked = set(rule.get("blocked_actions") or [])
    total = (rule.get("portfolio") or {}).get("total_position_pct")
    buy_blocked = bool(blocked & {"全部", "买入", "加仓"}) or rule.get("high_risk") or rule.get("risk_level") == "HIGH" or (total is not None and total >= 80)
    policy = assess_sell_policy(position, market, sell_price=base * (1 + rise / 100) * (1 - pullback / 100),
                                sell_quantity=sell if sell else None)
    advice.update(
        suggested_base_price=base, base_price_status="REVIEW_DRIFT" if stale_base else "REFERENCE",
        suggested_buy_fall_pct=fall, suggested_buy_rebound_pct=rebound,
        suggested_sell_rise_pct=rise, suggested_sell_pullback_pct=pullback,
        candidate_buy_quantity=None if buy_blocked else candidate_buy,
        candidate_sell_quantity=sell or None,
        suggested_min_base_quantity=reserve if held > 0 else None,
        current_max_position_quantity=grid.max_position_quantity if grid else None,
        buy_execution_status="DISABLED" if buy_blocked else "PENDING_BUDGET",
        sell_execution_status="PENDING_INVENTORY" if sell > 0 else "DISABLED",
        sell_policy=policy, minimum_sell_price=None,
        first_buy_reference_price=round(base * (1 - fall / 100) * (1 + rebound / 100), 4),
        first_sell_reference_price=round(base * (1 + rise / 100) * (1 - pullback / 100), 4),
        quantity_plan="建仓期建议买入份额大于卖出份额，候选按至少2:1估算；资金不足时减少卖出或等待，不预支资金。" if building else "买卖份额分别配置；保留至少一半现有库存作为候选底仓。",
        buy_quantity_note=("新增买入已暂停" if buy_blocked else
                           "已达最大持仓或剩余额度不足100份" if ceiling is not None and ceiling - held < 100 else
                           "现有买入数量不足100份或已停用" if raw_buy is not None else "未设置单笔买入数量"),
        sell_quantity_note=("未持仓" if not held else "保留建议底仓后不足100份" if held - reserve < 100 else
                            "现有卖出数量不足100份或已停用" if raw_sell is not None else "未设置单笔卖出数量"),
        reasons=["参数按本次ATR生成，随行情重新计算；属于起始建议，不保证收益或触发频率。"],
        strategy_guardrails=[
            "未设置底仓上下限表示不设固定限制；建议保留量不是平台已配置值。执行时检查可卖量与累计占用，循环卖出仍须防止未经核验清仓。",
            "部分卖出允许低于成本；每次成交更新净投入，最后一笔须单独满足清仓回本价。",
            "买入建议沿用现有数量或按建仓比例估算；执行前按实际可用现金、预算和累计委托占用调整。",
        ],
        execution_checks=[
            {"check": "cash_and_reservations", "status": "PENDING", "message": "全账户预算与网格累计占用未核验"},
            {"check": "inventory_floor", "status": "PENDING", "message": "核实可卖量并确认平台能够保护最低底仓"},
            {"check": "liquidation_gate", "status": "REQUIRED", "message": "最后一笔须核验清仓不亏，部分卖出不视为清仓授权"},
        ],
    )
    if stale_base:
        advice["reasons"].append("现有基准价偏离当前行情较大，等待复核；不能照抄或自动重置。")
    if buy_blocked:
        advice["reasons"].append("风险或组合仓位限制已阻断新增买入。")
    if legacy:
        buyback = int(sell * 0.5 // 100) * 100 if sell > 0 and not buy_blocked else 0
        if ceiling is not None and isfinite(ceiling):
            buyback = min(buyback, int(max(0, ceiling - (held - sell)) // 100) * 100)
        advice.update(
            action="反弹分批卖出，回款留在账户内", grid_mode="TRANSITION_MANAGEMENT",
            grid_mode_label="现有持仓波动管理", buy_execution_status="DISABLED" if buy_blocked else "WAIT_EXECUTED_PROCEEDS",
            candidate_buy_quantity=None, conditional_buyback_quantity=buyback or None,
            suggested_min_base_quantity=reserve, liquidation_policy=assess_sell_policy(position, market),
            buyback_quantity_note=("风险或组合仓位限制，暂停回补" if buy_blocked else
                                   "卖出后的最大持仓额度不足100份" if ceiling is not None and ceiling - (held - sell) < 100 else
                                   "分批卖出建议不足200份，暂不安排回补"),
            quantity_plan="卖出候选按实际网格数量或当前持仓约1/4分批；后续低位回补最多采用本笔已卖份额的一半作为候选，逐步减小旧仓，剩余回款留待目标配置。",
        )
        advice["reasons"].insert(0, "即使清仓成本暂未核实，仍提供反弹价格、部分卖出数量和条件回补方案。此处基准采用当前价拟定新计划，实际网格需另行检查后调整。")
        advice["strategy_guardrails"].append("回补必须在本笔卖出真实成交后重算：买入量不超过实际已卖量，金额不超过划给回补的可用回款；同一笔钱不能同时承诺给回补和目标建仓。")
    return advice
