"""One decision narrative for the report and AI, separate from settings drafts."""
from __future__ import annotations

from typing import Any


def describe_action_plan(recommendation: dict[str, Any], grid: dict[str, Any]) -> dict[str, Any]:
    rule = recommendation.get("rule_decision") or {}
    technical = recommendation.get("technical_assessment") or grid.get("technical_assessment") or {}
    held = (recommendation.get("quantity") or 0) > 0
    legacy = recommendation.get("strategy_role") == "LEGACY_EXIT"
    path = grid.get("price_plan") or {}
    partial = grid.get("partial_sell_plan") or {}
    sell = grid.get("candidate_sell_quantity")
    candidate_buy = grid.get("conditional_buyback_quantity") if legacy else grid.get("candidate_buy_quantity")
    buy_label = "回补" if legacy else "买入"
    blocked = bool(set(rule.get("blocked_actions") or []) & {"全部", "买入", "加仓"})
    blocked = blocked or technical.get("buy_gate") == "WAIT_CONFIRMATION" or grid.get("buy_execution_status") == "DISABLED"
    buy_status = "BLOCKED" if blocked else "CONDITIONAL"
    buy_condition = technical.get("buy_condition") or "等待有效行情后复评。"
    if blocked:
        buy_condition = f"本批次暂停{buy_label}。" + buy_condition
    elif legacy:
        buy_condition = (f"先卖后买：等待真实卖出回款，回补上限 {candidate_buy:g} 份；按实际回款和持仓重算。" + buy_condition
                         if candidate_buy else "暂无回补数量；卖出成交后按实际回款和持仓复评。")
    elif candidate_buy:
        buy_condition += "达到价格条件后，还需核实可用现金、预算与在途买单占用。"
    else:
        buy_status = "NO_QUANTITY"
        buy_condition = "当前没有买入数量建议；复核持仓上限和资金后重算。" + buy_condition
    buy_trigger = path.get("buy_trigger_price")
    if not blocked and candidate_buy and buy_trigger is not None:
        buy_condition += (f"价格先到 ¥{buy_trigger:.3f} 或以下，再从实际低点反弹 "
                          f"{grid['parameter_plan']['buy_rebound_pct']:.2f}%；反弹路径尚未核实。")

    notices: list[str] = []
    if grid.get("current_enabled") is False:
        notices.append("采集时原网格已停用；本报告未修改设置。")
    if grid.get("current_max_position_quantity") is not None and not legacy and (
            grid["current_max_position_quantity"] - (recommendation.get("quantity") or 0) < 100):
        notices.append("当前最大仓余量不足100份，暂不追加。")
    stage = "LEGACY_MANAGEMENT" if legacy else "POSITION_MANAGEMENT"
    sell_status, sell_price, sell_quantity = "NO_INVENTORY", None, None
    if legacy and not held:
        stage, headline = "RETIRED", "结束已退出标的计划"
        buy_condition, sell_condition = "不再新增旧仓。", "无剩余持仓。"
        buy_status = "RETIRED"
    elif not grid.get("parameter_plan"):
        stage, headline = "WAIT_DATA", "等待有效行情，暂不拟定价格计划"
        buy_status, sell_status = "WAIT_DATA", "WAIT_DATA"
        buy_condition, sell_condition = "价格参数尚不可用，暂不买入或回补。", "价格参数尚不可用。"
        notices.extend(grid.get("reasons") or [])
    elif not held:
        stage = "INITIAL_ENTRY"
        headline = "暂停建仓，先解除买入限制" if blocked else "等待回落，分批建立底仓"
        sell_condition = "建仓后再评估分批卖出与双向网格。"
    elif sell:
        sell_quantity = sell
        sell_price = partial.get("reference_price") or grid.get("first_sell_reference_price")
        sell_status = partial.get("status") or "WAIT_REBOUND"
        if sell_status == "CURRENT_PARTIAL_REVIEW":
            headline = "当前优先评估分批退出" if legacy else "当前评估部分卖出，保留底仓"
            recovered = (grid.get("legacy_exit_assessment") or {}).get("page_cost_recovered")
            hot = technical.get("status") == "OVERHEATED" or rule.get("trend_overheat_level") in {"OVERHEATED", "SEVERE_OVERHEATED"}
            evidence = "现价已到页面成本参考，且完整日技术位置偏热" if recovered and hot else "现价已到页面成本参考" if recovered else "完整日技术位置偏热"
            sell_condition = evidence + ("；优先评估部分退出，全部清仓另核本金。" if legacy else "；评估部分卖出并保留底仓。")
        elif path.get("sell_path_status") == "TRIGGER_ZONE_PATH_UNVERIFIED":
            headline, sell_status = "已跨草案上涨阈值，核对回落条件", "REVIEW_PATH"
            sell_condition = "现价已达到本次参数草案的上涨阈值；核对实际峰值及回落幅度，单次报价不能证明确认条件已完成。"
        else:
            headline = "等待反弹，分批回收资金" if legacy else "保留底仓，反弹时分批卖出"
            sell_condition = technical.get("sell_condition") or "等待反弹后复评。"
        if sell_status in {"WAIT_REBOUND", "REVIEW_PATH"} and path.get("sell_trigger_price") is not None:
            sell_condition += (f"本次草案上涨阈值 ¥{path['sell_trigger_price']:.3f}，"
                               f"达到后从实际高点回落 {grid['parameter_plan']['sell_pullback_pct']:.2f}%。")
        sell_condition += "调整条件单前先停用同标的原网格；触发后以实际成交更新剩余持仓。"
    else:
        headline = "保留底仓，等待后续波动"
        sell_condition = "保留底仓后可卖不足100份，暂不安排卖出。"
        if grid.get("inventory") and grid["inventory"].get("sellable_quantity") in (None, 0):
            headline = "等待可卖库存满足条件"
            sell_condition = grid["inventory"].get("note") or "当前无可卖份额。"

    liquidation = recommendation.get("candidate_liquidation_quantity")
    inventory = grid.get("inventory") or {}
    liquidation_inventory_ok = not inventory or (inventory.get("sellable_quantity") is not None and inventory["sellable_quantity"] >= (liquidation or 0))
    if held and liquidation and liquidation_inventory_ok and (recommendation.get("sell_policy") or {}).get("sell_allowed") and "全部" not in (rule.get("blocked_actions") or []):
        stage = "LEGACY_MANAGEMENT" if legacy else "POSITION_MANAGEMENT"
        headline, sell_status = "回本清仓条件已到，优先核验退出", "LIQUIDATION_REVIEW"
        sell_quantity, sell_price = liquidation, recommendation.get("last_price")
        sell_condition = "参考价满足已核验的清仓回本线；按实际可卖量、有效限价及在途委托核对后再决定全部退出。"
        buy_status, blocked, candidate_buy = "RETIRED", True, None
        buy_condition = "本轮最终退出不再回补；实际清仓回款留在账户，按目标组合资金计划重新分配。"
    elif recommendation.get("position_action") == "WAIT_PAIR_BALANCE" and stage == "POSITION_MANAGEMENT":
        headline = recommendation["action"]
    if sell_status in {"WAIT_DATA", "NO_INVENTORY", "NO_PARTIAL_INVENTORY"}:
        sell_quantity, sell_price = None, None

    invalidation = ("任一笔成交、条件单参数或资金变化后重算；价格回撤不等于清仓条件仍满足。" if legacy else
                    "达到价格阈值只进入复评；持仓、可用资金或量价条件变化后重算。")
    if inventory.get("sellable_quantity") is not None and sell_quantity:
        sell_quantity = min(sell_quantity, inventory["sellable_quantity"])
    result = {
        "contract": "actionable_review_v1", "stage": stage, "headline": headline,
        "buy_label": buy_label, "buy_status": buy_status, "buy_condition": buy_condition,
        "buy_quantity": None if blocked else candidate_buy,
        "sell_status": sell_status, "sell_condition": sell_condition,
        "sell_quantity": sell_quantity, "sell_reference_price": sell_price,
        "projected_remaining_quantity": (partial.get("sell_policy") or {}).get("projected_remaining_quantity") if sell_quantity and sell_status != "LIQUIDATION_REVIEW" else None,
        "projected_liquidation_floor": (partial.get("sell_policy") or {}).get("projected_liquidation_floor") if sell_quantity and sell_status != "LIQUIDATION_REVIEW" else None,
        "sell_reference_basis": "当前价评估" if sell_status in {"CURRENT_PARTIAL_REVIEW", "LIQUIDATION_REVIEW"} else "路径确认示例",
        "execution_authorized": False, "invalidation": invalidation,
        "inventory": inventory,
        "liquidation_floor": (recommendation.get("sell_policy") or {}).get("liquidation_floor"),
        "execution_channel": "CONDITION_ORDERS_ONLY",
        "notices": list(dict.fromkeys(notices)),
    }
    from etfmate.analysis.condition_plan import build_condition_plan
    from etfmate.analysis.decision_review import build_quantity_basis, build_contingency_plan
    result["condition_plan"] = build_condition_plan(result, grid)
    result["quantity_basis"] = build_quantity_basis(recommendation, grid, sell_quantity, sell_status)
    result["contingency_plan"] = build_contingency_plan(recommendation, result)
    return result
