from dataclasses import replace
import json

import pytest

from etfmate.analysis.account_strategy import TARGETS, pair_progress, account_overview, ANALYSIS_CONTRACT
from etfmate.analysis.recommendation import recommend
from etfmate.analysis.grid_advisor import advise_grid
from etfmate.analysis import rule_engine
from etfmate.analysis.ai_advisor import build_ai_review_input, normalize_host_ai_judgements, attach_ai_judgements
from etfmate.report.daily_report import render_html
from etfmate.storage.models import Position, MarketSnapshot, GridConfig


def market(code="510500"):
    return MarketSnapshot(code, TARGETS.get(code, {}).get("name", "测试ETF"), 1.10, 0, 1000000, 300000000,
                          ma5=1.05, ma10=1, ma20=.95, ma60=.90, atr14_pct=2, kline_days=240, ma5_slope_3=.02, bias5_ratio=.02,
                          rsi6=60, boll_position=.8, vol_ratio_1_5=1.35, vol_ratio_5_20=1.1)


def holding(code="510500", quantity=1000, value=1000):
    return Position(code, "测试ETF", quantity, 1.2, 1, value, -200, -20,
                    position_pct=10, position_pct_source="ths_account_total_asset", account_total_asset=10000)


@pytest.mark.parametrize("code", ["159781", "510300", "159915"])
def test_existing_legacy_position_is_managed_and_closed_position_is_not_reopened(code):
    p = holding(code)
    rec = recommend(p, None, market(code), [p])
    assert rec["strategy_role"] == "LEGACY_EXIT"
    assert rec["position_action"] == "MANAGE_EXISTING"
    assert rec["action_quantity"] is None
    assert recommend(None, None, market(code))["position_action"] == "RETIRE_GRID"


def test_pair_ratio_is_group_only_and_building_does_not_force_sell():
    ps = [holding("159259", value=9000), holding("159263", value=1000)]
    progress = pair_progress(ps)
    assert progress["target_weights"] == {"159259": .4, "159263": .6}
    assert progress["dip_buy_priority"] == "159263"
    for p in ps:
        rec = recommend(p, None, market(p.code), ps)
        assert rec["target_position_ratio"] is None
        assert rec["action_quantity"] is None
        assert rec["pair_progress"]["phase"] == "BUILDING"
    ps[0].market_value, ps[1].market_value = 4000, 6000
    assert pair_progress(ps)["phase"] == "BUILDING"
    assert pair_progress(ps)["dip_buy_priority"] is None


def test_empty_pair_has_no_division_or_forced_full_purchase():
    p = pair_progress([])
    assert p["current_weights"] == {"159259": None, "159263": None}
    assert p["dip_buy_priority"] is None
    rec = recommend(None, None, market("159259"))
    assert rec["action_quantity"] is None
    assert rec["target_position_ratio"] is None


def test_five_holdings_do_not_block_transitional_target_opportunity():
    ps = [holding(str(510300+i)) for i in range(5)]
    rec = recommend(None, None, market("159141"), ps)
    assert rec["position_action"] == "WAIT_DIP"
    assert "买入" not in rec["rule_decision"]["blocked_actions"]
    assert rec["funding_plan"]["allow_existing_cash"] is True
    assert all(recommend(p,None,market(p.code),ps)["candidate_liquidation_quantity"] is None for p in ps)


def test_high_risk_zero_target_retains_actual_position_and_blocks_grid(monkeypatch):
    monkeypatch.setattr(rule_engine, "_trend_score", lambda m: {
        "score":40,"name":"弱势","level":"WEAK","tags":[],"scores":{},"indicators":{},"data_sufficient":True,"evidence":[]})
    p,m = holding(),market()
    rec = recommend(p,None,m,[p])
    assert rec["rule_decision"]["high_risk"] is True
    assert rec["target_position_ratio"] == 0
    assert rec["new_position_ratio"] == rec["current_position_ratio"]
    assert rec["adjust_ratio"] == 0
    assert rec["position_action"] == "WAIT_BUY_REVIEW"
    assert advise_grid(None,m,p,rec["rule_decision"])["buy_execution_status"] == "DISABLED"


def test_fallback_position_percentage_does_not_fake_account_cap():
    p=holding();p.position_pct=100;p.position_pct_source="positions_market_value_fallback"
    rec=recommend(p,None,market(),[p])
    assert rec["rule_decision"]["portfolio"]["total_position_pct"] == 0
    assert rec["action_quantity"] is None


