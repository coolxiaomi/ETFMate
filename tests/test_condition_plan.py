from etfmate.analysis.condition_plan import build_condition_plan
from etfmate.analysis.action_plan import describe_action_plan
from etfmate.analysis.grid_advisor import advise_grid
from etfmate.analysis.recommendation import recommend
from test_account_strategy import holding, market


def test_current_partial_exit_does_not_require_another_grid_rise():
    a = {"sell_status":"CURRENT_PARTIAL_REVIEW", "sell_quantity":1000,
         "sell_reference_price":1.912, "inventory":{"sellable_quantity":2100}}
    p = build_condition_plan(a, {"price_plan":{"sell_trigger_price":1.94}})
    assert p["condition_type"] == "价格条件单·卖出"
    assert p["trigger_price"] == 1.912 and p["quantity"] == 1000
    assert "pullback_pct" not in p and not p["execution_authorized"]


def test_waiting_sell_maps_activation_and_actual_peak_without_double_pullback():
    a = {"sell_status":"WAIT_REBOUND", "sell_quantity":500,
         "sell_reference_price":1.9303, "inventory":{"sellable_quantity":2000}}
    p = build_condition_plan(a, {"price_plan":{"sell_trigger_price":1.934567},
                                "parameter_plan":{"sell_pullback_pct":.22}})
    assert p["trigger_price"] == 1.935
    assert p["pullback_pct"] == -.22 and p["guaranteed_price_trigger"] is False


def test_unknown_inventory_does_not_gain_configuration_quantity():
    p = build_condition_plan({"sell_quantity":500, "sell_reference_price":1.2}, {})
    assert p["quantity"] is None and p["operation"] == "WAIT_INVENTORY"


def test_t1_intraday_purchase_limits_partial_sell_and_liquidation_label():
    p = holding("159687", quantity=1000)
    p.cost_basis_verified, p.net_invested_amount = True, 500
    m = market(p.code)
    rec = recommend(p, None, m, [p])
    inventory = {"sellable_quantity":200, "settlement":"T1", "note":"今日买入800"}
    g = advise_grid(None, m, p, rec["rule_decision"], inventory=inventory)
    a = describe_action_plan(rec, g)
    assert g["candidate_sell_quantity"] <= 200
    assert a["sell_status"] != "LIQUIDATION_REVIEW"
    assert a["sell_quantity"] <= 200


def test_no_sellable_inventory_never_claims_reserve_is_the_only_reason():
    p = holding("510500")
    m = market(p.code)
    rec = recommend(p, None, m, [p])
    g = advise_grid(None, m, p, rec["rule_decision"], inventory={"sellable_quantity":0,"note":"当日买入尚不可卖","settlement":"T1"})
    a = describe_action_plan(rec,g)
    assert a["sell_quantity"] is None and "当日买入" in a["sell_condition"]


def test_final_exit_never_uses_an_unbounded_live_bid_below_principal_floor():
    p = build_condition_plan({"sell_status":"LIQUIDATION_REVIEW", "sell_quantity":1000,
        "sell_reference_price":1.912, "liquidation_floor":1.9052,
        "inventory":{"sellable_quantity":1000}}, {})
    assert p["order_limit_price"] == 1.912
    assert p["order_price_type"] != "即时买一价"


def test_recovered_principal_does_not_create_a_submitted_price_near_zero():
    p = build_condition_plan({"sell_status":"LIQUIDATION_REVIEW", "sell_quantity":1000,
        "sell_reference_price":1.912, "liquidation_floor":0,
        "inventory":{"sellable_quantity":1000}}, {})
    assert p["order_limit_price"] == 1.912 and p["trigger_price"] == 1.912


def test_final_exit_and_buyback_are_mutually_exclusive():
    from dataclasses import replace
    p=holding("159781",quantity=2000)
    p.cost_basis_verified,p.net_invested_amount=True,1800
    p.position_pct=10
    m=replace(market(p.code),last_price=1.1)
    rec=recommend(p,None,m,[p])
    g=advise_grid(None,m,p,rec["rule_decision"],inventory={"sellable_quantity":2000,"settlement":"T1"})
    a=describe_action_plan(rec,g)
    assert a["sell_status"] == "LIQUIDATION_REVIEW"
    assert a["buy_status"] == "RETIRED" and a["buy_quantity"] is None
    assert g["conditional_buyback_quantity"] is None and g["final_exit_plan"]
    assert "买入" in rec["rule_decision"]["blocked_actions"]


def test_tick_rounding_preserves_exact_boundary_and_does_not_activate_early():
    from etfmate.analysis.price_ticks import grid_trigger_price
    assert grid_trigger_price(1,3,"sell") == 1.03
    assert grid_trigger_price(1.656,2.51,"sell") == 1.698
    assert grid_trigger_price(1.656,2.51,"buy") == 1.614


def test_follow_up_policy_preserves_partial_fill_and_failed_order_boundaries():
    p = build_condition_plan({"sell_status": "CURRENT_PARTIAL_REVIEW", "sell_quantity": 1000,
                              "sell_reference_price": 1.912, "inventory": {"sellable_quantity": 2100}}, {})
    policy = p["follow_up_policy"]
    assert policy["contract"] == "condition_follow_up_v1" and policy["execution_authorized"] is False
    assert policy["partial_fill"]["cash_inventory_basis"] == "ACTUAL_FILLED_ONLY"
    assert policy["partial_fill"]["duplicate_new_order_allowed"] is False
    assert policy["rejected"]["automatic_retry_allowed"] is False
    assert policy["unfilled"]["automatic_timeout_cancel_allowed"] is False
    assert "撤单失败" in "".join(policy["rejected"]["actions"])
    assert "实际成交数量和金额" in "".join(policy["partial_fill"]["actions"])
    assert "不重复累加" in "".join(policy["partial_fill"]["actions"])


def test_replacement_requires_old_order_outcome_and_new_monitor_verification():
    p = build_condition_plan({"sell_status": "WAIT_REBOUND", "sell_quantity": 500,
                              "sell_reference_price": 1.93, "inventory": {"sellable_quantity": 2000}},
                             {"price_plan": {"sell_trigger_price": 1.94}, "parameter_plan": {"sell_pullback_pct": .2}})
    replacement = p["follow_up_policy"]["replacement"]
    assert replacement["zero_gap_guaranteed"] is False
    steps = replacement["actions"]
    assert "已报委托" in steps[0]
    assert "成交或撤单回报" in steps[1]
    assert "原委托结果明确后" in steps[2]
    assert "实际监控状态" in steps[3]
    assert "空窗" in steps[4]
    assert "实际监控状态" in p["steps"][-1]


def test_waiting_plan_keeps_follow_up_requirements_without_inventing_live_settings():
    p = build_condition_plan({}, {})
    policy = p["follow_up_policy"]
    assert p["operation"] == "WAIT" and p["quantity"] is None
    assert policy["revalidation"]["triggers"] == [
        "QUOTE_CHANGED", "ACCOUNT_CHANGED", "PARAMETERS_CHANGED", "ORDER_STATE_CHANGED"]
    assert "时长或偏差值" in "".join(policy["revalidation"]["actions"])
    assert not any(key in p for key in ("expires_at", "timeout_seconds", "slippage_limit_pct"))
    policy["replacement"]["actions"].clear()
    assert build_condition_plan({}, {})["follow_up_policy"]["replacement"]["actions"]
