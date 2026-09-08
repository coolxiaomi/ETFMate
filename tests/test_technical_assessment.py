from dataclasses import asdict, replace

import pandas as pd
import pytest

from etfmate.analysis.account_strategy import ANALYSIS_CONTRACT
from etfmate.analysis.ai_advisor import build_ai_review_input, normalize_host_ai_judgements
from etfmate.analysis.data_quality import build_analysis_data_quality_report
from etfmate.analysis.grid_advisor import advise_grid
from etfmate.analysis.recommendation import recommend
from etfmate.analysis.technical_assessment import assess_technical
from etfmate.market.indicators import enrich_indicators
from etfmate.market import providers
from etfmate.report.daily_report import render_html
from test_account_strategy import holding, market
from test_data_quality import _account, _grids


def recovery(code="510500"):
    return replace(market(code), signal_close=1.10, signal_date="2026-09-07", rsi6=48,
                   rsi14=38, bias12=-2, bias24=-4, previous_rsi6=31, recent_oversold_count5=2)


def test_same_atr_different_signals_change_both_gate_and_parameters():
    strong = market()
    weak = replace(strong, last_price=.85, ma5=.9, ma10=.95, ma5_slope_3=-.01,
                   bias5_ratio=-.055, rsi6=20, boll_position=.1,
                   vol_ratio_1_5=.8, vol_ratio_5_20=.8)
    p = holding()
    r = recommend(p, None, weak, [p])
    assert r["technical_assessment"]["status"] == "OVERSOLD_UNCONFIRMED"
    assert "买入" in r["rule_decision"]["blocked_actions"]
    base = advise_grid(None, strong, p)
    result = advise_grid(None, weak, p, r["rule_decision"])
    assert result["parameter_plan"]["buy_fall_pct"] > base["parameter_plan"]["buy_fall_pct"]
    assert result["parameter_plan"]["buy_rebound_pct"] > base["parameter_plan"]["buy_rebound_pct"]
    assert result["parameter_plan"]["sell_rise_pct"] < base["parameter_plan"]["sell_rise_pct"]
    assert result["candidate_buy_quantity"] is None
    assert result["grid_execution_status"] == "DO_NOT_ENABLE"
    assert result["candidate_sell_quantity"] > 0
    assert result["suggested_buy_quantity"] is None


def test_recovery_requires_prior_oversold_and_current_same_source_confirmation():
    m = recovery()
    assert assess_technical(m)["status"] == "OVERSOLD_RECOVERY"
    for changes in ({"recent_oversold_count5": None}, {"recent_oversold_count5": 0},
                    {"recent_oversold_count5": 6}, {"recent_oversold_count5": 1.5}, {"previous_rsi6": -1},
                    {"previous_rsi6": 50}, {"signal_close": None},
                    {"signal_close": .9}, {"vol_ratio_1_5": .8}):
        assert assess_technical(replace(m, **changes))["status"] != "OVERSOLD_RECOVERY"
    # A live quote above MA5 cannot repair a weak historical daily sample.
    assert assess_technical(replace(m, last_price=2, signal_close=.9))["status"] != "OVERSOLD_RECOVERY"
    result = advise_grid(None, m, holding())
    assert result["parameter_plan"]["buy_fall_pct"] == 2.8
    assert result["parameter_plan"]["buy_rebound_pct"] > .3
    assert result["suggested_buy_quantity"] is None


@pytest.mark.parametrize("changes", [{"rsi6": 80}, {"bias5_ratio": .07}, {"boll_position": .96},
                                      {"bias12": 8}, {"bias24": 9}])
def test_overheat_cannot_be_bought_as_oversold_recovery(changes):
    m = replace(recovery(), **changes)
    assert assess_technical(m)["status"] == "OVERHEATED"
    assert advise_grid(None, m, holding())["candidate_buy_quantity"] is None