def test_sector_identity_and_asymmetric_staged_parameters():
    p,m=holding("159141"),market("159141")
    rec=recommend(p,None,m,[p])
    assert rec["rule_decision"]["category"] == "行业主题ETF"
    g=GridConfig(p.code,p.name,True,base_price=.99,buy_quantity=200,sell_quantity=200)
    result=advise_grid(g,m,p,rec["rule_decision"])
    assert result["suggested_buy_fall_pct"] > result["suggested_sell_rise_pct"]
    assert result["suggested_buy_rebound_pct"] != result["suggested_sell_pullback_pct"]
    assert result["candidate_buy_quantity"] == 400
    assert result["candidate_sell_quantity"] == 200
    assert result["suggested_base_price"] == .99
    assert g.buy_quantity == 200  # Never mutate a real order.


def test_missing_inventory_or_side_quantity_is_not_fabricated():
    m=market("159259")
    result=advise_grid(None,m)
    assert result["candidate_buy_quantity"] is None
    assert result["candidate_sell_quantity"] is None
    assert result["grid_applicable"] is False
    p=holding("159259")
    g=GridConfig(p.code,p.name,True,order_quantity=100,buy_quantity=0,sell_quantity=0)
    result=advise_grid(g,m,p)
    assert result["candidate_buy_quantity"] is None
    assert result["candidate_sell_quantity"] is None


@pytest.mark.parametrize("atr", [None,0,float("nan"),float("inf")])
def test_invalid_market_does_not_produce_parameters(atr):
    m=market();m.atr14_pct=atr
    result=advise_grid(None,m,holding())
    assert "suggested_base_price" not in result
    assert result["candidate_buy_quantity"] is None


def test_report_has_account_roles_exits_and_no_retired_outputs():
    ps=[holding(),holding("159781")]
    recs=[recommend(next((p for p in ps if p.code==code),None),None,market(code),ps) for code in [*TARGETS,"159781"]]
    gs=[advise_grid(None,market(r["code"]),next((p for p in ps if p.code==r["code"]),None),r["rule_decision"]) for r in recs]
    ai=build_ai_review_input(recs,gs)
    output=json.dumps(ai,ensure_ascii=False)
    assert "t_grid" not in output and "watchlist" not in output
    assert ai["schema"]["review_contract"] == ANALYSIS_CONTRACT
    html=render_html("TEST ONLY - 无实时账户数据",recs,gs,{}, {})
    for word in ["账户总览","目标组合","现有持仓管理","成长 40%","价值 60%","待核验"]:
        assert word in html
    assert "T网格" not in html and "自选" not in html
    assert html.index('510500</span>') < html.index('159141</span>')
    assert "等待清仓成本核验" in html
    assert account_overview(recs,{"cash":5000})["available_cash"] is None


def test_ai_old_contract_cannot_enable_or_override_liquidation():
    p,m=holding("159781"),market("159781")
    rec=recommend(p,None,m,[p])
    assert normalize_host_ai_judgements({"review_contract":"etf_no_loss_v2","items":[{"code":p.code,"confidence":99}]},[rec])[p.code]["enabled"] is False
    attached=attach_ai_judgements([rec],{p.code:{"enabled":True,"judgement":"立即亏损清仓"}})
    assert "立即亏损清仓" not in json.dumps(attached,ensure_ascii=False)
    assert attached[0]["action_quantity"] is None


def test_pair_overweight_buy_is_paused_without_forcing_sale():
    ps=[holding("159259",value=9000),holding("159263",value=1000)]
    rec=recommend(ps[0],None,market("159259"),ps)
    assert rec["position_action"] == "WAIT_PAIR_BALANCE"
    assert "买入" in rec["rule_decision"]["blocked_actions"]
    assert rec["candidate_liquidation_quantity"] is None
    g=GridConfig("159259","测试",True,buy_quantity=200,sell_quantity=100)
    result=advise_grid(g,market("159259"),ps[0],rec["rule_decision"])
    assert result["candidate_buy_quantity"] is None
    assert result["buy_execution_status"] == "DISABLED"


