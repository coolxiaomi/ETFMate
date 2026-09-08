from copy import deepcopy

import pytest

from etfmate.analysis.funding_plan import build_funding_plan


def account(cash=6366.66, total=69579.36, value=63212.70):
    return {"account_summary": {"cash": cash, "total_asset": total, "total_market_value": value},
            "positions": [{"code": "588160", "quantity": "1600"}],
            "snapshot": {"text": "最新上传时间: 2026-09-08 09:42，持仓列表"},
            "trades": [{"side": "卖出", "amount": "2671.00", "trade_date": "2026-09-07"}]}


def grid(code="510500", base=7.61, fall=2.2, rebound=.2, quantity=100, **extra):
    return {"code": code, "condition_type": "grid", "enabled": True, "status": "监控中",
            "base_price": str(base), "buy_fall_pct": f"-{fall}", "buy_rebound_pct": f"+{rebound}",
            "buy_quantity": str(quantity), **extra}


def original_conditions():
    rows = [grid(*args) for args in [
        ("510500", 7.610, 2.20, .20, 100), ("513120", 1.306, 5.20, .20, 500),
        ("515880", .670, 5.20, .20, 500), ("588160", 1.052, 5.20, .20, 500),
        ("159781", 1.065, 3.15, .15, 1000), ("159566", 1.818, 5.10, .10, 500),
        ("159870", .815, 5.20, .20, 500), ("159687", 1.877, 5.20, .20, 500),
        ("562800", .918, 5.20, .20, 500), ("518880", 9.058, 5.05, .05, 100),
        ("159141", 1.170, 5.15, .15, 1000), ("159326", 1.693, 5.15, .15, 500),
        ("560280", 1.534, 5.20, .20, 500),
    ]]
    rows[3]["max_position_quantity"] = "2000"
    rows.extend({"code": code, "condition_type": "buy_only", "enabled": True, "buy_quantity": "1000",
                 "raw_text": f"股价低于(含){gate}元后，每次个股涨跌幅达到-5.00%买入，最大买入数量10000股"}
                for code, gate in (("159259", "1.300"), ("159263", "1.115")))
    return rows


def test_closed_pool_uses_cash_once_and_separates_cap_from_condition_exposure():
    source = account()
    untouched = deepcopy(source)
    plan = build_funding_plan(source, original_conditions())
    assert source == untouched
    assert plan["cash"] == 6366.66
    assert plan["position_pct"] == pytest.approx(90.849786)
    assert plan["buy_capacity_under_cap"] == 0
    assert plan["required_net_sell_to_cap"] == pytest.approx(7549.212)
    assert plan["first_cycle_estimated_cash"] == pytest.approx(11714.531247, abs=.00001)
    assert plan["shortfall"] == pytest.approx(5347.871247, abs=.00001)
    assert plan["active_buy_condition_count"] == plan["condition_count"] == 15
    assert plan["estimate_complete"]
    assert plan["monitoring_is_frozen"] is False
    assert plan["source_uploaded_at"] == "2026-09-08 09:42"
    assert all(row["broker_order_status"] is None for row in plan["conditions"])


def test_588160_keeps_original_500_share_exposure_and_reports_400_share_headroom():
    result = build_funding_plan(account(), [grid("588160", 1.052, 5.2, .2, 500, max_position_quantity="2000")])
    row = result["conditions"][0]
    assert row["buy_quantity"] == 500
    assert row["buy_headroom_quantity"] == row["max_buy_quantity_by_inventory"] == 400
    assert "BUY_EXCEEDS_MAX_POSITION" in row["limitation_codes"]
    assert row["first_cycle_estimated_cash"] == pytest.approx(499.645296)
    assert row["included_in_first_cycle"]  # Nominal source exposure, never a resized executable order.


def test_entry_gate_is_only_reference_without_inventing_a_minus_five_percent_first_price():
    condition = {"code": "159259", "condition_type": "buy_only", "enabled": True,
                 "buy_quantity": 1000, "raw_text": "股价低于（含）1.300元后，每次涨跌幅达到-5.00%买入"}
    row = build_funding_plan(account(), [condition])["conditions"][0]
    assert row["first_cycle_estimated_cash"] == 1300
    assert row["buy_price_example"] == 1.3
    assert row["estimate_basis"] == "ENTRY_GATE_PRICE_REFERENCE"
    assert "ENTRY_PATH_UNVERIFIED" in row["limitation_codes"]


@pytest.mark.parametrize("changes", [{"buy_quantity": "1"}, {"buy_quantity": "0"},
                                     {"buy_fall_pct": "100"}, {"buy_rebound_pct": None},
                                     {"base_price": float("nan")}])
def test_incomplete_or_invalid_active_order_does_not_look_fully_funded(changes):
    first, invalid = grid(), grid("159687", 1.877, 5.2, .2, 500)
    invalid.update(changes)
    plan = build_funding_plan(account(), [first, invalid])
    assert plan["first_cycle_estimated_cash"] is None
    assert plan["shortfall"] is None
    assert not plan["estimate_complete"]
    assert plan["known_first_cycle_estimated_cash"] == pytest.approx(745.746516)


def test_inactive_and_sell_only_conditions_do_not_reserve_buying_cash():
    inactive = grid(enabled=False)
    sell_only = {"code": "159687", "condition_type": "sell_only", "enabled": True, "order_quantity": 1000}
    plan = build_funding_plan(account(), [inactive, sell_only])
    assert plan["first_cycle_estimated_cash"] == 0
    assert plan["shortfall"] == 0
    assert plan["active_buy_condition_count"] == 0
    assert plan["cash"] == 6366.66


@pytest.mark.parametrize("conditions", [None, [{"code": "X", "enabled": True, "condition_type": "unknown"}],
                                       [grid(enabled=None)]])
def test_unknown_scope_or_monitoring_state_keeps_total_unknown(conditions):
    plan = build_funding_plan(account(), conditions)
    assert plan["first_cycle_estimated_cash"] is None
    assert plan["shortfall"] is None


def test_cash_is_not_backfilled_from_assets_or_old_sales_and_zero_is_valid():
    missing = build_funding_plan(account(cash=None), [grid()])
    assert missing["cash"] is missing["shortfall"] is missing["buy_capacity_under_cap"] is None
    zero = build_funding_plan(account(cash=0), [grid()])
    assert zero["cash"] == zero["buy_capacity_under_cap"] == 0
    assert zero["shortfall"] == pytest.approx(745.746516)


def test_buy_capacity_is_intersection_of_captured_cash_and_cap_headroom():
    below = build_funding_plan(account(cash=2000, total=10000, value=7500), [])
    assert below["buy_capacity_under_cap"] == 500
    assert below["required_net_sell_to_cap"] == 0
    limited_cash = build_funding_plan(account(cash=100, total=10000, value=7500), [])
    assert limited_cash["buy_capacity_under_cap"] == 100
    at_cap = build_funding_plan(account(cash=2000, total=10000, value=8000), [])
    assert at_cap["buy_capacity_under_cap"] == 0


def test_explicit_zero_ceiling_and_unknown_inventory_are_not_unlimited():
    zero = build_funding_plan(account(), [grid(max_position_quantity=0)])["conditions"][0]
    assert zero["max_buy_quantity_by_inventory"] == 0
    assert "BUY_EXCEEDS_MAX_POSITION" in zero["limitation_codes"]
    source = account()
    del source["positions"]
    unknown = build_funding_plan(source, [grid(max_position_quantity=2000)])["conditions"][0]
    assert unknown["buy_headroom_quantity"] is None
    assert "INVENTORY_UNKNOWN" in unknown["limitation_codes"]
