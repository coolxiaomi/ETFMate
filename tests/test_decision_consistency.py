from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etfmate.analysis import rule_engine
from etfmate.analysis.recommendation import recommend
from etfmate.analysis.trade_reviewer import review_trade_periods
from etfmate.browser.ths_account import extract_watchlist
from etfmate.cli import _position as _cli_position
from etfmate.storage.models import GridConfig, MarketSnapshot, Position, Trade


def test_short_trend_score_uses_pure_five_factor_score_without_atr_deduct():
    market = MarketSnapshot(
        code="159999",
        name="测试ETF",
        last_price=1.10,
        pct_chg=1.0,
        volume=1_500_000,
        amount=100_000_000,
        ma5=1.05,
        ma5_slope_3=0.02,
        ma10=1.00,
        ma20=0.95,
        boll_position=0.80,
        bias5_ratio=0.02,
        rsi6=60,
        atr14=0.02,
        atr_expansion_ratio=2.0,
        vol_ratio_1_5=1.35,
        vol_ratio_5_20=1.1,
        kline_days=120,
    )

    trend = rule_engine._trend_score(market)

    assert trend["score"] == 100
    assert trend["level"] == "STRONG_TREND"
    assert trend["name"] == "短线强趋势"
    assert "atr_risk_deduct" not in trend["scores"]
    assert "positive_normalized_score" not in trend["scores"]
    assert "ATR波动放大" not in trend["tags"]


def test_etf_classifier_keeps_commodity_gold_and_qdii_as_analysis_categories():
    assert rule_engine.classify_etf("黄金ETF") == "商品ETF"
    assert rule_engine.classify_etf("豆粕ETF") == "商品ETF"
    assert rule_engine.classify_etf("纳指ETF(QDII)") == "跨境ETF"


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
