from dataclasses import replace

from etfmate.analysis.action_plan import describe_action_plan
from etfmate.analysis.execution_review import build_execution_review
from etfmate.analysis.grid_advisor import advise_grid
from etfmate.analysis.recommendation import recommend
from etfmate.report.daily_report import render_html
from etfmate.storage.models import GridConfig
from test_account_strategy import holding, market


def review_case(code="159687", **changes):
    p = holding(code)
    p.cost_price = 1.0
    m = replace(market(code), **changes)
    rec = recommend(p, None, m, [p])
    grid = advise_grid(None, m, p, rec["rule_decision"])
    return p, rec, grid


def test_recovered_legacy_price_is_a_current_exit_review_not_next_grid_target():
    p, rec, grid = review_case()
    a = describe_action_plan(rec, grid)
    assert a["sell_status"] == "CURRENT_PARTIAL_REVIEW"
    assert a["sell_reference_price"] == rec["last_price"]
    assert a["sell_reference_price"] < grid["first_sell_reference_price"]
    assert 0 < a["sell_quantity"] < p.quantity
    assert a["execution_authorized"] is False
    html = render_html("TEST", [rec], [grid], {})
    assert "当前优先评估分批退出" in html
    assert "等待反弹，分批回收资金" not in html
    assert html.index("当前价评估") < html.index("后续网格参数草案")


def test_target_above_proposed_sell_trigger_requires_path_review():
    p = holding()
    m = market(p.code)
    config = GridConfig(p.code, p.name, True, base_price=m.last_price / 1.035,
                        buy_quantity=100, sell_quantity=100)
    rec = recommend(p, config, m, [p])
    grid = advise_grid(config, m, p, rec["rule_decision"])
    a = describe_action_plan(rec, grid)
    assert a["sell_status"] == "REVIEW_PATH"
    assert "单次报价不能" in a["sell_condition"]
    assert "等待反弹" not in a["headline"]
    assert not a["execution_authorized"]


def test_blocked_unheld_target_exposes_no_current_buy_quantity():
    p = holding("159781")
    p.position_pct = 90
    m = market("159259")
    rec = recommend(None, None, m, [p])
    grid = advise_grid(None, m, None, rec["rule_decision"])
    a = describe_action_plan(rec, grid)
    assert a["stage"] == "INITIAL_ENTRY" and a["buy_status"] == "BLOCKED"
    assert a["buy_quantity"] is None and a["sell_quantity"] is None
    assert "暂停建仓" in a["headline"]
    assert grid["parameter_plan"]["buy_quantity"] >= 100
    html = render_html("TEST", [rec], [grid], {})
    assert html.index("本批次暂停买入") < html.index("后续网格参数草案")


def test_active_non_grid_buy_orders_are_included_in_conflict_review():
    p = holding("159781")
    p.position_pct = 90
    recs, grids = [], []
    for code in (p.code, "159259", "159263"):
        m = market(code)
        pos = p if code == p.code else None
        rec = recommend(pos, None, m, [p])
        recs.append(rec)
        grids.append(advise_grid(None, m, pos, rec["rule_decision"]))
    conditions = [{"code": code, "condition_type": "grid" if code == p.code else "buy_only", "enabled": True}
                  for code in (p.code, "159259", "159263")]
    # Multiple real orders of the same code must not be deduplicated away.
    conditions.append(dict(conditions[-1]))
    review = build_execution_review(recs, grids, conditions)
    assert review["active_condition_count"] == 4
    assert review["active_non_grid_count"] == 3
    assert len(review["live_order_conflicts"]) == 4
    assert review["conditions_complete"] and not review["execution_ready"]
    conditions[-1]["enabled"] = False
    assert len(build_execution_review(recs, grids, conditions)["live_order_conflicts"]) == 3


def test_report_orders_current_exits_before_large_waiting_loss_positions():
    _, recovered, first = review_case()
    p = holding("159781")
    p.cost_price, p.market_value = 3, 50000
    m = market(p.code)
    waiting = recommend(p, None, m, [p])
    second = advise_grid(None, m, p, waiting["rule_decision"])
    html = render_html("TEST", [waiting, recovered], [second, first], {})
    assert html.index('<span class="code">159687') < html.index('<span class="code">159781')


def test_small_inventory_does_not_gain_a_current_sell_from_profitable_price():
    p = holding("159687")
    p.quantity = 100
    m = market(p.code)
    rec = recommend(p, None, m, [p])
    grid = advise_grid(None, m, p, rec["rule_decision"])
    a = describe_action_plan(rec, grid)
    assert a["sell_quantity"] is None and a["sell_reference_price"] is None
    assert "不足100" in a["sell_condition"]


def test_verified_liquidation_is_independent_of_atr_settings():
    p = holding("159687", quantity=100)
    p.cost_basis_verified, p.net_invested_amount = True, 100
    m = replace(market(p.code), atr14_pct=None)
    rec = recommend(p, None, m, [p])
    grid = advise_grid(None, m, p, rec["rule_decision"])
    a = describe_action_plan(rec, grid)
    assert not grid["parameter_plan"]
    assert a["sell_status"] == "LIQUIDATION_REVIEW" and a["sell_quantity"] == 100
    assert a["sell_reference_price"] == m.last_price and not a["execution_authorized"]