@pytest.mark.parametrize("changes", [{"vol_ratio_1_5": .8}, {"vol_ratio_5_20": .8}, {"ma60": 1.2}])
def test_mixed_evidence_remains_conditional_without_claiming_confirmation(changes):
    t = assess_technical(replace(market(), **changes))
    assert t["status"] == "MIXED"
    assert t["buy_gate"] == "CONDITIONAL"
    assert t["conflicts"]


@pytest.mark.parametrize("field,value", [("rsi6", None), ("rsi6", float("nan")), ("ma5", float("inf")),
                                        ("ma5", 0), ("vol_ratio_1_5", -1), ("rsi6", 101),
                                        ("boll_position", 2), ("bias5_ratio", float("nan"))])
def test_invalid_core_data_degrades_without_buy_permission(field, value):
    m = replace(market(), **{field: value})
    assert assess_technical(m)["status"] == "INSUFFICIENT"
    r = recommend(holding(), None, m)
    result = advise_grid(None, m, holding(), r["rule_decision"])
    assert result["grid_execution_status"] == "DO_NOT_ENABLE"
    assert result["candidate_buy_quantity"] is None


def test_zero_rsi_is_real_oversold_evidence_not_missing():
    m = replace(market(), rsi6=0, bias5_ratio=-.04, boll_position=0)
    t = assess_technical(m)
    assert t["status"] == "OVERSOLD_UNCONFIRMED"
    assert "rsi6" not in t["missing_fields"]


def test_buy_conditions_only_list_unmet_confirmation_requirements():
    m = replace(market(), ma20=1.2, ma5_slope_3=-.01, vol_ratio_5_20=.8)
    t = assess_technical(m)
    assert t["status"] == "WEAK"
    assert "站回MA5" not in t["buy_condition"]  # Price is already above it.
    assert "MA5斜率转正" in t["buy_condition"]
    assert "5日/20日量比≥0.9" in t["buy_condition"]
    hot = assess_technical(replace(market(), rsi6=80))
    assert hot["buy_condition"] == "等待RSI6<75后复评。"


def test_technical_multiplier_cannot_create_a_nonpositive_buy_price():
    m = replace(market(), atr14_pct=65, rsi6=80)
    result = advise_grid(None, m, holding())
    assert result["parameter_plan"] is None
    assert result["grid_execution_status"] == "DO_NOT_ENABLE"
    assert result["candidate_buy_quantity"] is None


@pytest.mark.parametrize("code", ["510500", "159781", "159259"])
def test_recovery_never_overrides_portfolio_risk_or_inventory(code):
    m, p = recovery(code), holding(code)
    p.position_pct = 90
    rec = recommend(p, None, m, [p])
    result = advise_grid(None, m, p, rec["rule_decision"])
    assert rec["technical_assessment"]["status"] == "OVERSOLD_RECOVERY"
    assert result["candidate_buy_quantity"] is None
    assert not result.get("conditional_buyback_quantity")
    assert result["grid_execution_status"] == "DO_NOT_ENABLE"
    assert result["candidate_sell_quantity"] <= p.quantity - result["suggested_min_base_quantity"]
    high = advise_grid(None, m, p, {"high_risk": True})
    assert high["candidate_buy_quantity"] is None
    assert not high.get("conditional_buyback_quantity")


def test_history_uses_previous_five_rows_and_is_causal():
    closes = [1 + i * .002 for i in range(65)] + [1.10, 1.07, 1.04, 1.01, .98, .96, 1.0, 1.04]
    df = pd.DataFrame({"close": closes, "open": closes, "high": [c+.01 for c in closes],
                       "low": [c-.01 for c in closes], "volume": [1000]*len(closes)})
    full = enrich_indicators(df)
    index = 72
    history = full.iloc[index-5:index]
    expected = ((history.rsi6 <= 30) & ((history.bias5_ratio <= -.03) | (history.boll_position <= .2))).sum()
    assert expected > 0
    assert full.iloc[index].recent_oversold_count5 == expected
    pd.testing.assert_frame_equal(full.iloc[:index+1], enrich_indicators(df.iloc[:index+1]))
    assert pd.isna(full.iloc[10].recent_oversold_count5)


