"""Explicit strategy gaps and isolated sale scenarios shared by analysis and reports."""
from __future__ import annotations

from math import isfinite
from typing import Any


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        return None
    return float(value)


def build_quantity_basis(recommendation: dict, grid: dict, quantity: float | None,
                         sell_status: str) -> dict:
    held = _number(recommendation.get("quantity"))
    proposed = _number(quantity)
    raw = _number(grid.get("current_sell_quantity"))
    original_valid = raw is not None and raw >= 100 and raw % 100 == 0
    parameter_source = (grid.get("parameter_plan") or {}).get("sell_quantity_source", "")
    if not proposed or not held:
        source, label = "NO_SELL_PLAN", "本批次无卖出数量"
    elif sell_status == "LIQUIDATION_REVIEW":
        source, label = "VERIFIED_LIQUIDATION", "按已核验清仓条件拟定全部库存"
    elif original_valid or "现有单笔量" in parameter_source:
        source, label = "EXISTING_ORDER_QUANTITY", "沿用合法原单量，再受保留仓与可卖量约束"
    else:
        source, label = "HOLDING_QUARTER_FALLBACK", "原单量缺失或异常，按持仓约1/4取整起拟，再受库存约束"
    asset = _number(recommendation.get("account_total_asset"))
    value = _number(recommendation.get("market_value"))
    weight = value / asset * 100 if value is not None and asset and asset > 0 else None
    if weight is None and recommendation.get("position_pct_source") == "ths_account_total_asset":
        weight = _number(recommendation.get("position_pct"))
    return {
        "source": source, "label": label, "original_sell_quantity": raw,
        "holding_quantity": held, "proposed_sell_quantity": proposed,
        "reduction_pct": round(proposed / held * 100, 4) if held and held > 0 and proposed else None,
        "account_weight_pct": round(weight, 4) if weight is not None else None,
        "risk_optimized": False,
        "note": "份额来自既有数量规则，尚未按账户风险贡献、回款目标或收益回测优化。",
    }


def build_contingency_plan(recommendation: dict, action: dict) -> dict:
    held = (_number(recommendation.get("quantity")) or 0) > 0
    status = action["sell_status"]
    waiting = status in {"WAIT_REBOUND", "REVIEW_PATH"}
    cases = []
    if held and waiting:
        cases.append({"code": "ACTIVATION_NOT_REACHED", "trigger": "未到卖出启动价",
                      "action": "保留未触发状态；刷新完整日信号、当前报价和账户资金后复评，不假设反弹一定发生。"})
    if held:
        cases.extend([
            {"code": "CONTINUED_DECLINE", "trigger": "价格继续下跌",
             "action": "重评完整日趋势、账户风险与剩余库存；不因下跌自动回补，也不绕过最终清仓本金约束。"},
            {"code": "LONG_UNTRIGGERED", "trigger": "长期未触发",
             "action": "重新检查退出依据、原单有效状态和账户资金；复核期限尚未约定，不自动延期、改价或重建。"},
        ])
    else:
        cases.append({"code": "ENTRY_CONDITIONS_UNMET", "trigger": "建仓条件持续不满足",
                      "action": "刷新完整日信号与账户预算后复评；未确认可分配资金前保持等待，不自动建仓。"})
    technical = recommendation.get("technical_assessment") or {}
    hot = technical.get("status") == "OVERHEATED"
    return {
        "mode": "REASSESS_ONLY", "cases": cases, "review_deadline": None,
        "automatic_actions_authorized": False,
        "brief": ("未到启动价或继续下跌：刷新完整日信号与账户重评；长期未触发的复核期限尚未约定。" if held and waiting else
                  "报价变化或持续未成交：刷新行情、库存与账户重评；不自动追价或重建。" if held else
                  "条件持续不满足时重评信号与预算，保持等待。"),
        "signal_caveat": "过热只是本次部分卖出复评依据，不证明理想卖点或之后必跌。" if hot else None,
    }


