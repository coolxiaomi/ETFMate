from copy import deepcopy

import pytest

from etfmate.analysis.account_strategy import ANALYSIS_CONTRACT
from etfmate.analysis.data_quality import build_analysis_data_quality_report
from etfmate.analysis.grid_advisor import advise_grid
from etfmate.analysis.recommendation import recommend
from etfmate.report.daily_report import render_html
from etfmate.storage.models import GridConfig
from test_account_strategy import holding, market
from test_data_quality import _account, _grids, _analysis


def test_510500_one_share_source_does_not_erase_1000_share_inventory():
    p, m = holding(), market()
    g = GridConfig(p.code, p.name, True, buy_quantity=100, sell_quantity=1)
    result = advise_grid(g, m, p, {"high_risk": True, "portfolio": {"total_position_pct": 90.83}})
    assert result["candidate_sell_quantity"] == 200
    assert result["sell_policy"]["sale_scope"] == "PARTIAL"
    assert result["parameter_plan"]["buy_quantity"] == 100
    assert result["parameter_plan"]["sell_quantity"] == 200
    assert result["candidate_buy_quantity"] is None
    assert result["suggested_buy_quantity"] is result["suggested_sell_quantity"] is None
    assert result["grid_execution_status"] == "DO_NOT_ENABLE"
    assert "总仓90.83% ≥ 80%；高风险" in result["grid_execution_note"]
    assert result["current_sell_quantity"] == g.sell_quantity == 1


@pytest.mark.parametrize("raw", [None, 0, 1, 99, 150, float("nan"), float("inf"), 300])
@pytest.mark.parametrize("code", ["510500", "159259", "159781"])
def test_each_draft_has_six_valid_parameters(raw, code):
    p = holding(code)
    g = GridConfig(code, p.name, True, buy_quantity=raw, sell_quantity=raw)
    result = advise_grid(g, market(code), p)
    plan = result["parameter_plan"]
    for side in ("buy_quantity", "sell_quantity"):
        assert plan[side] >= 100 and plan[side] % 100 == 0
    for pct in ("buy_fall_pct", "buy_rebound_pct", "sell_rise_pct", "sell_pullback_pct"):
        assert plan[pct] > 0
    assert result["candidate_sell_quantity"] <= p.quantity - result["suggested_min_base_quantity"]
    assert result["grid_applicable"] is False


@pytest.mark.parametrize("quantity,ceiling", [(0, None), (100, None), (1000, 1000), (1000, 0)])
def test_draft_does_not_enable_grid_with_inventory_or_capacity_block(quantity, ceiling):
    p = holding(quantity=quantity)
    result = advise_grid(GridConfig(p.code, p.name, True, max_position_quantity=ceiling), market(), p)
    assert result["grid_execution_status"] == "DO_NOT_ENABLE"
    assert result["parameter_plan"]["buy_quantity"] >= 100
    assert result["parameter_plan"]["sell_quantity"] >= 100
    assert result["suggested_sell_quantity"] is None


def test_configured_zero_and_one_sided_bounds_render_without_unset_labels():
    p = holding()
    g = GridConfig(p.code, p.name, True, min_base_quantity=0)
    html = render_html("TEST", [recommend(p, g, market(), [p])], [advise_grid(g, market(), p)], {})
    assert "当前：最小仓 0" in html
    assert "最大仓" not in html and "未设置" not in html


def test_risk_block_does_not_discard_ceiling_when_showing_draft():
    p = holding()
    g = GridConfig(p.code, p.name, True, buy_quantity=500, max_position_quantity=1250)
    result = advise_grid(g, market(), p, {"high_risk": True})
    assert result["candidate_buy_quantity"] is None
    assert result["parameter_plan"]["buy_quantity"] == 200
    assert result["grid_execution_status"] == "DO_NOT_ENABLE"


@pytest.mark.parametrize("field,value", [("buy_quantity", 0), ("sell_quantity", 1), ("sell_quantity", 150),
                                         ("buy_fall_pct", None), ("sell_pullback_pct", -0.2)])
def test_analysis_gate_rejects_incomplete_or_illegal_grid_drafts(field, value):
    analysis = _analysis()
    advice = advise_grid(None, market(), holding())
    advice["parameter_plan"][field] = value
    analysis["grid_advices"] = [advice]
    result = build_analysis_data_quality_report(_account(), _grids(), analysis)
    assert any(f"双向参数 {field} 无效" in e for e in result["fatal_errors"])


def test_v4_and_version_only_migration_cannot_reuse_old_side_pause_advice():
    analysis = _analysis()
    analysis["analysis_contract"] = "etf_account_transition_v4"
    result = build_analysis_data_quality_report(_account(), _grids(), analysis)
    assert any("分析契约已更新" in e for e in result["fatal_errors"])
    changed = deepcopy(analysis)
    changed["analysis_contract"] = ANALYSIS_CONTRACT
    result = build_analysis_data_quality_report(_account(), _grids(), changed)
    assert any("缺少双向参数与整单状态" in e for e in result["fatal_errors"])
