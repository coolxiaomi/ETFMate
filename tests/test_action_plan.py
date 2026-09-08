from dataclasses import replace

import pytest

from etfmate.analysis.action_plan import describe_action_plan
from etfmate.analysis.account_strategy import account_overview
from etfmate.analysis.ai_advisor import build_ai_review_input, normalize_host_ai_judgements
from etfmate.analysis.grid_advisor import advise_grid
from etfmate.analysis.recommendation import recommend
from etfmate.report.daily_report import render_html
from etfmate.storage.models import GridConfig
from test_account_strategy import holding, market


def mixed(code="510500"):
    return replace(market(code), vol_ratio_1_5=.95)


def test_mixed_signals_alone_do_not_block_conditional_plan():
    p, m = holding(), mixed()
    rec = recommend(p, None, m, [p])
    g = advise_grid(None, m, p, rec["rule_decision"])
    assert rec["technical_assessment"]["status"] == "MIXED"
    assert "买入" not in rec["rule_decision"]["blocked_actions"]
    assert g["candidate_buy_quantity"] > 0
    assert g["grid_execution_status"] == "PENDING_VERIFICATION"
    assert g["suggested_buy_quantity"] is None and not g["grid_applicable"]
    assert "量比" in describe_action_plan(rec, g)["buy_condition"]


@pytest.mark.parametrize("risk", ["portfolio", "short_sample", "high_risk", "pair_overweight"])
def test_soft_mixed_signal_does_not_bypass_other_limits(risk):
    p, m = holding("159259"), mixed("159259")
    ps = [p]
    if risk == "portfolio":
        p.position_pct = 90.83
    elif risk == "short_sample":
        m.kline_days = 80
    elif risk == "high_risk":
        m.rsi6, m.bias5_ratio, m.boll_position = 38, -.02, .1
        m.ma5, m.ma10 = 1.2, 1.3
    else:
        ps.append(holding("159263", value=100))
    rec = recommend(p, None, m, ps)
    g = advise_grid(None, m, p, rec["rule_decision"])
    assert rec["technical_assessment"]["status"] == "MIXED"
    assert "买入" in rec["rule_decision"]["blocked_actions"]
    assert g["candidate_buy_quantity"] is None
    assert g["grid_execution_status"] == "DO_NOT_ENABLE"
    if risk == "high_risk":
        assert rec["target_position_ratio"] == 0


def test_unheld_target_has_entry_plan_but_no_sell_or_active_grid():
    m = mixed("159259")
    rec = recommend(None, None, m)
    g = advise_grid(None, m, None, rec["rule_decision"])
    plan = describe_action_plan(rec, g)
    assert plan["stage"] == "INITIAL_ENTRY"
    assert "分批建立底仓" in plan["headline"]
    assert "建仓后" in plan["sell_condition"]
    assert g["candidate_buy_quantity"] > 0 and g["candidate_sell_quantity"] is None
    assert g["grid_execution_status"] == "DO_NOT_ENABLE"
    assert g["parameter_plan"]["sell_quantity"] >= 100
    assert "建仓后" in g["parameter_plan"]["sell_quantity_source"]
    html = render_html("TEST", [rec], [g], {})
    assert "卖出库存不足" not in html and "暂不启用整单" not in html
    assert "共同执行规则与指标口径" not in html


def test_account_cap_is_shown_once_while_each_plan_keeps_specific_conditions():
    p = holding("159781"); p.position_pct = 90.83
    markets = [mixed(p.code), mixed("159259"), mixed("159263")]
    recs = [recommend(p if m.code == p.code else None, None, m, [p]) for m in markets]
    grids = [advise_grid(None, m, p if m.code == p.code else None, r["rule_decision"]) for m, r in zip(markets, recs)]
    assert all(not g["candidate_buy_quantity"] and not g.get("conditional_buyback_quantity") for g in grids)
    assert grids[0]["candidate_sell_quantity"] > 0
    html = render_html("TEST", recs, grids, {})
    assert html.count("90.83%") == 1 and html.count("80%新增买入门槛") == 1
    assert "暂不启用整单" not in html and "量价条件未确认" not in html
    assert "等待反弹，分批回收资金" in html and "本批次暂停回补" in html
    assert "建议" in html and "后续网格参数草案" in html
    ai = build_ai_review_input(recs, grids)
    assert ai["items"][0]["action_plan"] == describe_action_plan(recs[0], grids[0])


def test_unknown_account_percentage_is_not_presented_as_confirmed_cap():
    p = holding(); p.position_pct = 100; p.position_pct_source = "positions_market_value_fallback"
    overview = account_overview([recommend(p, None, mixed(), [p])])
    assert overview["total_position_pct"] is None
    assert "口径未确认" in overview["position_note"]


def test_collected_disabled_state_and_original_order_errors_are_retained():
    p, m = holding(), mixed()
    original = GridConfig(p.code, p.name, False, buy_quantity=100, sell_quantity=1)
    rec = recommend(p, original, m, [p])
    g = advise_grid(original, m, p, rec["rule_decision"])
    html = render_html("TEST", [rec], [g], {})
    assert "采集时原网格已停用" in html and "采集单笔卖量1" in html
    assert g["grid_execution_status"] == "DO_NOT_ENABLE"
    assert not original.enabled and original.sell_quantity == 1


def test_retired_legacy_is_not_represented_as_new_entry_and_old_ai_is_rejected():
    m = mixed("159781")
    rec = recommend(None, None, m)
    g = advise_grid(None, m, None, rec["rule_decision"])
    assert describe_action_plan(rec, g)["stage"] == "RETIRED"
    assert g["candidate_buy_quantity"] is None
    assert not normalize_host_ai_judgements({"review_contract": "etf_account_transition_v6", "items": []}, [rec])[m.code]["enabled"]