def test_collect_never_visits_or_requires_watchlist(tmp_path,monkeypatch):
    from etfmate.browser import ths_account
    class Session:
        def __init__(self,*args): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def screenshot(self,*args): pass
        def navigate(self,url):
            raise AssertionError("Unexpected navigation: "+url)
    monkeypatch.setattr(ths_account,"WebAccessSession",Session)
    monkeypatch.setattr(ths_account,"require_login",lambda *args: None)
    monkeypatch.setattr(ths_account.time,"sleep",lambda *args: None)
    monkeypatch.setattr(ths_account,"_collect_tab_snapshot",lambda *args: {"text":"","scroll_complete":True})
    monkeypatch.setattr(ths_account,"_click_tab",lambda *args: None)
    monkeypatch.setattr(ths_account,"_records_from_snapshot",lambda *args: [])
    monkeypatch.setattr(ths_account,"extract_watchlist",lambda *args: (_ for _ in ()).throw(AssertionError("Retired watchlist collector was called")))
    result=ths_account.collect(tmp_path,tmp_path / "collect-test")
    assert "watchlist" not in result and "watchlist_snapshot" not in result
    assert set(result["trade_snapshots"]) == {"本月","近三月","近半年","今年","自定义"}


def test_folded_trade_review_keeps_cashflows_separate_from_returns():
    html=render_html("TEST ONLY",[],[],{"periods":[{"period":"近7日复盘","trade_count":3,"buy_amount":1000,"sell_amount":800}]})
    assert "近7日复盘" in html and "800.00" in html
    assert "卖出金额是成交回款，不等于收益" in html


@pytest.mark.parametrize("code", ["159781","510300","159915"])
def test_exit_cost_gap_does_not_erase_old_holding_partial_sell_advice(code):
    p,m=holding(code),market(code)
    rec=recommend(p,None,m,[p])
    result=advise_grid(None,m,p,rec["rule_decision"])
    assert rec["sell_policy"]["status"] == "PENDING_COST_BASIS"
    assert rec["position_action"] == "MANAGE_EXISTING"
    assert result["grid_mode"] == "TRANSITION_MANAGEMENT"
    assert result["candidate_sell_quantity"] == 200
    assert result["first_sell_reference_price"] > m.last_price
    assert result["sell_policy"]["sale_scope"] == "PARTIAL"
    assert result["sell_policy"]["sell_allowed"] is True
    assert result["candidate_buy_quantity"] is None
    assert result["conditional_buyback_quantity"] == 100
    assert result["buy_execution_status"] == "WAIT_EXECUTED_PROCEEDS"
    assert result["liquidation_policy"]["sell_allowed"] is False


def test_weak_legacy_still_has_rebound_exit_but_no_buyback():
    p,m=holding("159781"),market("159781")
    result=advise_grid(None,m,p,{"risk_level":"HIGH","blocked_actions":["买入"]})
    assert result["candidate_sell_quantity"] == 200
    assert result["conditional_buyback_quantity"] is None
    assert result["buy_execution_status"] == "DISABLED"


def test_transition_keeps_all_capital_and_does_not_preallocate_unfilled_proceeds():
    p=holding("159781")
    recs=[recommend(p,None,market(p.code),[p]),recommend(None,None,market("159259"),[p])]
    overview=account_overview(recs,{"total_asset":10000,"available_cash":1000})
    assert overview["external_cash_flow_policy"] == "NO_DEPOSITS_NO_WITHDRAWALS"
    assert overview["available_cash"] == 1000
    funding=recs[1]["funding_plan"]
    assert funding["allow_existing_cash"] is True
    assert funding["primary_future_source"] == "EXECUTED_LEGACY_PROCEEDS"
    assert funding["count_unfilled_proceeds"] is False
    assert funding["priority"] == "LEGACY_RECOVERY_FIRST"
    assert funding["requires_legacy_reserve_first"] is True
    assert funding["target_funding_scope"] == "VERIFIED_SURPLUS_AFTER_LEGACY_RESERVE"
    assert overview["funding_priority"] == funding["priority"]
    assert recs[1]["action_quantity"] is None
    grids=[advise_grid(None,market(p.code),p,recs[0]["rule_decision"])]
    html=render_html("TEST ONLY",recs,grids,{})
    assert html.index('id="exits"') < html.index('id="targets"')
    assert "反弹分批卖出" in html and "等待真实卖出回款" in html


def test_cash_balance_label_is_collected_without_claiming_spendable_cash():
    from etfmate.browser.ths_account import _account_summary_from_snapshot
    summary = _account_summary_from_snapshot({"text": "总资产\n69445.98\n现金余额\n6365.98\n持仓列表"}, [])
    assert summary["cash"] == 6365.98
    assert summary.get("available_cash") is None
