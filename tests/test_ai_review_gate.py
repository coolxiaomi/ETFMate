from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from etfmate import cli
from etfmate.analysis.ai_advisor import (
    AI_REVIEW_CONTRACT, ai_review_validation_errors, attach_ai_judgements,
    normalize_host_ai_judgements, review_input_for_analysis,
)
from etfmate.analysis.data_quality import DataQualityError, build_report_data_quality_report
from etfmate.storage.models import MarketSnapshot
from etfmate.storage.repository import read_json, write_json
from test_data_quality import _account, _grids, _snapshot


def _review_payload(review_input):
    return {
        "review_contract": AI_REVIEW_CONTRACT,
        **{key: review_input[key] for key in ("run_id", "review_id", "input_fingerprint")},
        "items": [{
            "code": row["code"], "review_status": "PASS", "ai_action": "保持条件计划",
            "confidence": 65, "judgement": "测试复核：当前动作与输入的价格、库存及清仓约束一致。",
            "conflicts": [], "guardrails": ["完整周期净投入未核验时不能最终清仓"],
            "final_bias": "保持规则建议",
        } for row in review_input["items"]],
    }


def _prepare_analysis(tmp_path, monkeypatch):
    run_id = "TEST-AI-REVIEW"
    write_json(tmp_path / "data/raw/ths" / run_id / "account.json", _account())
    write_json(tmp_path / "data/raw/touker" / run_id / "grids.json", _grids())
    monkeypatch.setattr(cli, "build_market_snapshot", lambda code: MarketSnapshot(**_snapshot(code), pct_chg=0, volume=1000000))
    cli.run_analyze(tmp_path, run_id)
    folder = tmp_path / "data/raw/market" / run_id
    return run_id, read_json(folder / "analysis.json"), read_json(folder / "ai_review_input.json")


def _write_valid_review(tmp_path, run_id):
    folder = tmp_path / "data/raw/market" / run_id
    review_input = read_json(folder / "ai_review_input.json")
    source = tmp_path / "test-review.json"
    write_json(source, _review_payload(review_input))
    cli.run_ai_attach(tmp_path, run_id, source)


def test_formal_report_requires_complete_bound_ai_review(tmp_path, monkeypatch):
    run_id, analysis, _ = _prepare_analysis(tmp_path, monkeypatch)
    folder = tmp_path / "data/raw/market" / run_id
    analysis_quality = read_json(folder / "data_quality.json")
    assert analysis_quality["status"] == "PASS"
    assert analysis_quality["formal_report_ready"] is False
    assert all(not row["enabled"] for row in analysis["ai_judgements"].values())
    with pytest.raises(DataQualityError, match="本次复核未生成"):
        cli.run_report(tmp_path, run_id)
    assert not (tmp_path / "data/reports").exists()
    assert read_json(folder / "data_quality.json")["status"] == "FAIL"
    _write_valid_review(tmp_path, run_id)
    cli.run_report(tmp_path, run_id)
    quality = read_json(folder / "data_quality.json")
    assert quality["formal_report_ready"] is True
    assert quality["metrics"]["ai_review_pass_count"] == len(analysis["recommendations"])


def test_submitted_order_evidence_change_requires_new_ai_review(tmp_path, monkeypatch):
    run_id, analysis, review_input = _prepare_analysis(tmp_path, monkeypatch)
    account = read_json(tmp_path / "data/raw/ths" / run_id / "account.json")
    grids = read_json(tmp_path / "data/raw/touker" / run_id / "grids.json")
    grids["submitted_orders"] = {
        "contract": "touker_submitted_audit_v1", "captured_at": "2026-09-08T12:30:00+08:00",
        "selected_tab": "已委托", "selection_verified": True, "complete": False,
        "records": [{"code": "159687", "date": "2026-09-07", "time": "09:30:28",
                     "side": "卖出", "quantity": 500, "price": 1.877,
                     "status": "已成交，成交价1.8770"}],
    }
    changed = review_input_for_analysis(account, grids, analysis)
    assert changed["input_fingerprint"] != review_input["input_fingerprint"]
    submitted = changed["context"]["execution_review"]["submitted_orders"]
    assert submitted["observed_count"] == 1
    assert submitted["status_counts"]["FILLED"] == 1
    assert ai_review_validation_errors(_review_payload(review_input), analysis["recommendations"], changed)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown", "empty", "nonfinite", "wrong_run", "wrong_fingerprint"])
