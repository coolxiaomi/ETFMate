from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etfmate.analysis import rule_engine
from etfmate.analysis.grid_advisor import advise_grid
from etfmate.analysis.trade_reviewer import review_trade_periods
from etfmate.cli import _position as _cli_position
from etfmate.report.daily_report import _ai_judgement_html, _holding_view, render_html
from etfmate.storage.models import GridConfig, MarketSnapshot, Position, Trade


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
        Position("510500", "中证500ETF", 1000, 1, 1, 1000, 0, 0, position_pct=82, position_pct_source="ths_account_total_asset"),
    ]

    decision = rule_engine.decide_position(None, None, _market(), existing, [_market()])

    assert decision["position_action"] == "WATCH"
    assert decision["action"] == "观察"


def test_fallback_holding_pct_does_not_trigger_portfolio_hard_cap(monkeypatch):
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
        Position("510500", "中证500ETF", 1000, 1, 1, 1000, 0, 0, position_pct=100, position_pct_source="positions_market_value_fallback"),
    ]

    decision = rule_engine.decide_position(None, None, _market(), existing, [_market()])

    assert decision["position_action"] == "OPEN"
    assert decision["target_position_pct"] == 4
    assert any("资金仓位口径置信度低" in warning for warning in decision["risks"])


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
        layered_context={"confidence": 22, "total_score": -3},
    )

    assert advice["action"] in {"暂停买入侧", "只保留卖出", "人工复核"}
    assert advice["suggested_buy_quantity"] is None


def test_grid_confirmation_pct_uses_base_price_buckets_and_stays_equal():
    cases = [
        (0.99, 0.20),
        (1.50, 0.15),
        (2.50, 0.10),
        (4.00, 0.07),
        (6.00, 0.05),
        (8.50, 0.03),
    ]
    for base_price, expected in cases:
        grid = GridConfig(
            code="159999",
            name="测试ETF",
            enabled=True,
            base_price=base_price,
            order_quantity=200,
            buy_fall_pct=4,
            sell_rise_pct=4,
        )
        market = _market()
        market.last_price = base_price
        market.atr14_pct = 8.0

        advice = advise_grid(grid, market, _position(position_pct=2))

        assert advice["suggested_buy_rebound_pct"] == expected
        assert advice["suggested_sell_pullback_pct"] == expected


def test_existing_grid_keeps_reasonable_base_price():
    grid = GridConfig(
        code="159999",
        name="测试ETF",
        enabled=True,
        base_price=1.01,
        order_quantity=200,
        buy_fall_pct=3,
        buy_rebound_pct=0.5,
        sell_rise_pct=3,
        sell_pullback_pct=0.5,
        min_base_quantity=300,
        max_position_quantity=2000,
    )
    market = MarketSnapshot(
        code="159999",
        name="测试ETF",
        last_price=1.0,
        pct_chg=0.2,
        volume=1000000,
        amount=100000000,
        ma20=1.0,
        ma60=1.0,
        boll_mid=1.0,
        atr14_pct=2.0,
        kline_days=240,
    )

    advice = advise_grid(grid, market, _position(position_pct=3))

    assert advice["base_price_status"] == "维持现有基准"
    assert advice["suggested_base_price"] == 1.01
    assert advice["current_buy_rebound_pct"] == 0.5
    assert advice["current_sell_pullback_pct"] == 0.5


def test_existing_grid_adjusts_distorted_base_price():
    grid = GridConfig(
        code="159999",
        name="测试ETF",
        enabled=True,
        base_price=1.25,
        lower_price=0.9,
        upper_price=1.15,
        order_quantity=200,
        buy_fall_pct=3,
        sell_rise_pct=3,
    )
    market = MarketSnapshot(
        code="159999",
        name="测试ETF",
        last_price=1.0,
        pct_chg=0.2,
        volume=1000000,
        amount=100000000,
        ma20=1.01,
        ma60=1.02,
        boll_mid=1.0,
        atr14_pct=2.0,
        kline_days=240,
    )

    advice = advise_grid(grid, market, _position(position_pct=3))

    assert advice["base_price_status"] == "建议调整基准"
    assert advice["suggested_base_price"] != grid.base_price
    assert any("偏离" in reason or "失真" in reason for reason in advice["reasons"])


