import pytest

from etfmate.analysis.data_quality import build_raw_data_quality_report
from etfmate.analysis.grid_advisor import advise_grid
from etfmate.analysis.recommendation import recommend
from etfmate.cli import _optional_grid_limit
from etfmate.report.daily_report import render_html
from etfmate.storage.models import GridConfig
from test_account_strategy import holding, market
from test_data_quality import _account, _grids


@pytest.mark.parametrize("value", [None, "", "--", "未设置", "不限制", "不限"])
def test_unset_bounds_are_optional_and_not_zero(value):
    grids = _grids()
    grids["grids"][0].update(min_base_quantity=value, max_position_quantity=value)
    quality = build_raw_data_quality_report(_account(), grids)
    assert quality["status"] == "PASS"
    assert not any("底仓" in w or "最大持仓" in w for w in quality["warnings"])
    assert _optional_grid_limit(value) is None


def test_absent_limits_still_produce_advice_without_fake_execution():
    p, m = holding(), market()
    g = GridConfig(p.code, p.name, True, buy_quantity=500, sell_quantity=200)
    advice = advise_grid(g, m, p)
    assert advice["min_base_status"] == advice["max_position_status"] == "UNSET"
    assert advice["current_min_base_quantity"] is None
    assert advice["current_max_position_quantity"] is None
    assert advice["candidate_buy_quantity"] == 500
    assert advice["candidate_sell_quantity"] == 200
    assert advice["suggested_min_base_quantity"] == 500
    assert advice["suggested_buy_quantity"] is None
    assert not advice["grid_applicable"]


@pytest.mark.parametrize("code", ["510500", "159781"])
def test_explicit_floor_is_respected_for_targets_and_legacy(code):
    p = holding(code)
    g = GridConfig(code, p.name, True, sell_quantity=500, min_base_quantity=850)
    advice = advise_grid(g, market(code), p)
    assert advice["current_min_base_quantity"] == 850
    assert advice["min_base_status"] == "CONFIGURED"
    assert advice["candidate_sell_quantity"] == 100
    assert advice["suggested_min_base_quantity"] == 900


@pytest.mark.parametrize("ceiling, expected", [(None, 500), (0, None), (1000, None), (1099, None), (1250, 200)])
def test_explicit_ceiling_caps_buy_and_preserves_zero(ceiling, expected):
    p = holding()
    g = GridConfig(p.code, p.name, True, buy_quantity=500, max_position_quantity=ceiling)
    advice = advise_grid(g, market(), p)
    assert advice["candidate_buy_quantity"] == expected
    assert advice["current_max_position_quantity"] == ceiling
    assert _optional_grid_limit(ceiling) == ceiling


def test_legacy_buyback_respects_inventory_after_sale():
    p = holding("159781")
    g = GridConfig(p.code, p.name, True, sell_quantity=400, max_position_quantity=700)
    advice = advise_grid(g, market(p.code), p)
    assert advice["candidate_sell_quantity"] == 400
    assert advice["conditional_buyback_quantity"] == 100


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), 1.5, "bad"])
def test_invalid_limits_are_not_treated_as_unset(value):
    grids = _grids()
    grids["grids"][0]["max_position_quantity"] = value
    assert build_raw_data_quality_report(_account(), grids)["status"] == "FAIL"
    with pytest.raises(ValueError):
        _optional_grid_limit(value)


def test_reversed_limits_fail_quality_gate():
    grids = _grids()
    grids["grids"][0].update(min_base_quantity=2000, max_position_quantity=1000)
    assert build_raw_data_quality_report(_account(), grids)["status"] == "FAIL"


def test_report_distinguishes_quantity_reasons_and_optional_settings():
    p = holding()
    g = GridConfig(p.code, p.name, True, buy_quantity=100, sell_quantity=1)
    recs = [recommend(p, g, market(), [p]), recommend(None, None, market("159259"), [p])]
    advice = advise_grid(g, market(), p, {"high_risk": True})
    empty = advise_grid(None, market("159259"))
    html = render_html("TEST-optional-grid-limits · 无实时账户数据", recs, [advice, empty], {})
    for label in ["建议份额", "新增买入已暂停", "现有卖出数量不足100份或已停用", "未持仓",
                  "未设置（不设固定下限）", "未设置（不设固定上限）", "本次建议保留 500 份",
                  "未提供可用金额", "当前尚未建仓"]:
        assert label in html
    for misleading in ["待核验份", "待核验 份", "候选份额，待核验", "待核验%", "—份", "最大持仓待预算确认"]:
        assert misleading not in html