def test_incomplete_or_unbound_review_is_not_enabled(tmp_path, monkeypatch, mutation):
    _, analysis, review_input = _prepare_analysis(tmp_path, monkeypatch)
    payload = _review_payload(review_input)
    if mutation == "missing":
        payload["items"].pop()
    elif mutation == "duplicate":
        payload["items"].append(deepcopy(payload["items"][0]))
    elif mutation == "unknown":
        payload["items"][0]["code"] = "999999"
    elif mutation == "empty":
        payload["items"][0]["judgement"] = " "
    elif mutation == "nonfinite":
        payload["items"][0]["confidence"] = float("inf")
    elif mutation == "wrong_run":
        payload["run_id"] = "OLD"
    else:
        payload["input_fingerprint"] = "old"
    assert ai_review_validation_errors(payload, analysis["recommendations"], review_input)
    result = normalize_host_ai_judgements(payload, analysis["recommendations"], review_input)
    assert all(row["enabled"] is False for row in result.values())


def test_ai_objections_remain_auditable_and_block_formal_report(tmp_path, monkeypatch):
    run_id, analysis, review_input = _prepare_analysis(tmp_path, monkeypatch)
    payload = _review_payload(review_input)
    row = payload["items"][0]
    row.update(review_status="REVISE", judgement="页面已回本却仍要求等待反弹", conflicts=["标题与当前价格阶段矛盾"], final_bias="需要人工确认")
    source = tmp_path / "review.json"
    write_json(source, payload)
    cli.run_ai_attach(tmp_path, run_id, source)
    saved = read_json(tmp_path / "data/raw/market" / run_id / "analysis.json")
    item = next(rec for rec in saved["recommendations"] if rec["code"] == row["code"])
    assert item["ai_judgement"]["judgement"] == row["judgement"]
    assert item["ai_judgement"]["conflicts"] == row["conflicts"]
    assert item["ai_judgement"]["execution_authority"] is False
    assert item["action_quantity"] is None
    with pytest.raises(DataQualityError, match="未解决"):
        cli.run_report(tmp_path, run_id)


def test_reanalyze_invalidates_even_same_run_old_review(tmp_path, monkeypatch):
    run_id, _, review_input = _prepare_analysis(tmp_path, monkeypatch)
    _write_valid_review(tmp_path, run_id)
    cli.run_analyze(tmp_path, run_id)
    folder = tmp_path / "data/raw/market" / run_id
    new_input = read_json(folder / "ai_review_input.json")
    assert new_input["review_id"] != review_input["review_id"]
    with pytest.raises(DataQualityError, match="与本次分析不一致"):
        cli.run_report(tmp_path, run_id)


@pytest.mark.parametrize("changed_source", ["account", "grid", "market", "action"])
def test_source_or_action_change_invalidates_review(tmp_path, monkeypatch, changed_source):
    _, analysis, review_input = _prepare_analysis(tmp_path, monkeypatch)
    account, grids = _account(), _grids()
    if changed_source == "account":
        account["account_summary"]["cash"] += 10
    elif changed_source == "grid":
        grids["grids"][0]["base_price"] += 0.1
    elif changed_source == "market":
        analysis["market_snapshots"][0]["last_price"] += 0.1
    else:
        analysis["grid_advices"][0]["parameter_plan"]["sell_quantity"] += 100
    quality = build_report_data_quality_report(account, grids, analysis, _review_payload(review_input))
    assert quality["status"] == "FAIL"
    assert any("已变化" in error or "不一致" in error or "input_fingerprint" in error for error in quality["fatal_errors"])


