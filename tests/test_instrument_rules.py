import pytest

from etfmate.analysis.instrument_rules import get_instrument_rule


@pytest.mark.parametrize("code", ["159687", "513120", "518880"])
def test_verified_cross_border_and_gold_etfs_allow_same_day_resale(code):
    rule = get_instrument_rule(code)
    assert rule["settlement"] == "T0"
    assert rule["same_day_sell_allowed"] is True
    assert len(rule["source_urls"]) == 2
    assert "sellable_quantity" not in rule


@pytest.mark.parametrize("code", [
    "159141", "159259", "159263", "159326", "159566", "159781", "159870",
    "510500", "515880", "560280", "562800", "588160",
])
def test_domestic_stock_etfs_do_not_make_new_purchases_sellable_same_day(code):
    assert get_instrument_rule(code)["settlement"] == "T1"
    assert get_instrument_rule(code)["same_day_sell_allowed"] is False
    assert len(get_instrument_rule(code)["source_urls"]) == 2


@pytest.mark.parametrize("code", ["159999", "513999", "518999", "600000", "invalid"])
def test_unknown_security_does_not_inherit_a_rule_from_its_prefix(code):
    rule = get_instrument_rule(code)
    assert rule["settlement"] == "UNKNOWN"
    assert rule["same_day_sell_allowed"] is None
    assert rule["verified_on"] is None


def test_exchange_qualified_code_is_normalized_without_mutating_registry():
    first = get_instrument_rule("SH513120")
    first["source_urls"].clear()
    assert get_instrument_rule("513120.SH")["source_urls"]