def test_complete_day_conditions_are_not_misrepresented_as_live_price_thresholds():
    p = holding("510500")
    m = replace(market(p.code), last_price=1.2, signal_close=1.0, signal_date="2026-09-07",
                signal_is_complete=True, signal_volume_basis="completed_daily",
                ma5=1.05, ma10=1.10, ma20=1.15, ma5_slope_3=-.01)
    rec = recommend(p, None, m, [p])
    grid = advise_grid(None, m, p, rec["rule_decision"])
    plan = describe_action_plan(rec, grid)
    assert m.last_price > m.ma5 > m.signal_close
    assert "下一个完整交易日确认（现有样本 2026-09-07）" in plan["buy_condition"]
    assert "站回MA5" in plan["buy_condition"]


def test_account_execution_review_keeps_failure_evidence_after_removing_full_history():
    submitted = {
        "contract": "touker_submitted_audit_v1", "captured_at": "2026-09-08T14:10:00+08:00",
        "selected_tab": "已委托", "selection_verified": True, "complete": False,
        "records": [{"code": "159687", "date": "2026-07-14", "status": "资金不足", "raw_text": "资金不足"}],
    }
    review = build_execution_review([], [], conditions=[], submitted_snapshot=submitted)
    assert "records" not in review["submitted_orders"]
    summary = review["submitted_orders"]["failure_summary"]
    assert summary["observed_rejected_count"] == 1 and summary["complete"] is False
    assert summary["categories"][0]["examples"][0]["raw_text"] == "资金不足"
    assert review["follow_up_policy"]["contract"] == "condition_follow_up_v1"
    assert review["follow_up_policy"]["rejected"]["automatic_retry_allowed"] is False


def test_sell_only_and_unknown_conditions_do_not_become_buy_conflicts():
    _, rec, grid = review_case()
    conditions = [
        {"code": rec["code"], "condition_type": "sell_only", "enabled": True, "condition_identity": "sell-1"},
        {"code": "510500", "condition_type": "custom", "enabled": True, "condition_identity": "custom-2"},
    ]
    review = build_execution_review([rec], [grid], conditions)
    assert review["live_order_conflicts"] == []
    assert {row["reason_code"] for row in review["condition_review_items"]} == {
        "SELL_OVERLAP_REVIEW", "UNKNOWN_CONDITION_TYPE"}
    assert {row["condition_identity"] for row in review["condition_review_items"]} == {"sell-1", "custom-2"}
    assert not any("先停用" in task for task in review["tasks"])
    assert "确认重叠后" in review["condition_review_items"][0]["reason"]


def test_existing_sell_without_new_candidate_does_not_gain_stop_instruction():
    review = build_execution_review([], [], conditions=[
        {"code": "159687", "condition_type": "sell_only", "enabled": True},
    ])
    assert review["live_order_conflicts"] == review["condition_review_items"] == []
    assert not any("先停用" in task for task in review["tasks"])


def test_only_actual_buy_conflicts_enter_stop_count(monkeypatch):
    import etfmate.analysis.execution_review as module
    monkeypatch.setattr(module, "describe_action_plan", lambda rec, grid: {
        "buy_status": "BLOCKED", "sell_status": "WAIT_REBOUND", "sell_quantity": 100,
    })
    conditions = [
        {"code": "159687", "condition_type": "grid", "enabled": True},
        {"code": "159687", "condition_type": "buy_only", "enabled": True},
        {"code": "159687", "condition_type": "sell_only", "enabled": True},
        {"code": "159687", "condition_type": "custom", "enabled": True},
    ]
    review = build_execution_review([{"code": "159687"}], [], conditions)
    assert len(review["live_order_conflicts"]) == 2
    assert all(row["reason_code"] == "BUY_RESTRICTION_CONFLICT" for row in review["live_order_conflicts"])
    assert len(review["condition_review_items"]) == 2
    assert "先停用 2 条" in review["tasks"][0]


def test_new_grid_draft_limit_does_not_prove_original_grid_is_buy_conflict(monkeypatch):
    import etfmate.analysis.execution_review as module
    monkeypatch.setattr(module, "describe_action_plan", lambda rec, grid: {
        "buy_status": "WAIT_DIP", "sell_status": "WAIT_REBOUND", "sell_quantity": 100,
    })
    review = build_execution_review([{"code": "159687"}], [
        {"code": "159687", "grid_execution_status": "DO_NOT_ENABLE"},
    ], conditions=[{"code": "159687", "condition_type": "grid", "enabled": True}])
    assert review["live_order_conflicts"] == []
    assert review["condition_review_items"][0]["reason_code"] == "GRID_PLAN_REVIEW"
    assert not any("先停用" in task for task in review["tasks"])