@pytest.mark.parametrize("mutation", ["missing_path", "missing_partial", "wrong_current_price", "wrong_trigger", "false_fill_path", "all_inventory"])
def test_v8_analysis_checks_action_stage_and_price_arithmetic(tmp_path, monkeypatch, mutation):
    from etfmate.analysis.data_quality import build_analysis_data_quality_report
    from etfmate.analysis import inventory_plan
    original_rule = inventory_plan.get_instrument_rule
    monkeypatch.setattr(inventory_plan, "get_instrument_rule", lambda code:
                        {**original_rule(code), "settlement": "T1"} if code == "510300" else original_rule(code))
    _, analysis, _ = _prepare_analysis(tmp_path, monkeypatch)
    grid = next(row for row in analysis["grid_advices"] if row["code"] == "510300")
    assert grid["partial_sell_plan"]["status"] == "CURRENT_PARTIAL_REVIEW"
    if mutation == "missing_path":
        grid.pop("price_plan")
    elif mutation == "missing_partial":
        grid.pop("partial_sell_plan")
    elif mutation == "wrong_current_price":
        grid["partial_sell_plan"]["reference_price"] += 0.1
    elif mutation == "wrong_trigger":
        grid["price_plan"]["buy_trigger_price"] += 0.1
    elif mutation == "false_fill_path":
        grid["price_plan"]["path_evidence"] = "ORDER_FILLED"
    else:
        grid["partial_sell_plan"]["candidate_quantity"] = 1000
    quality = build_analysis_data_quality_report(_account(), _grids(), analysis)
    assert quality["status"] == "FAIL"
    assert any("510300" in error for error in quality["fatal_errors"])


@pytest.mark.parametrize("mutation", ["old_analysis", "old_quote", "future_quote", "missing_quote", "future_signal", "incomplete_signal"])
def test_formal_report_rejects_unverifiable_or_stale_data_time(tmp_path, monkeypatch, mutation):
    _, analysis, _ = _prepare_analysis(tmp_path, monkeypatch)
    now = datetime.now(timezone(timedelta(hours=8)))
    snapshot = analysis["market_snapshots"][0]
    if mutation == "old_analysis":
        analysis["analysis_time"] = "2000-01-01 10:00:00"
    elif mutation == "old_quote":
        snapshot["quote_time"] = "2000-01-01T15:00:00+08:00"
    elif mutation == "future_quote":
        snapshot["quote_time"] = (now + timedelta(days=1)).isoformat()
    elif mutation == "missing_quote":
        snapshot.pop("quote_time")
    elif mutation == "future_signal":
        snapshot["signal_date"] = (now + timedelta(days=1)).date().isoformat()
    else:
        snapshot["signal_is_complete"] = False
    # Rebinding cannot make an invalid source time valid.
    review_input = review_input_for_analysis(_account(), _grids(), analysis)
    analysis["ai_review_input_fingerprint"] = review_input["input_fingerprint"]
    quality = build_report_data_quality_report(_account(), _grids(), analysis, _review_payload(review_input), now=now)
    assert quality["status"] == "FAIL"
    assert any("时间" in error or "日线" in error for error in quality["fatal_errors"])


def test_closed_market_friday_data_is_not_rejected_on_monday(tmp_path, monkeypatch):
    from etfmate.analysis.action_plan import describe_action_plan
    from etfmate.analysis.decision_review import build_decision_review
    from etfmate.analysis.inventory_plan import build_inventory_plan
    _, analysis, _ = _prepare_analysis(tmp_path, monkeypatch)
    monday = datetime(2026, 9, 14, 8, 30, tzinfo=timezone(timedelta(hours=8)))
    analysis["analysis_time"] = monday.isoformat()
    analysis["inventory_plan"] = build_inventory_plan(_account(), monday.date())
    for grid in analysis["grid_advices"]:
        grid["inventory"] = analysis["inventory_plan"].get(grid["code"], {})
    for row in analysis["market_snapshots"] + analysis["recommendations"]:
        row.update(quote_time="2026-09-11T15:00:00+08:00", signal_date="2026-09-11")
    grids = {row["code"]: row for row in analysis["grid_advices"]}
    analysis["action_plans"] = {row["code"]: describe_action_plan(row, grids[row["code"]])
                                for row in analysis["recommendations"]}
    analysis["decision_review"] = build_decision_review(
        analysis["recommendations"], analysis["grid_advices"],
        _account()["account_summary"], analysis["funding_plan"],
    )
    review_input = review_input_for_analysis(_account(), _grids(), analysis)
    analysis["ai_review_input_fingerprint"] = review_input["input_fingerprint"]
    quality = build_report_data_quality_report(_account(), _grids(), analysis, _review_payload(review_input), now=monday)
    assert quality["status"] == "PASS"