def test_snapshot_carries_daily_evidence_separately_from_quote(monkeypatch):
    df = pd.DataFrame({"datetime": pd.bdate_range(end="2026-09-07", periods=80).strftime("%Y-%m-%d"), "close": [1+i*.001 for i in range(80)],
                       "open": [1]*80, "high": [1.1]*80, "low": [.9]*80,
                       "volume": [1000]*80, "amount": [1e8]*80})
    monkeypatch.setattr(providers, "tencent_quote", lambda codes: {codes[0]: {"last_price": 2, "quote_time": "2026-09-08T10:38:54+08:00"}})
    monkeypatch.setattr(providers, "baidu_daily_kline", lambda code: df)
    monkeypatch.setattr(providers, "tencent_daily_kline", lambda code: df.assign(volume=lambda frame: frame.volume / 100))
    m = providers.build_market_snapshot("510500")
    assert m.signal_close == df.close.iloc[-1] and m.last_price == 2
    assert m.signal_date == "2026-09-07"
    assert m.signal_is_complete is True
    assert m.previous_rsi6 == 100 and m.recent_oversold_count5 == 0


def test_report_keeps_per_symbol_evidence_without_public_explanations():
    ps = [holding(), holding("159781")]
    recs = [recommend(p, None, recovery(p.code), ps) for p in ps]
    gs = [advise_grid(None, recovery(p.code), p, recs[i]["rule_decision"]) for i, p in enumerate(ps)]
    html = render_html("TEST · 无实时账户数据", recs, gs, {})
    assert "共同执行规则与指标口径" not in html
    assert "单位：份、¥、%" not in html
    assert "待核验净投入" in html
    assert html.count("BIAS5/12/24") == 2 and html.count("RSI6/14") == 2
    assert html.count("样本日量/5日均量") == 2
    assert "最终退出不代表现在只等清仓" not in html
    assert "即使清仓成本暂未核实" not in html
    assert "前5个样本超卖 2 次" in html
    ai = build_ai_review_input(recs, gs)
    assert ai["items"][0]["technical_assessment"] == recs[0]["technical_assessment"]


def test_v5_and_fake_version_upgrade_are_rejected():
    p, m = holding("510300"), recovery("510300")
    rec = recommend(p, None, m, [p])
    grid = advise_grid(None, m, p, rec["rule_decision"])
    analysis = {"analysis_contract": "etf_account_transition_v5", "market_snapshots": [asdict(m)],
                "recommendations": [rec], "grid_advices": [grid]}
    result = build_analysis_data_quality_report(_account(), _grids(), analysis)
    assert any("分析契约已更新" in e for e in result["fatal_errors"])
    analysis["analysis_contract"] = ANALYSIS_CONTRACT
    del rec["rule_decision"]["technical_assessment"]
    result = build_analysis_data_quality_report(_account(), _grids(), analysis)
    assert any("综合技术依据" in e for e in result["fatal_errors"])
    assert not normalize_host_ai_judgements({"review_contract": "etf_account_transition_v5", "items": []}, [rec])[p.code]["enabled"]


def test_gate_rejects_grid_that_bypasses_technical_wait():
    m = replace(market("510300"), rsi6=80)
    p = holding(m.code)
    rec = recommend(p, None, m, [p])
    grid = advise_grid(None, m, p, rec["rule_decision"])
    grid["candidate_buy_quantity"] = 100
    analysis = {"analysis_contract": ANALYSIS_CONTRACT, "market_snapshots": [asdict(m)],
                "recommendations": [rec], "grid_advices": [grid]}
    result = build_analysis_data_quality_report(_account(), _grids(), analysis)
    assert any("绕过未确认" in e for e in result["fatal_errors"])