def test_profitable_upper_band_grid_does_not_move_base_to_current_price():
    grid = GridConfig(
        code="159999",
        name="测试ETF",
        enabled=True,
        base_price=1.0,
        order_quantity=200,
        buy_fall_pct=3,
        sell_rise_pct=3,
    )
    position = Position("159999", "测试ETF", 1000, 0.95, 1.08, 1080, 130, 13.68, position_pct=3)
    market = MarketSnapshot(
        code="159999",
        name="测试ETF",
        last_price=1.08,
        pct_chg=1.0,
        volume=1000000,
        amount=100000000,
        boll_upper=1.1,
        boll_mid=1.02,
        ma20=1.03,
        ma60=1.0,
        bias6=3.0,
        atr14_pct=2.0,
        kline_days=240,
    )

    advice = advise_grid(grid, market, position)

    assert advice["base_price_status"] == "维持现有基准"
    assert advice["suggested_base_price"] == 1.0
    assert advice["suggested_sell_quantity"] >= advice["suggested_buy_quantity"]


def test_profitable_strong_trend_grid_keeps_profit_room():
    grid = GridConfig(
        code="159999",
        name="测试ETF",
        enabled=True,
        base_price=1.0,
        order_quantity=200,
        buy_fall_pct=3,
        sell_rise_pct=3,
    )
    position = Position("159999", "测试ETF", 1000, 0.95, 1.08, 1080, 130, 13.68, position_pct=3)
    market = MarketSnapshot(
        code="159999",
        name="测试ETF",
        last_price=1.08,
        pct_chg=1.0,
        volume=1000000,
        amount=100000000,
        boll_upper=1.1,
        boll_mid=1.02,
        ma20=1.03,
        ma60=1.0,
        bias6=3.0,
        atr14_pct=2.0,
        kline_days=240,
    )

    advice = advise_grid(
        grid,
        market,
        position,
        rule_decision={
            "action": "持有",
            "position_action": "HOLD",
            "trend_score": 86,
            "risk_level": "LOW",
        },
    )

    assert advice["grid_purpose"] == "持仓网格"
    assert advice["suggested_sell_quantity"] == 200
    assert any("不因浮盈提前减仓" in reason or "继续盈利空间" in reason for reason in advice["reasons"])


def test_weak_loss_grid_does_not_keep_normal_buy_side():
    grid = GridConfig(
        code="159999",
        name="测试ETF",
        enabled=True,
        base_price=1.2,
        order_quantity=200,
        buy_fall_pct=3,
        sell_rise_pct=3,
    )
    position = Position("159999", "测试ETF", 1000, 1.15, 1.0, 1000, -150, -13.0, position_pct=6)
    market = MarketSnapshot(
        code="159999",
        name="测试ETF",
        last_price=1.0,
        pct_chg=-1.0,
        volume=1000000,
        amount=100000000,
        ma20=1.08,
        ma60=1.1,
        boll_mid=1.05,
        atr14_pct=2.0,
        kline_days=240,
    )

    advice = advise_grid(grid, market, position)

    assert advice["action"] == "降低买入侧"
    assert advice["suggested_buy_quantity"] < advice["suggested_sell_quantity"]
    assert any("不用于鼓励补仓" in reason or "买入侧降速" in reason for reason in advice["reasons"])


def test_watchlist_open_generates_new_grid_without_existing_touker_grid():
    market = MarketSnapshot(
        code="159999",
        name="测试ETF",
        last_price=1.0,
        pct_chg=0.5,
        volume=1000000,
        amount=100000000,
        ma20=0.98,
        boll_mid=0.99,
        atr14_pct=2.0,
        kline_days=240,
    )

    advice = advise_grid(None, market, None, rule_decision={"action": "轻仓建仓", "position_action": "LIGHT_OPEN", "trend_score": 78, "risk_level": "LOW"})

    assert advice["grid_applicable"] is True
    assert advice["grid_purpose"] == "建仓网格"
    assert advice["base_price_status"] == "新建建议基准"
    assert advice["suggested_base_price"] is not None
    assert advice["suggested_buy_rebound_pct"] is not None
    assert advice["suggested_sell_pullback_pct"] is not None


