from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etfmate.analysis import rule_engine
from etfmate.analysis.grid_advisor import advise_grid
from etfmate.report.daily_report import _ai_judgement_html, render_html
from etfmate.storage.models import GridConfig, MarketSnapshot, Position


def _market() -> MarketSnapshot:
    return MarketSnapshot(
        code="159999",
        name="测试ETF",
        last_price=1.0,
        pct_chg=-1.0,
        volume=1000000,
        amount=100000000,
        ma5=1.0,
        ma10=1.0,
        ma20=1.0,
        ma60=1.1,
        kline_days=240,
    )


def _position(position_pct: float = 3.36) -> Position:
    return Position(
        code="159999",
        name="测试ETF",
        quantity=1000,
        cost_price=1.1,
        last_price=1.0,
        market_value=1000,
        pnl=-100,
        pnl_pct=-9.09,
        position_pct=position_pct,
    )


def test_high_risk_zero_target_should_not_be_downgraded_to_hold(monkeypatch):
    monkeypatch.setattr(
        rule_engine,
        "_trend_score",
        lambda market: {
            "score": 40,
            "name": "短线转弱",
            "level": "WEAK",
            "tags": [],
            "scores": {},
            "indicators": {},
            "data_sufficient": True,
            "evidence": ["测试趋势转弱"],
        },
    )
    monkeypatch.setattr(rule_engine, "_momentum_score", lambda market, all_markets: {"score": 0, "evidence": []})
    monkeypatch.setattr(rule_engine, "_risk_score", lambda market: {"score": 80, "evidence": ["测试高风险"]})

    decision = rule_engine.decide_position(_position(), None, _market(), [_position()], [_market()])

    assert decision["position_action"] in {"REDUCE", "RISK_REVIEW", "EXIT_SHORT_TERM"}
    assert decision["action"] != "持有"
    assert any("目标仓位为 0" in reason for reason in decision["reasons"])


def test_portfolio_limit_blocks_new_position(monkeypatch):
    monkeypatch.setattr(
        rule_engine,
        "_trend_score",
        lambda market: {
            "score": 90,
            "name": "强势进攻区",
            "level": "STRONG_ATTACK",
            "tags": [],
            "scores": {},
            "indicators": {},
            "data_sufficient": True,
            "evidence": ["测试强趋势"],
        },
    )
    monkeypatch.setattr(rule_engine, "_momentum_score", lambda market, all_markets: {"score": 90, "evidence": []})
    monkeypatch.setattr(rule_engine, "_risk_score", lambda market: {"score": 0, "evidence": []})
    existing = [
        Position("510500", "中证500ETF", 1000, 1, 1, 1000, 0, 0, position_pct=72),
    ]

    decision = rule_engine.decide_position(None, None, _market(), existing, [_market()])

    assert decision["position_action"] == "WATCH"
    assert decision["action"] == "观察"


def test_high_risk_zero_target_grid_must_not_keep_normal_buy_side():
    grid = GridConfig(
        code="159999",
        name="测试ETF",
        enabled=True,
        order_quantity=200,
        buy_fall_pct=3,
        sell_rise_pct=3,
    )
    advice = advise_grid(
        grid,
        _market(),
        _position(),
        rule_decision={
            "action": "风控复核",
            "position_action": "RISK_REVIEW",
            "risk_level": "HIGH",
            "trend_score": 25,
            "target_position_ratio": 0,
        },
    )

    assert advice["action"] in {"暂停买入侧", "只保留卖出", "人工复核"}
    assert advice["suggested_buy_quantity"] is None


def test_ai_disabled_renders_compact_status_only():
    html = _ai_judgement_html(
        {
            "ai_judgement": {
                "enabled": False,
                "confidence": 0,
                "judgement": "宿主 AI 尚未回写",
                "guardrails": ["占位护栏"],
            }
        }
    )

    assert "AI复核未启用" in html
    assert "占位护栏" not in html


def test_report_renders_rule_versions():
    html = render_html("2026-06-23 14:45:08", [], [], {}, {})

    assert "规则 2026.06.23-v1" in html
    assert "评分 score-2026.06" in html
    assert "网格 grid-2026.06" in html
    assert "风控 risk-2026.06" in html
