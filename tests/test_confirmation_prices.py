"""Price examples must meet the percentage at the displayed ETF tick."""
from copy import deepcopy
from decimal import Decimal

import pytest

from etfmate.analysis.data_quality import _validate_price_and_partial_plan
from etfmate.analysis.grid_advisor import advise_grid
from etfmate.analysis.price_ticks import confirmation_price
from etfmate.analysis.recommendation import recommend
from test_account_strategy import holding, market


# Fixed values independently recalculated from the 20260908-121824 report.
SELL_CASES = [
    ("159326", 1.698, .25, "1.6937550", "1.693", "1.694"),
    ("562800", .942, .33, "0.9388914", "0.938", "0.939"),
    ("159566", 1.822, .29, "1.8167162", "1.816", "1.817"),
    ("159870", .829, .25, "0.8269275", "0.826", "0.827"),
    ("515880", .721, .46, "0.7176834", "0.717", "0.718"),
    ("513120", 1.333, .31, "1.3288677", "1.328", "1.329"),
]
BUY_CASES = [
    ("159259", 1.251, .80, "1.261008", "1.262", "1.261"),
    ("159566", 1.678, .66, "1.6890748", "1.690", "1.689"),
    ("159870", .772, .55, "0.7762460", "0.777", "0.776"),
    ("515880", .638, .69, "0.6424022", "0.643", "0.642"),
    ("562800", .857, .75, "0.8634275", "0.864", "0.863"),
]


@pytest.mark.parametrize("side,case", [("sell", row) for row in SELL_CASES] + [("buy", row) for row in BUY_CASES],
                         ids=[f"sell-{row[0]}" for row in SELL_CASES] + [f"buy-{row[0]}" for row in BUY_CASES])
def test_report_regressions_meet_percentage_and_adjacent_tick_does_not(side, case):
    _, extreme, pct, expected_raw, expected_tick, old_display = case
    theoretical, tick = confirmation_price(extreme, pct, side)
    assert theoretical == Decimal(expected_raw)
    assert tick == Decimal(expected_tick)
    assert tick % Decimal("0.001") == 0
    start, rate = Decimal(str(extreme)), Decimal(str(pct))
    direction = 1 if side == "buy" else -1
    assert direction * (tick - start) * 100 >= start * rate
    previous = tick - direction * Decimal("0.001")
    assert direction * (previous - start) * 100 < start * rate
    assert direction * (Decimal(old_display) - start) * 100 < start * rate


@pytest.mark.parametrize("side,pct,expected", [
    ("buy", .1, "1.001"), ("buy", .099999, "1.001"), ("buy", .100001, "1.002"),
    ("sell", .1, "0.999"), ("sell", .099999, "0.999"), ("sell", .100001, "0.998"),
])
def test_exact_tick_and_nearby_boundaries_do_not_gain_or_lose_a_tick(side, pct, expected):
    _, tick = confirmation_price(1, pct, side)
    assert tick == Decimal(expected)


def _advice():
    position, quote = holding("159566"), market("159566")
    rec = recommend(position, None, quote, [position])
    return rec, advise_grid(None, quote, position, rec["rule_decision"])


def _errors(rec, grid):
    errors = []
    _validate_price_and_partial_plan(grid, rec, errors)
    return errors


def test_generated_plan_separates_exact_boundary_from_tick_and_unifies_references():
    rec, grid = _advice()
    assert not _errors(rec, grid)
    path = grid["price_plan"]
    assert path["confirmation_price_basis"] == "EXTREME_EQUALS_TRIGGER"
    assert path["price_tick"] == .001
    for side in ("buy", "sell"):
        assert isinstance(path[f"{side}_confirmation_theoretical_price"], str)
        assert (path[f"{side}_confirmation_tick_price"] == path[f"{side}_confirmation_example"]
                == grid[f"first_{side}_reference_price"])
    if grid["partial_sell_plan"]["status"] == "WAIT_REBOUND":
        assert grid["partial_sell_plan"]["reference_price"] == path["sell_confirmation_tick_price"]


@pytest.mark.parametrize("mutation", ["legacy_structure", "rounded_theory", "float_theory", "wrong_assumption", "wrong_tick",
                                      "early_buy", "early_sell", "fractional_buy", "fractional_sell",
                                      "later_buy", "later_sell", "old_buy_alias", "old_sell_alias"])
def test_gate_rejects_old_or_tampered_confirmation_contract(mutation):
    rec, original = _advice()
    grid = deepcopy(original)
    path = grid["price_plan"]
    if mutation == "legacy_structure":
        for key in list(path):
            if key in {"price_tick", "confirmation_price_basis"} or "_theoretical_" in key or "_tick_" in key:
                path.pop(key)
    elif mutation == "rounded_theory":
        path["sell_confirmation_theoretical_price"] = f'{float(path["sell_confirmation_theoretical_price"]):.6f}'
        if path["sell_confirmation_theoretical_price"] == original["price_plan"]["sell_confirmation_theoretical_price"]:
            path["sell_confirmation_theoretical_price"] = "1.000000"
    elif mutation == "float_theory":
        path["sell_confirmation_theoretical_price"] = float(path["sell_confirmation_theoretical_price"])
    elif mutation == "wrong_assumption":
        path["confirmation_price_basis"] = "ACTUAL_PEAK_VERIFIED"
    elif mutation == "wrong_tick":
        path["price_tick"] = .01
    else:
        mode, side = mutation.rsplit("_", 1) if "alias" not in mutation else ("alias", mutation.split("_")[1])
        if mode == "alias":
            grid[f"first_{side}_reference_price"] += .0001
        else:
            tick = Decimal(str(path[f"{side}_confirmation_tick_price"]))
            direction = 1 if side == "buy" else -1
            delta = -direction * Decimal(".001") if mode == "early" else direction * Decimal(".001")
            if mode == "fractional":
                delta = direction * Decimal(".0001")
            path[f"{side}_confirmation_tick_price"] = float(tick + delta)
            path[f"{side}_confirmation_example"] = float(tick + delta)
            grid[f"first_{side}_reference_price"] = float(tick + delta)
    errors = _errors(rec, grid)
    assert errors
    if mutation.startswith("early"):
        assert any("未满足确认比例" in error for error in errors)
    if mutation.startswith("fractional"):
        assert any("不在0.001交易档位" in error for error in errors)


def test_ordinary_rounding_remains_rejected_after_all_legacy_aliases_are_changed():
    from etfmate.analysis.data_quality import _validate_confirmation_prices

    for side, case in [("sell", row) for row in SELL_CASES] + [("buy", row) for row in BUY_CASES]:
        code, trigger, pct, raw, _, old = case
        _, grid = _advice()
        grid["code"] = code
        triggers = {"buy": 1., "sell": 1.}
        percentages = {"buy": .1, "sell": .1}
        triggers[side], percentages[side] = trigger, pct
        for direction in ("buy", "sell"):
            theoretical, tick = confirmation_price(triggers[direction], percentages[direction], direction)
            grid["price_plan"][f"{direction}_confirmation_theoretical_price"] = format(theoretical, "f")
            for field in (f"{direction}_confirmation_tick_price", f"{direction}_confirmation_example"):
                grid["price_plan"][field] = float(tick)
            grid[f"first_{direction}_reference_price"] = float(tick)
        for field in (f"{side}_confirmation_tick_price", f"{side}_confirmation_example"):
            grid["price_plan"][field] = float(old)
        grid[f"first_{side}_reference_price"] = float(old)
        errors = []
        _validate_confirmation_prices(grid, triggers, percentages, errors)
        assert any("未满足确认比例" in error for error in errors), (code, side, raw)