def build_decision_review(recommendations: list[dict], grid_advices: list[dict],
                          account_summary: dict | None = None,
                          funding_plan: dict | None = None) -> dict:
    from etfmate.analysis.action_plan import describe_action_plan

    summary, funding = account_summary or {}, funding_plan or {}
    grids = {row["code"]: row for row in grid_advices}
    plans = {row["code"]: describe_action_plan(row, grids.get(row["code"], {})) for row in recommendations}
    total = _number(funding.get("total_asset", summary.get("total_asset")))
    value = _number(funding.get("market_value", summary.get("market_value")))
    cash = _number(funding.get("cash", summary.get("cash")))
    scenarios = []
    for row in recommendations:
        plan = plans[row["code"]]
        if plan["sell_status"] not in {"CURRENT_PARTIAL_REVIEW", "LIQUIDATION_REVIEW"}:
            continue
        quantity, price = _number(plan.get("sell_quantity")), _number(plan.get("sell_reference_price"))
        held, ledger_value = _number(row.get("quantity")), _number(row.get("market_value"))
        if (quantity is None or price is None or held is None
                or not 0 < quantity <= held or price <= 0):
            continue
        proceeds = quantity * price
        sold_value = quantity / held * ledger_value if ledger_value is not None and ledger_value >= 0 else None
        projected_value = max(0.0, value - sold_value) if value is not None and sold_value is not None and value >= sold_value else None
        projected_asset = total + proceeds - sold_value if total is not None and total > 0 and sold_value is not None else None
        scenarios.append({
            "code": row["code"], "quantity": quantity, "reference_price": price,
            "status": "ILLUSTRATION_NOT_EXECUTED", "estimated_proceeds": round(proceeds, 6),
            "valuation_basis": "LEDGER_VALUE_WITH_REFERENCE_SALE",
            "sold_ledger_value": round(sold_value, 6) if sold_value is not None else None,
            "projected_cash": round(cash + proceeds, 6) if cash is not None else None,
            "projected_market_value": round(projected_value, 6) if projected_value is not None else None,
            "projected_total_asset": round(projected_asset, 6) if projected_asset is not None else None,
            "projected_position_pct": round(projected_value / projected_asset * 100, 6)
            if projected_value is not None and projected_asset and projected_asset > 0 else None,
            "remaining_net_sell_to_threshold": round(max(0.0, projected_value - projected_asset * .8), 6)
            if projected_value is not None and projected_asset and projected_asset > 0 else None,
        })
    gaps = [
        ("ACCOUNT_RISK_LIMIT", "账户最大回撤与超限处置", "缺少可执行的风险限额与恢复规则。"),
        ("ROLE_BUDGETS", "四只目标的账户预算", "组内40/60不能决定全账户买入份额。"),
        ("CASH_BUFFER", "现金缓冲", "现有现金不等于已分配给目标组合的预算。"),
        ("PROCEEDS_ALLOCATION", "旧仓预留与回款用途", "尚未量化永久退出、旧仓周转与目标承接金额。"),
        ("EXIT_REVIEW_DEADLINE", "退出期限与长期未触发处置", "迁移完成时间无法保证；不编造自动止损或延期规则。"),
    ]
    return {
        "contract": "decision_review_v1",
        "partial_review_boundary": "以下策略缺口不阻断按现有规则复评部分卖出；它们不授权自动止损、扩大回补或越过最终清仓约束。",
        "position_threshold": {"pct": 80.0, "semantics": "NEW_BUY_GATE", "forced_reduction": False,
                               "drawdown_limit": False,
                               "note": "80%是新增买入门槛；达到后暂停新增投入，不代表强制立即降仓、最大回撤或本金保障。"},
        "unresolved_policies": [{"code": code, "label": label, "impact": impact} for code, label, impact in gaps],
        "liquidation_constraint": {
            "policy": "NO_LOSS_ON_LIQUIDATION", "can_delay_exit_indefinitely": True,
            "unverified_cost_codes": [row["code"] for row in recommendations if (row.get("quantity") or 0) > 0
                                      and not (row.get("sell_policy") or {}).get("cost_basis_verified")],
            "note": "最终清仓回本是既定硬约束；亏损部分卖出可能提高剩余回本线，旧仓退出可能长期无法完成。",
        },
        "quantity_policy": {"risk_optimized": False,
                            "note": "卖出量沿用合法原单或持仓比例起拟，受库存保护约束，尚未按当前账户风险优化。"},
        "cost_assumptions": {"fees_ignored": True, "source": "USER_AGREED", "returns_validated": False,
                             "note": "费用按既有约定忽略；参数和数量未经净收益、滑点及回撤回测验证。"},
        "migration": {"funding_priority": "LEGACY_RECOVERY_FIRST", "allocation_status": "UNSPECIFIED",
                      "note": "旧仓回本管理预留优先；回款未自动分配，目标仅用确认余款。四只目标目前是方向，不是已完成的资金迁移计划。"},
        "sell_scenarios": scenarios,
        "future_conditional_plan_count": sum(plan["sell_status"] in {"WAIT_REBOUND", "REVIEW_PATH"} and bool(plan.get("sell_quantity"))
                                             for plan in plans.values()),
        "scenario_assumptions": "各行独立假设本笔按参考价全部成交，剩余持仓保持账本估值且忽略费用；卖出份额按原账面价值扣除，价差计入总资产。不相加、不预支回款，未来反弹计划不计入。",
    }
