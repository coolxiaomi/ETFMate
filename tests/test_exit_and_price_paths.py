"""Regression cases for current exits versus future, path-dependent grid plans."""
from dataclasses import replace

import pytest

from etfmate.analysis.grid_advisor import advise_grid
from etfmate.analysis.recommendation import recommend
from etfmate.analysis.rule_engine import _trend_score
from etfmate.analysis.technical_assessment import assess_technical
from etfmate.storage.models import GridConfig
from test_account_strategy import holding, market


def _review(position, quote, grid=None):
    rec = recommend(position, grid, quote, [position] if position else [])
    return rec, advise_grid(grid, quote, position, rec["rule_decision"])


def test_159687_cost_recovered_and_hot_exit_uses_current_price_without_granting_liquidation():
    p = replace(holding("159687", quantity=2100), cost_price=1.905, position_pct=90.88)
    m = replace(market(p.code), last_price=1.913, signal_close=1.91, ma5=1.86,
                ma10=1.855, ma20=1.847, ma60=1.8468, ma5_slope_3=.0108696,
                bias5_ratio=.0268817, bias6=2.68817, bias12=3.28977, bias24=3.75736,
                rsi6=68.75, rsi14=73.913, boll_position=1, boll_upper=1.904345,
                vol_ratio_1_5=.86998, vol_ratio_5_20=.90582, atr14_pct=1.49589)
    rec, g = _review(p, m, GridConfig(p.code, p.name, True, base_price=1.877, sell_quantity=1000))
    assert rec["rule_trend_score"] == 82
    assert rec["rule_decision"]["trend_overheat_level"] == "SEVERE_OVERHEATED"
    assert "当前评估分批退出" in rec["action"]
    assert rec["rule_decision"]["legacy_exit_assessment"]["page_cost_recovered"]
    assert g["partial_sell_plan"]["status"] == "CURRENT_PARTIAL_REVIEW"
    assert g["partial_sell_plan"]["reference_price"] == 1.913
    assert g["partial_sell_plan"]["candidate_quantity"] == 1000
    assert g["partial_sell_plan"]["sell_policy"]["status"] == "PARTIAL_ALLOWED"
    assert g["first_sell_reference_price"] > m.last_price  # Future plan has its own purpose.
    assert rec["candidate_liquidation_quantity"] is None
    assert rec["sell_policy"]["status"] == "PENDING_COST_BASIS"
    assert g["conditional_buyback_quantity"] is None
    evidence = rec["rule_decision"]["trend_overheat_evidence"]
    assert any("布林" in item for item in evidence)
    assert not any("RSI" in item for item in evidence)


@pytest.mark.parametrize("price,expected", [(1.2, "CURRENT_PARTIAL_REVIEW"), (1.199, "WAIT_REBOUND")])
def test_page_cost_equality_only_changes_partial_exit_timing(price, expected):
    p = holding("159781")
    rec, g = _review(p, replace(market(p.code), last_price=price))
    assert g["partial_sell_plan"]["status"] == expected
    assert rec["candidate_liquidation_quantity"] is None


def test_hot_target_position_has_current_partial_plan_and_keeps_base_inventory():
    p = holding("510500")
    rec, g = _review(p, replace(market(), rsi6=80))
    assert g["partial_sell_plan"]["status"] == "CURRENT_PARTIAL_REVIEW"
    assert g["partial_sell_plan"]["candidate_quantity"] <= p.quantity - g["suggested_min_base_quantity"]
    assert g["candidate_buy_quantity"] is None
    assert rec["candidate_liquidation_quantity"] is None


def test_510500_snapshot_beyond_sell_trigger_requires_path_review_not_another_rebound():
    p = holding()
    m = replace(market(), last_price=7.838, signal_close=7.84, ma5=7.762, ma10=7.834,
                ma20=7.888, ma60=8.087, ma5_slope_3=-.012468, bias5_ratio=.010049,
                rsi6=37.73585, boll_position=.41832, vol_ratio_1_5=.34008,
                vol_ratio_5_20=1.13429, atr14_pct=2.040816)
    original = GridConfig(p.code, p.name, True, base_price=7.61, sell_quantity=1)
    _, g = _review(p, m, original)
    prices = g["price_plan"]
    assert prices["base_price"] == original.base_price == 7.61
    assert prices["sell_trigger_price"] == pytest.approx(7.769)
    assert prices["sell_trigger_price"] < m.last_price
    assert prices["sell_path_status"] == "TRIGGER_ZONE_PATH_UNVERIFIED"
    assert prices["path_evidence"] == "SNAPSHOT_ONLY"
    assert g["grid_execution_status"] == "DO_NOT_ENABLE"
    assert g["suggested_sell_quantity"] is None


@pytest.mark.parametrize("quantity", [0, 100])
def test_current_exit_cannot_bypass_inventory_floor(quantity):
    p = holding("159781", quantity=quantity)
    _, g = _review(p, replace(market(p.code), rsi6=80, last_price=1.3))
    assert g["partial_sell_plan"]["status"] == "NO_PARTIAL_INVENTORY"
    assert g["partial_sell_plan"]["candidate_quantity"] is None
    assert g["partial_sell_plan"]["reference_price"] is None


def test_invalid_full_trade_gate_never_produces_current_sell_quantity():
    p, m = holding("159781"), replace(market("159781"), rsi6=80)
    g = advise_grid(None, m, p, {"blocked_actions": ["全部"]})
    assert g["partial_sell_plan"]["status"] == "WAIT_DATA"
    assert g["partial_sell_plan"]["candidate_quantity"] is None


def test_score_and_heat_do_not_mix_current_quote_with_prior_daily_indicators():
    prior = replace(market(), signal_close=1.1, last_price=.7)
    assert _trend_score(prior)["score"] == _trend_score(replace(prior, last_price=2))["score"]
    assert _trend_score(prior)["indicators"]["price_basis"] == "DAILY_SIGNAL"


def test_incomplete_intraday_volume_cannot_establish_a_weak_volume_conclusion():
    m = replace(market(), signal_is_complete=False, signal_volume_basis="intraday_daily", vol_ratio_1_5=.1)
    technical = assess_technical(m)
    assert technical["status"] == "INSUFFICIENT"
    assert technical["buy_gate"] == "WAIT_CONFIRMATION"
    assert "不能与完整日量直接比较" in technical["evidence"][2]["text"]
    trend = _trend_score(m)
    assert not trend["data_sufficient"]
    assert "短线量能不足" not in trend["tags"]


def test_mixed_with_no_individual_threshold_missing_still_has_meaningful_condition():
    m = replace(market(), ma5=1.1)  # Exact MA equality breaks strict up without an unmet single threshold.
    technical = assess_technical(m)
    assert technical["status"] == "MIXED"
    assert technical["buy_condition"] != "等待后复评。"
