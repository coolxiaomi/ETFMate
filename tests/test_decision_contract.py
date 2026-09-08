"""The rendered decision limits must be part of the validated analysis and AI input."""
from copy import deepcopy

import pytest

from etfmate import cli
from etfmate.analysis.ai_advisor import ai_review_validation_errors, review_input_for_analysis
from etfmate.analysis.data_quality import DataQualityError, build_analysis_data_quality_report
from etfmate.storage.repository import read_json, write_json
from test_ai_review_gate import _prepare_analysis, _review_payload, _write_valid_review
from test_data_quality import _account, _grids


def test_new_analysis_persists_decision_limits_and_passes_same_context_to_ai(tmp_path, monkeypatch):
    _, analysis, review = _prepare_analysis(tmp_path, monkeypatch)
    assert analysis["analysis_contract"] == "etf_account_transition_v10"
    decision = analysis["decision_review"]
    assert review["context"]["decision_review"] == decision
    assert decision["position_threshold"]["forced_reduction"] is False
    assert decision["position_threshold"]["drawdown_limit"] is False
    assert decision["cost_assumptions"]["returns_validated"] is False
    assert decision["quantity_policy"]["risk_optimized"] is False
    for item in review["items"]:
        action = analysis["action_plans"][item["code"]]
        assert item["action_plan"] == action
        assert action["execution_authorized"] is False
        assert action["quantity_basis"]["risk_optimized"] is False
        assert action["contingency_plan"]["automatic_actions_authorized"] is False
        assert action["condition_plan"]["follow_up_policy"]["execution_authorized"] is False


@pytest.mark.parametrize("mutation", [
    "missing_review", "wrong_review_type", "force_reduction", "optimized_quantity",
    "guaranteed_return", "made_up_scenario", "missing_actions", "wrong_actions_type",
    "missing_quantity_basis", "automatic_retry",
])
def test_gate_rejects_omitted_or_changed_decision_limits_even_with_current_version(tmp_path, monkeypatch, mutation):
    _, analysis, _ = _prepare_analysis(tmp_path, monkeypatch)
    changed = deepcopy(analysis)
    if mutation == "missing_review":
        changed.pop("decision_review")
    elif mutation == "wrong_review_type":
        changed["decision_review"] = []
    elif mutation == "force_reduction":
        changed["decision_review"]["position_threshold"]["forced_reduction"] = True
    elif mutation == "optimized_quantity":
        changed["decision_review"]["quantity_policy"]["risk_optimized"] = True
    elif mutation == "guaranteed_return":
        changed["decision_review"]["cost_assumptions"]["returns_validated"] = True
    elif mutation == "made_up_scenario":
        changed["decision_review"]["sell_scenarios"].append({"code": "510300", "estimated_proceeds": 999999})
    elif mutation == "missing_actions":
        changed.pop("action_plans")
    elif mutation == "wrong_actions_type":
        changed["action_plans"] = []
    else:
        action = next(iter(changed["action_plans"].values()))
        if mutation == "missing_quantity_basis":
            action.pop("quantity_basis")
        else:
            action["condition_plan"]["follow_up_policy"]["execution_authorized"] = True
    quality = build_analysis_data_quality_report(_account(), _grids(), changed)
    assert quality["status"] == "FAIL"
    assert any("decision_review" in msg or "action_plans" in msg for msg in quality["fatal_errors"])


def test_decision_evidence_change_invalidates_previous_ai_review(tmp_path, monkeypatch):
    _, analysis, review = _prepare_analysis(tmp_path, monkeypatch)
    analysis["decision_review"]["unresolved_policies"][0]["impact"] = "修改后的风险处置条件"
    changed = review_input_for_analysis(_account(), _grids(), analysis)
    assert changed["input_fingerprint"] != review["input_fingerprint"]
    assert ai_review_validation_errors(_review_payload(review), analysis["recommendations"], changed)


def test_v9_cannot_reuse_a_new_review_to_render_a_formal_report(tmp_path, monkeypatch):
    run_id, analysis, _ = _prepare_analysis(tmp_path, monkeypatch)
    _write_valid_review(tmp_path, run_id)
    path = tmp_path / "data/raw/market" / run_id / "analysis.json"
    analysis = read_json(path)
    analysis["analysis_contract"] = "etf_account_transition_v9"
    write_json(path, analysis)
    with pytest.raises(DataQualityError, match="分析契约已更新"):
        cli.run_report(tmp_path, run_id)
    assert not (tmp_path / "data/reports" / f"{run_id}-etf-realtime.html").exists()


def test_report_receives_the_validated_decision_and_action_structures(tmp_path, monkeypatch):
    run_id, analysis, _ = _prepare_analysis(tmp_path, monkeypatch)
    _write_valid_review(tmp_path, run_id)
    captured = {}

    def capture_report(path, date, recommendations, grid_advices, trade_review, data):
        captured.update(data)
        return path

    monkeypatch.setattr(cli, "write_report", capture_report)
    cli.run_report(tmp_path, run_id)
    assert captured["decision_review"] == analysis["decision_review"]
    assert captured["action_plans"] == analysis["action_plans"]


def test_sell_only_condition_is_rendered_as_a_review_item_not_a_buy_conflict(tmp_path, monkeypatch):
    from etfmate.analysis import inventory_plan
    from etfmate.report.daily_report import render_html

    original_rule = inventory_plan.get_instrument_rule
    monkeypatch.setattr(inventory_plan, "get_instrument_rule", lambda code:
                        {**original_rule(code), "settlement": "T1"} if code == "510300" else original_rule(code))
    _, analysis, _ = _prepare_analysis(tmp_path, monkeypatch)
    assert analysis["action_plans"]["510300"]["sell_quantity"] > 0
    html = render_html("TEST ONLY", analysis["recommendations"], analysis["grid_advices"], {}, {
        "account_summary": _account()["account_summary"],
        "funding_plan": analysis["funding_plan"],
        "decision_review": analysis["decision_review"],
        "conditions": [{"code": "510300", "condition_type": "sell_only", "enabled": True}],
    })
    assert "监控条件待核对 · 1 条" in html
    assert "先停用 1 条与本批次买入限制冲突" not in html
    assert "需调整的监控中条件单 · 1 条" not in html