def test_watchlist_not_open_does_not_emit_executable_grid():
    market = MarketSnapshot(
        code="159999",
        name="测试ETF",
        last_price=1.0,
        pct_chg=0.5,
        volume=1000000,
        amount=100000000,
        ma20=0.98,
        boll_mid=0.99,
        atr14_pct=2.0,
        kline_days=240,
    )

    advice = advise_grid(None, market, None, rule_decision={"action": "观察", "position_action": "WATCH", "trend_score": 50, "risk_level": "MEDIUM"})

    assert advice["grid_applicable"] is False
    assert advice["grid_purpose"] == "暂不设网格"
    assert advice["suggested_base_price"] is None


def test_position_pct_uses_account_total_asset_and_keeps_holding_pct():
    position = _cli_position(
        {
            "code": "159999",
            "name": "测试ETF",
            "quantity": 1000,
            "market_value": 1000,
            "holding_pct": "25%",
            "cost_price": 1,
            "last_price": 1,
        },
        {"total_asset": 10000, "total_market_value": 4000},
    )

    assert position.position_pct == 10
    assert position.holding_pct == 25
    assert position.position_pct_source == "ths_account_total_asset"


def test_trade_review_quality_metrics():
    trades = [
        Trade("2026-06-24", "09:30:00", "159999", "测试ETF", "买入", 1.00, 100, 100, 0.1),
        Trade("2026-06-24", "10:00:00", "159999", "测试ETF", "买入", 0.98, 100, 98, 0.1),
        Trade("2026-06-24", "11:00:00", "159999", "测试ETF", "卖出", 1.03, 100, 103, 0.1),
        Trade("2026-06-24", "13:00:00", "159999", "测试ETF", "卖出", 1.05, 100, 105, 0.1),
    ]

    review = review_trade_periods(trades, "2026-06-24")[0]

    assert review["avg_trade_amount"] == 101.5
    assert review["ineffective_trade_count"] == 4
    assert review["estimated_grid_profit"] is not None
    assert review["buy_after_down_count"] >= 1
    assert review["sell_after_up_count"] >= 1


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


def test_report_hides_rule_versions():
    html = render_html("2026-06-23 14:45:08", [], [], {}, {})

    assert "规则 2026.06.23-v1" not in html
    assert "评分 score-2026.06" not in html
    assert "网格 grid-2026.06" not in html
    assert "风控 risk-2026.06" not in html


def test_indicator_metric_values_are_colored_by_context():
    view = _holding_view(
        {
            "code": "159999",
            "name": "测试ETF",
            "last_price": 1.2,
            "boll_position_pct": 95.0,
            "boll_upper": 1.18,
            "boll_mid": 1.0,
            "boll_lower": 0.82,
            "ma5": 1.1,
            "ma10": 1.05,
            "ma20": 0.98,
            "ma60": 1.25,
            "ma200": None,
            "ma_status": "上MA5/下MA60",
            "volume": 1000000,
            "vol_ratio": 2.1,
            "turnover_pct": 6.0,
            "amount_ratio20": 0.65,
            "vol_ma5": 200,
            "vol_ma20": 100,
            "atr7_pct": 5.2,
            "atr14_pct": 4.6,
            "atr30_pct": 3.0,
            "atr60_pct": 1.8,
            "bias6": 7.0,
            "bias12": 3.5,
            "bias24": -3.2,
            "rsi6": 88,
            "rsi14": 28,
        }
    )
    html = "".join(str(row.get("current", "")) + str(row.get("reference", "")) for row in view["rows"])

    assert '<span class="danger">95.00%</span>' in html
    assert '<span class="profit">1.100</span>' in html
    assert '<span class="loss">1.250</span>' in html
    assert '<span class="warn">2.10</span>' in html
    assert '<span class="danger">5.20%</span>' in html
    assert '<span class="danger">+7.00%</span>' in html
    assert '<span class="attention">28.0</span>' in html
