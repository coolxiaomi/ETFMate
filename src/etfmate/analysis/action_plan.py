"""Describe a conditional plan without presenting internal grid gates as live state."""
from __future__ import annotations

from typing import Any


def describe_action_plan(recommendation: dict[str, Any], grid: dict[str, Any]) -> dict[str, Any]:
    technical = recommendation.get("technical_assessment") or grid.get("technical_assessment") or {}
    held = (recommendation.get("quantity") or 0) > 0
    legacy = recommendation.get("strategy_role") == "LEGACY_EXIT"
    sell = grid.get("candidate_sell_quantity")
    buy_label = "回补" if legacy else "买入"
    buy_condition = technical.get("buy_condition") or "等待有效行情后复评。"
    notices = []
    if grid.get("current_enabled") is False:
        notices.append("采集时原网格已停用；本报告未修改设置。")
    if grid.get("current_max_position_quantity") is not None and not legacy and (
            grid["current_max_position_quantity"] - (recommendation.get("quantity") or 0) < 100):
        notices.append("当前最大仓余量不足100份，暂不追加。")

    if legacy and not held:
        stage, headline = "RETIRED", "结束已退出标的计划"
        buy_condition, sell_condition = "不再新增旧仓。", "无剩余持仓。"
    elif not grid.get("parameter_plan"):
        stage, headline = "WAIT_DATA", "等待有效行情，暂不拟定价格计划"
        sell_condition = "价格参数尚不可用。"
        notices.extend(grid.get("reasons") or [])
    elif not held:
        stage, headline = "INITIAL_ENTRY", "等待回落，分批建立底仓"
        sell_condition = "建仓后再评估分批卖出与双向网格。"
    else:
        stage = "LEGACY_MANAGEMENT" if legacy else "POSITION_MANAGEMENT"
        if sell:
            headline = "等待反弹，分批回收资金" if legacy else "保留底仓，反弹时分批卖出"
            sell_condition = "" if legacy else technical.get("sell_condition") or "等待反弹后复评。"
        else:
            headline = "保留底仓，等待后续波动"
            sell_condition = "保留底仓后可卖不足100份，暂不安排卖出。"
        if recommendation.get("candidate_liquidation_quantity"):
            headline = recommendation["action"]
        elif recommendation.get("position_action") == "WAIT_PAIR_BALANCE":
            headline = recommendation["action"]
        if legacy and not grid.get("conditional_buyback_quantity") and technical.get("buy_gate") != "WAIT_CONFIRMATION":
            buy_condition = "暂无回补数量；卖出成交后按实际回款和持仓复评。"

    return {"stage": stage, "headline": headline, "buy_label": buy_label,
            "buy_condition": buy_condition, "sell_condition": sell_condition,
            "notices": list(dict.fromkeys(notices))}
