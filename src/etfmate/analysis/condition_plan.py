"""Map decisions to verified Touker condition types, without submitting orders."""
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING

PRICE_GUIDE = "https://m.touker.com/brochure/brochureh5/homeConditionDetails.htm?id=26"
PULLBACK_GUIDE = "https://cdn01.touker.com/hbec/projects/qq/production/conditionH5/explainH5/down.html"


def build_follow_up_policy() -> dict:
    """Return review requirements, not platform settings or automatic order actions."""
    return {
        "contract": "condition_follow_up_v1", "execution_authorized": False,
        "partial_fill": {
            "status": "RECONCILE_ACTUAL_FILLS", "label": "部分成交",
            "cash_inventory_basis": "ACTUAL_FILLED_ONLY", "duplicate_new_order_allowed": False,
            "actions": [
                "按实际成交数量和金额核对自动同步账本中的现金、持仓、可卖量与剩余净投入；不得按委托总量预计成交。",
                "先核对剩余委托是否仍活跃及撤单回报，未确认结束前不按原计划总量重复新建条件。",
                "实际回款已经同步账本时不重复累加；未成交部分不计回款，不占用其预期回款安排买入。",
            ],
        },
        "rejected": {
            "status": "REVIEW_REJECTION_BEFORE_REPLAN", "label": "申报失败",
            "automatic_retry_allowed": False,
            "actions": [
                "先核对委托回报、证券代码、原单标识和失败原文，区分申报失败与撤单失败。",
                "资金不足核对现金和活跃买入委托；可卖不足核对结算可卖量和活跃卖出委托；参数错误核对平台字段与价格档位。未知原因保留待核验。",
                "原因及原委托终态明确后，刷新账户和报价再复评；不自动重试或直接重建同量条件。",
            ],
        },
        "unfilled": {
            "status": "VERIFY_ORDER_STATE_BEFORE_CHANGE", "label": "未成交或长期未触发",
            "automatic_timeout_cancel_allowed": False,
            "actions": [
                "先区分条件仍在监控、已触发报单和部分成交，核对活跃委托及撤单回报；暂停监控不代表撤单完成。",
                "报价、账户或参数变化时重新评估等待条件，不把历史「已申报」当作当前冻结或已自动撤单。",
                "没有已核实的时限和平台设置时，不承诺超时撤单、自动追价或固定成交期限。",
            ],
        },
        "replacement": {
            "status": "VERIFY_OLD_AND_NEW_ORDER_STATE", "label": "旧单替换",
            "zero_gap_guaranteed": False,
            "actions": [
                "按原条件标识核对同标的监控条件和已报委托，确认重叠范围。",
                "停用需要替换的原条件及重叠条件，防止再次触发；再核对已报委托的成交或撤单回报。",
                "原委托结果明确后，按实际现金和库存刷新计划；符合本批次条件时再配置替代单，避免重复报单。",
                "保存后核对新单代码、方向、数量、价格和实际监控状态；未确认生效前不声称已受新条件保护。",
                "记录替换结果；停旧单与启新单之间可能存在监控空窗，不承诺无空窗切换。",
            ],
        },
        "revalidation": {
            "status": "REVALIDATE_CHANGED_INPUTS", "label": "计划失效与复评",
            "triggers": ["QUOTE_CHANGED", "ACCOUNT_CHANGED", "PARAMETERS_CHANGED", "ORDER_STATE_CHANGED"],
            "actions": [
                "创建、修改或沿用条件前，若报价、现金、持仓、可卖量、净投入、原单状态或参数发生变化，刷新证据并重算本批次计划。",
                "成交价可能偏离触发价；有效期、超时撤单和滑点／价格偏差保护须核对平台实际支持及本单设置，不填写未经核实的时长或偏差值。",
            ],
        },
        "note": "以上为本地计划的复核要求，不代表平台已有自动控制功能，也不授权提交、撤销或重试真实委托。",
    }


def build_condition_plan(action: dict, grid: dict) -> dict:
    quantity = action.get("sell_quantity")
    reference = action.get("sell_reference_price")
    current = action.get("sell_status") in {"CURRENT_PARTIAL_REVIEW", "LIQUIDATION_REVIEW"}
    inventory = action.get("inventory") or {}
    result = {
        "channel": "CONDITION_ORDERS_ONLY", "operation": "WAIT",
        "condition_type": None, "quantity": None, "trigger_price": None,
        "trigger_relation": None, "order_price_type": None,
        "repeat_policy": "DO_NOT_RECREATE_BEFORE_REVIEW", "execution_authorized": False,
        "steps": [], "source_urls": [], "follow_up_policy": build_follow_up_policy(),
    }
    if not quantity or not reference:
        return result
    result["steps"] = [
        "先按原单标识核对同标的已报委托，再停用原双向网格及重叠卖出条件单；已触发报单的，等成交或撤单结果明确后再替换。",
        "同标的只保留本批次这一条退出计划；成交后不自动重建，先同步剩余持仓与本金再复评。",
        "保存后核对新单参数及实际监控状态；未确认生效前不声称已受新条件保护，替换过程不承诺无监控空窗。",
    ]
    if not inventory or inventory.get("sellable_quantity") is None:
        result.update(operation="WAIT_INVENTORY", steps=result["steps"] + ["本次可卖量尚不能推出，暂不生成可配置数量。"])
        return result
    if current:
        # ETF price tick is 0.001. Rounding an upward trigger down would execute early.
        trigger = float(Decimal(str(reference)).quantize(Decimal("0.001"), rounding=ROUND_CEILING))
        result.update(operation="REPLACE_WITH_PRICE_SELL", condition_type="价格条件单·卖出",
                      quantity=quantity, trigger_price=trigger, trigger_relation="达到或高于",
                      order_price_type="即时买一价", source_urls=[PRICE_GUIDE])
        if action.get("sell_status") == "LIQUIDATION_REVIEW":
            floor = action.get("liquidation_floor")
            if floor is None:
                result.update(operation="WAIT_LIQUIDATION_FLOOR", quantity=None)
                return result
            limit = max(trigger, float(Decimal(str(floor)).quantize(Decimal("0.001"), rounding=ROUND_CEILING)))
            result.update(trigger_price=max(trigger, limit), order_price_type=f"限价 ¥{limit:.3f}",
                          order_limit_price=limit)
        result["steps"].insert(1, "按当前参考价设置价格卖出，不附加下一格上涨要求；创建时若报价或持仓已变化，先刷新计划。")
    else:
        path, parameters = grid.get("price_plan") or {}, grid.get("parameter_plan") or {}
        initial, pullback = path.get("sell_trigger_price"), parameters.get("sell_pullback_pct")
        if initial and pullback:
            initial = float(Decimal(str(initial)).quantize(Decimal("0.001"), rounding=ROUND_CEILING))
            result.update(operation="REPLACE_WITH_PULLBACK_SELL", condition_type="回落卖出",
                          quantity=quantity, trigger_price=initial, trigger_relation="先达到或高于",
                          pullback_pct=-pullback, guaranteed_price_trigger=False,
                          order_price_type="即时买一价", source_urls=[PULLBACK_GUIDE])
            result["steps"].insert(1, "初始价格只负责开启监控，再按新条件单激活后的实际最高价计算累计回落；不继承旧单峰值，关闭保底价触发，避免绕过回落条件。")
        else:
            result.update(operation="WAIT_PRICE_DATA")
    return result
