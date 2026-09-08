from copy import deepcopy

import pytest

from etfmate.analysis.action_plan import describe_action_plan
from etfmate.analysis.decision_review import build_decision_review, build_quantity_basis
from etfmate.report.daily_report import render_html


def sale(code="159687", quantity=1000, held=2100, price=1.912, ledger_value=4015.2,
         status="CURRENT_PARTIAL_REVIEW"):
    rec = {
        "code": code, "name": "测试ETF", "quantity": held, "last_price": price,
        "market_value": ledger_value, "account_total_asset": 69555.46,
        "position_pct_source": "ths_account_total_asset", "strategy_role": "LEGACY_EXIT",
        "rule_decision": {}, "technical_assessment": {"status": "OVERHEATED"},
        "sell_policy": {"status": "PENDING_COST_BASIS", "sell_allowed": False,
                        "cost_basis_verified": False},
    }
    grid = {
        "code": code, "current_sell_quantity": quantity, "candidate_sell_quantity": quantity,
        "candidate_buy_quantity": None, "buy_execution_status": "DISABLED",
        "parameter_plan": {"sell_quantity_source": "现有单笔量，受底仓约束", "buy_quantity_source": "当前无回补",
                           "buy_rebound_pct": .2, "sell_pullback_pct": .2},
        "price_plan": {"sell_trigger_price": 2.0},
        "partial_sell_plan": {"status": status, "reference_price": price,
                              "sell_policy": {"projected_remaining_quantity": held - quantity}},
        "inventory": {"sellable_quantity": held, "settlement": "T0", "today_buy_quantity": 0},
    }
    return rec, grid


def funding():
    return {"cash": 6366.66, "total_asset": 69555.46, "market_value": 63188.8,
            "required_net_sell_to_cap": 7544.432, "buy_capacity_under_cap": 0}


def test_current_sale_scenario_reveals_remaining_exposure_without_claiming_execution():
    rec, grid = sale()
    review = build_decision_review([rec], [grid], funding_plan=funding())
    scenario = review["sell_scenarios"][0]
    assert scenario["estimated_proceeds"] == 1912
    assert scenario["projected_cash"] == 8278.66
    assert scenario["projected_position_pct"] == pytest.approx(61276.8 / 69555.46 * 100)
    assert scenario["remaining_net_sell_to_threshold"] == 5632.432
    assert scenario["status"] == "ILLUSTRATION_NOT_EXECUTED"
    assert review["position_threshold"]["semantics"] == "NEW_BUY_GATE"
    assert not review["position_threshold"]["forced_reduction"]
    assert not review["position_threshold"]["drawdown_limit"]


def test_scenario_uses_ledger_valuation_consistently_when_quote_has_changed():
    rec, grid = sale(ledger_value=4200)
    scenario = build_decision_review([rec], [grid], funding_plan=funding())["sell_scenarios"][0]
    assert scenario["sold_ledger_value"] == 2000
    assert scenario["projected_market_value"] == 61188.8
    assert scenario["projected_total_asset"] == 69467.46
    assert scenario["projected_total_asset"] == pytest.approx(scenario["projected_market_value"] + scenario["projected_cash"])
    assert scenario["projected_position_pct"] == pytest.approx(61188.8 / 69467.46 * 100)
    assert scenario["valuation_basis"] == "LEDGER_VALUE_WITH_REFERENCE_SALE"


def test_future_rebound_candidates_are_not_summed_as_cash_received():
    current, current_grid = sale()
    future, future_grid = sale("159781", held=11500, quantity=1000, price=1.093,
                               ledger_value=12178.5, status="WAIT_REBOUND")
    future["technical_assessment"] = {"status": "WEAK"}
    original = deepcopy([current, future, current_grid, future_grid])
    review = build_decision_review([current, future], [current_grid, future_grid], funding_plan=funding())
    assert len(review["sell_scenarios"]) == 1
    assert review["sell_scenarios"][0]["code"] == "159687"
    assert review["future_conditional_plan_count"] == 1
    assert [current, future, current_grid, future_grid] == original


@pytest.mark.parametrize("missing", ["cash", "market_value"])
def test_unknown_scenario_inputs_remain_unknown(missing):
    rec, grid = sale()
    account = funding()
    account.pop(missing)
    scenario = build_decision_review([rec], [grid], funding_plan=account)["sell_scenarios"][0]
    assert scenario["projected_cash" if missing == "cash" else "projected_position_pct"] is None


def test_missing_position_valuation_is_not_replaced_with_a_new_quote():
    rec, grid = sale()
    rec.pop("market_value")
    scenario = build_decision_review([rec], [grid], funding_plan=funding())["sell_scenarios"][0]
    assert scenario["estimated_proceeds"] == 1912
    assert scenario["projected_market_value"] is None
    assert scenario["projected_total_asset"] is None


def test_quantity_basis_explains_original_and_fallback_without_risk_optimization():
    rec, grid = sale()
    plan = describe_action_plan(rec, grid)
    assert plan["quantity_basis"]["source"] == "EXISTING_ORDER_QUANTITY"
    assert plan["quantity_basis"]["reduction_pct"] == pytest.approx(47.619, abs=.0001)
    assert not plan["quantity_basis"]["risk_optimized"]
    grid["current_sell_quantity"] = 1
    grid["parameter_plan"]["sell_quantity_source"] = "持仓约1/4取整，最低100份起拟"
    fallback = build_quantity_basis(rec, grid, 500, "WAIT_REBOUND")
    assert fallback["source"] == "HOLDING_QUARTER_FALLBACK"
    assert fallback["original_sell_quantity"] == 1
    rec.pop("account_total_asset")
    rec["position_pct_source"] = "positions_market_value_fallback"
    rec["position_pct"] = 100
    assert build_quantity_basis(rec, grid, 500, "WAIT_REBOUND")["account_weight_pct"] is None


def test_waiting_and_overheat_plans_expose_missing_contingencies_without_new_authority():
    rec, grid = sale(status="WAIT_REBOUND")
    plan = describe_action_plan(rec, grid)
    contingency = plan["contingency_plan"]
    assert {case["code"] for case in contingency["cases"]} == {
        "ACTIVATION_NOT_REACHED", "CONTINUED_DECLINE", "LONG_UNTRIGGERED"}
    assert contingency["review_deadline"] is None
    assert not contingency["automatic_actions_authorized"]
    assert "不证明理想卖点" in contingency["signal_caveat"]
    review = build_decision_review([rec], [grid])
    assert review["liquidation_constraint"]["can_delay_exit_indefinitely"]
    assert review["liquidation_constraint"]["unverified_cost_codes"] == ["159687"]
    assert review["cost_assumptions"]["fees_ignored"]
    assert not review["cost_assumptions"]["returns_validated"]
    assert review["migration"]["allocation_status"] == "UNSPECIFIED"
    assert "不阻断" in review["partial_review_boundary"]


def test_report_keeps_three_sections_and_explains_reduction_and_shared_gaps_once():
    rec, grid = sale()
    html = render_html("DEV-HISTORY", [rec], [grid], {}, {"funding_plan": funding()})
    assert html.count("<section id=") == 3
    assert html.count("计划边界与尚待确定项") == 1
    assert "减持本标的 47.62%" in html
    assert "剩余回本线" in html and "账户最大回撤与超限处置" in html
    assert "5632.43" in html
    assert "过热只是本次部分卖出复评依据" in html
