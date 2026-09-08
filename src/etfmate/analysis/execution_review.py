"""Account-level operational gaps and live-order conflicts, without inventing funds."""
from __future__ import annotations

from typing import Any

from etfmate.analysis.action_plan import describe_action_plan
from etfmate.analysis.condition_plan import build_follow_up_policy
from etfmate.analysis.submitted_order_review import build_submitted_order_review


def build_execution_review(recommendations: list[dict], grids: list[dict],
                           conditions: list[dict] | None = None,
                           funding: dict | None = None,
                           submitted_snapshot: dict | None = None) -> dict[str, Any]:
    by_code = {row["code"]: row for row in recommendations}
    by_grid = {row["code"]: row for row in grids}
    plans = {code: describe_action_plan(row, by_grid.get(code, {})) for code, row in by_code.items()}
    current = [code for code, plan in plans.items()
               if plan["sell_status"] in {"CURRENT_PARTIAL_REVIEW", "LIQUIDATION_REVIEW"}]
    reached = [code for code, plan in plans.items() if plan["sell_status"] == "REVIEW_PATH"]
    # Fallback is for rendering callers without raw conditions; it never claims completeness.
    observed = conditions if conditions is not None else [
        {"code": row["code"], "condition_type": "grid", "enabled": row.get("current_enabled")}
        for row in grids if row.get("current_enabled") is not None
    ]
    active = [row for row in observed if row.get("enabled") is True]
    conflicts = []
    review_items = []
    for row in active:
        code, kind = str(row.get("code") or ""), row.get("condition_type")
        plan, g = plans.get(code), by_grid.get(code, {})
        item = {"code": code, "type": {"grid": "双向网格", "buy_only": "分批建仓", "sell_only": "卖出条件"}.get(kind, str(kind or "未知类型")),
                "status": "采集时监控中", "condition_identity": row.get("condition_identity")}
        if kind in {"grid", "buy_only"} and plan and plan["buy_status"] in {"BLOCKED", "RETIRED", "WAIT_DATA"}:
            conflicts.append({**item, "reason_code": "BUY_RESTRICTION_CONFLICT",
                              "reason": "仍监控买入，与本批次暂停新增投入的判断不一致"})
        elif kind == "grid" and g.get("grid_execution_status") == "DO_NOT_ENABLE":
            review_items.append({**item, "reason_code": "GRID_PLAN_REVIEW",
                                 "reason": "本次网格草案不具备启用条件；先核对原单实际参数和限制，不能据草案状态直接认定原单必须停用"})
        elif kind in {"grid", "buy_only"} and plan is None:
            review_items.append({**item, "reason_code": "MISSING_DECISION_REVIEW",
                                 "reason": "本批次缺少同代码动作判断，先核对原单方向、参数及资金或库存条件"})
        if kind == "sell_only" and plan and plan.get("sell_quantity"):
            review_items.append({**item, "reason_code": "SELL_OVERLAP_REVIEW",
                                 "reason": "同代码已有卖出条件，本批次也有卖出候选；先核对是否沿用同一原单、出售预算及已报委托，确认重叠后再处理替换"})
        elif kind not in {"grid", "buy_only", "sell_only"}:
            review_items.append({**item, "reason_code": "UNKNOWN_CONDITION_TYPE",
                                 "reason": "条件类型及买卖方向未明确，先核对原单和资金或库存影响；不能仅因未纳入网格决策就要求停用"})
    tasks = []
    if conflicts:
        tasks.append(f"先停用 {len(conflicts)} 条与本批次买入限制冲突的条件单；双向网格按整单处理，再配置本批次卖出计划。")
    if current:
        tasks.append("当前优先复评分批退出：" + "、".join(current) + "；价格和份额见对应卡片。")
    if reached:
        tasks.append("已跨本次草案上涨阈值：" + "、".join(reached) + "；核对实际峰值回落，不能据单次报价认定成交。")
    if review_items:
        tasks.append(f"另有 {len(review_items)} 条监控条件待核对，按下方原因确认类型或重叠关系；不计入买入冲突停用数量。")
    if len(tasks) < 3:
        tasks.append("其余持仓按各自价格条件等待；买入与回补须先满足资金、风险和库存条件。")
    if len(tasks) < 3:
        tasks.append("成交后更新持仓和剩余净投入；回款确认可用后再安排目标组合。")
    submitted = build_submitted_order_review(submitted_snapshot)
    # Raw terminal history stays in the fingerprint-bound source; review focuses on
    # status counts and exceptional orders instead of repeating every filled trade.
    submitted.pop("records", None)
    if submitted["today_open_orders"]:
        tasks.insert(0, "先处理本次已观察到的当日未完成委托，再调整同标的条件；已申报不等于成交或回款。")
    return {
        "level": "CONDITIONAL_DECISION_SUPPORT", "execution_ready": False,
        "label": "条件单操作计划 · 现金与可卖量按账户事实计算",
        "current_exit_codes": current, "threshold_review_codes": reached,
        "active_condition_count": len(active), "conditions_complete": conditions is not None,
        "active_non_grid_count": sum(row.get("condition_type") != "grid" for row in active),
        "live_order_conflicts": conflicts, "condition_review_items": review_items, "tasks": tasks[:3],
        "funding": funding or {},
        "submitted_orders": submitted,
        "follow_up_policy": build_follow_up_policy(),
        "boundary": "已确认：资金不追加也不转出，无额外手动委托，条件单成交自动同步账本。现金按账本余额、可卖量按交易制度与当日成交计算；监控中条件单不当作冻结委托。调整前先停用冲突原单，已触发报单须等成交或撤单结果，防止重复占用。",
    }
