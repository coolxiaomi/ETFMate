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
    from etfmate.analysis.technical_assessment import assess_technical
    technical = rule.get("technical_assessment") or assess_technical(market)
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
        "current_enabled": grid.enabled if grid else None,
        "current_buy_quantity": grid.buy_quantity if grid else None,
        "current_sell_quantity": grid.sell_quantity if grid else None,
        "current_min_base_quantity": grid.min_base_quantity if grid else None,
        "current_max_position_quantity": grid.max_position_quantity if grid else None,
        "min_base_status": "CONFIGURED" if grid and grid.min_base_quantity is not None else "UNSET",
        "max_position_status": "CONFIGURED" if grid and grid.max_position_quantity is not None else "UNSET",
        "buy_quantity_note": "缺少有效行情，暂不计算",
        "sell_quantity_note": "缺少有效行情，暂不计算",
        "buyback_quantity_note": "暂不安排回补",
        "parameter_plan": None, "grid_execution_status": "DO_NOT_ENABLE",
        "technical_assessment": technical, "specific_notes": [],
        "grid_execution_note": "暂不启用整单：缺少有效参数",
    }
    legacy = role["role"] == "LEGACY_EXIT"
    if legacy and not held:
        policy = assess_sell_policy(position, market)
        advice.update(action="停用旧网格", grid_mode="LEGACY_EXIT",
                      grid_mode_label="过渡退出", buy_execution_status="DISABLED",
                      sell_execution_status="LIQUIDATION_REVIEW", sell_policy=policy,
                      minimum_sell_price=policy["minimum_sell_price"],
                      buy_quantity_note="旧网格停止新增买入", sell_quantity_note="未持仓",
                      grid_execution_note="停用整单：旧标的已无持仓",
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
    original = {"buy_fall_pct": fall, "buy_rebound_pct": rebound,
                "sell_rise_pct": rise, "sell_pullback_pct": pullback}
    state = technical["status"]
    if state in {"WEAK", "OVERSOLD_UNCONFIRMED", "OVERHEATED"}:
        fall = round(fall * 1.25, 2)
        rebound = round(min(0.8, rebound * 1.5), 2)
        rise = round(max(1.5, rise * 0.85), 2)
        adjustment = "买入间距×1.25、反弹确认×1.5，卖出间距×0.85；仅保留复评草案。"
    elif state == "OVERSOLD_RECOVERY":
        rebound = round(min(0.8, rebound * 1.25), 2)
        adjustment = "初步修复：反弹确认×1.25，买入间距不缩窄。"
    else:
        adjustment = "沿用角色起始间距；量价状态决定是否等待确认。"
    basis_label = {"WEAK": "弱势修正", "OVERSOLD_UNCONFIRMED": "超卖未企稳修正",
                   "OVERHEATED": "过热修正", "OVERSOLD_RECOVERY": "初步修复，提高反弹确认"}
    advice["parameter_basis"] = {
        "atr14_pct": atr, "original": original, "technical_status": state,
        "adjustment": adjustment,
        "note": f"ATR14 {atr:.2f}% · {basis_label.get(state, '沿用角色起始间距')}",
    }
    if fall >= 100:
        advice.update(action="等待波动数据复核", reasons=["综合修正后下跌间距达到100%，不生成无效参数。"])
        return advice
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
    valid_sell = raw_sell is not None and isfinite(raw_sell) and raw_sell >= 100 and raw_sell % 100 == 0
    sell_draft = int(raw_sell) if valid_sell else max(100, int(held * 0.25 // 100) * 100)
    sell = int(min(sell_draft, max(0, held - reserve)) // 100) * 100
    raw_buy = (grid.buy_quantity if grid and grid.buy_quantity is not None else grid.order_quantity if grid else None)
    valid_buy = raw_buy is not None and isfinite(raw_buy) and raw_buy >= 100 and raw_buy % 100 == 0
    buy_draft = int(raw_buy) if valid_buy else 100
    candidate_buy = buy_draft
    if building and sell > 0:
        candidate_buy = max(candidate_buy, sell * 2)
    buy_draft = candidate_buy
    # An omitted optional ceiling adds no fixed limit. Respect an explicit zero.
    ceiling = grid.max_position_quantity if grid else None
    if ceiling is not None and isfinite(ceiling) and candidate_buy is not None:
        candidate_buy = min(candidate_buy, int(max(0, ceiling - held) // 100) * 100) or None
    buy_draft = candidate_buy or buy_draft
    blocked = set(rule.get("blocked_actions") or [])
    total = (rule.get("portfolio") or {}).get("total_position_pct")
    buy_blocked = bool(blocked & {"全部", "买入", "加仓"}) or rule.get("high_risk") or rule.get("risk_level") == "HIGH" or (total is not None and total >= 80) or technical["buy_gate"] == "WAIT_CONFIRMATION"
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
        buy_quantity_note=("新增投入受限，整单暂不启用" if buy_blocked else
                           "已达最大持仓或剩余额度不足100份" if ceiling is not None and ceiling - held < 100 else
                           "按合法单笔数量拟定"),
        sell_quantity_note=("未持仓" if not held else "保留建议底仓后不足100份" if held - reserve < 100 else
                            "按持仓与保留量拟定"),
        reasons=["参数按本次ATR生成，随行情重新计算；属于起始建议，不保证收益或触发频率。"],
        strategy_guardrails=[
            "建议保留量不是平台已配置值。启用前核实库存保护；无法保护时整单停用，部分卖出另行安排。",
            "部分卖出允许低于成本；每次成交更新净投入，最后一笔须单独满足清仓回本价。",
            "数量草案沿用合法单笔量，缺失或异常时按持仓或100份起拟；不代表已核验资金或可卖量。",
        ],
        execution_checks=[
            {"check": "cash_and_reservations", "status": "PENDING", "message": "全账户预算与网格累计占用未核验"},
            {"check": "inventory_floor", "status": "PENDING", "message": "核实可卖量并确认平台能够保护最低底仓"},
            {"check": "liquidation_gate", "status": "REQUIRED", "message": "最后一笔须核验清仓不亏，部分卖出不视为清仓授权"},
        ],
    )
    if stale_base:
        advice["reasons"].append("现有基准价偏离当前行情较大，等待复核；不能照抄或自动重置。")
        advice["specific_notes"].append("现有基准价偏离行情较大，需复核后调整。")
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
    blockers = []
    if total is not None and total >= 80:
        blockers.append(f"总仓{total:.2f}% ≥ 80%")
    if rule.get("high_risk") or rule.get("risk_level") == "HIGH":
        blockers.append("高风险")
    if buy_blocked and not blockers:
        blockers.append("新增投入受限")
    if technical["buy_gate"] == "WAIT_CONFIRMATION":
        blockers.append("量价条件未确认")
    if not held:
        blockers.append("未持仓，卖出库存不足")
    elif sell < 100:
        blockers.append("保留底仓后可卖不足100")
    if ceiling is not None and ceiling - held < 100 and not legacy:
        blockers.append("最大仓余量不足100")
    if stale_base:
        blockers.append("基准价偏离，需复核")
    if legacy:
        blockers.append("先卖后回补，需逐笔核实回款")
    if grid and not grid.enabled:
        blockers.append("当前整单已停用")
    if (raw_buy is not None and not valid_buy) or (raw_sell is not None and not valid_sell):
        blockers.append("原单数量异常，需核对")
    if grid and grid.min_base_quantity is not None and ceiling is not None and reserve > ceiling:
        blockers.append("建议底仓高于当前最大仓")
    # A complete settings draft is separate from action candidates and verified execution.
    # Touker cannot disable either side by entering zero or by a side-only pause.
    plan_buy = (advice.get("conditional_buyback_quantity") if legacy else advice["candidate_buy_quantity"])
    advice["parameter_plan"] = {
        "buy_quantity": plan_buy or (100 if legacy else buy_draft),
        "sell_quantity": sell or sell_draft,
        "buy_fall_pct": fall, "buy_rebound_pct": rebound,
        "sell_rise_pct": rise, "sell_pullback_pct": pullback,
        "buy_quantity_source": ("成交后回补比例" if plan_buy else "最小100份起拟，当前无回补动作") if legacy else
                               "现有单笔量/建仓比例" if valid_buy else "最小100份起拟/建仓比例",
        "sell_quantity_source": (("现有单笔量，建仓后复评" if valid_sell else "建仓后网格草案，按100份起拟") if not held else
                                 "现有单笔量，受底仓约束" if valid_sell else "持仓约1/4取整，最低100份起拟"),
    }
    advice["grid_execution_status"] = "DO_NOT_ENABLE" if blockers else "PENDING_VERIFICATION"
    advice["grid_execution_note"] = (
        "暂不启用整单：" + "；".join(blockers) if blockers else
        "启用前：核实可用资金、可卖量、累计占用及底仓保护"
    )
    advice["strategy_guardrails"].append("平台双向联动；任一侧不满足执行条件时整单停用。部分卖出计划须另行执行，不能用0份或单侧暂停实现。")
    for side, raw, valid in (("买", raw_buy, valid_buy), ("卖", raw_sell, valid_sell)):
        if raw is not None and not valid:
            advice["reasons"].append(f"采集单笔{side}量{raw:g}与平台100份起、100份整数倍约束不符；需核对原单，不代表持仓不足或已停用。")
            advice["specific_notes"].append(f"采集单笔{side}量{raw:g}不符合100份整数倍约束，需核对原单。")
    return advice
