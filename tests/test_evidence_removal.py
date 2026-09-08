from __future__ import annotations

import json

import pytest

from etfmate.analysis.ai_advisor import (
    AI_REVIEW_CONTRACT,
    build_ai_review_input,
    load_host_ai_judgements,
    normalize_host_ai_judgements,
)
from etfmate.analysis.grid_advisor import advise_grid
from etfmate.analysis.recommendation import recommend
from etfmate.report.daily_report import render_html
from etfmate.storage.models import MarketSnapshot, Position


def test_recommendation_grid_ai_and_report_without_layer_scoring():
    market = MarketSnapshot(
        code="510300", name="沪深300ETF", last_price=3.9, pct_chg=0,
        volume=1000000, amount=300000000, ma5=3.85, ma10=3.8,
        ma20=3.7, ma60=3.6, atr14_pct=2, rsi6=55, kline_days=120,
        data_quality="quote:test;kline:test",
    )
    position = Position("510300", "沪深300ETF", 1000, 3.5, 3.9, 3900, 400, 11.4, position_pct=3.9)
    item = recommend(position, None, market, [position], [market])
    grid = advise_grid(None, market, position, rule_decision=item["rule_decision"])
    ai_input = build_ai_review_input([item], [grid])
    assert item["action"] == item["rule_decision"]["action"]
    assert ai_input["schema"]["review_contract"] == AI_REVIEW_CONTRACT
    assert "evidence" not in ai_input["items"][0]
    output = json.dumps([item, grid, ai_input], ensure_ascii=False)
    html = render_html("TEST ONLY", [item], [grid], {}, {})
    for text in (output, html):
        assert "七层" not in text
        assert "多层证据" not in text
        assert "layered_" not in text
    assert "现有持仓管理" in html


def test_legacy_ai_judgement_is_not_reused_after_evidence_removal():
    recs = [{"code": "510300"}]
    old = {"items": [{"code": "510300", "judgement": "旧分析", "confidence": 90}]}
    result = normalize_host_ai_judgements(old, recs)
    assert result["510300"]["enabled"] is False
    assert "重新复核" in result["510300"]["judgement"]
    from test_ai_review_gate import _review_payload
    review_input = build_ai_review_input(recs, [], run_id="TEST", review_id="review")
    current = _review_payload(review_input)
    assert normalize_host_ai_judgements(current, recs)["510300"]["enabled"] is True


def test_ai_attach_preserves_current_contract_and_rejects_old_input(tmp_path):
    from etfmate.cli import run_ai_attach
    from etfmate.storage.repository import write_json

    from pytest import MonkeyPatch
    from test_ai_review_gate import _prepare_analysis, _review_payload
    with MonkeyPatch.context() as patch:
        run_id, analysis, review_input = _prepare_analysis(tmp_path, patch)
    recs = analysis["recommendations"]
    source = tmp_path / "review.json"
    payload = _review_payload(review_input)
    write_json(source, payload)
    run_ai_attach(tmp_path, run_id, source)
    assert load_host_ai_judgements(tmp_path, run_id, recs)["510300"]["enabled"] is True
    write_json(source, {"items": []})
    with pytest.raises(RuntimeError, match="AI 输入契约已更新"):
        run_ai_attach(tmp_path, run_id, source)
    assert load_host_ai_judgements(tmp_path, run_id, recs)["510300"]["enabled"] is True
