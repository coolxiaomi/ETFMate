from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etfmate.analysis import rule_engine
from etfmate.analysis.grid_advisor import advise_grid
from etfmate.analysis.layered_context import build_layered_context
from etfmate.analysis.recommendation import recommend
from etfmate.analysis.trade_reviewer import review_trade_periods
from etfmate.browser.ths_account import extract_watchlist
from etfmate.cli import _position as _cli_position
from etfmate.report.daily_report import _ai_judgement_html, _compact_grid_action, _grid_table_html, _holding_view, render_html
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
    decision = rule_engine.decide_position(_position(), None, _market(), [_position()], [_market()])

    assert decision["position_action"] in {"REDUCE", "TREND_REVIEW", "EXIT_TREND_POSITION"}
    assert decision["action"] != "持有"
    assert decision["account_mode"] == "TREND_TRADING"
    assert decision["trend_trade_mode"] == "ONLY_SELL_OR_CLEAR"
    assert any("只卖/清仓候选" in reason or "买入侧必须归零" in reason for reason in decision["reasons"])


def test_rule_engine_outputs_short_trend_only_without_legacy_total_scores(monkeypatch):
    monkeypatch.setattr(
        rule_engine,
        "_trend_score",
        lambda market: {
            "score": 90,
            "name": "短线强趋势",
            "level": "STRONG_TREND",
            "tags": [],
            "scores": {},
            "indicators": {},
            "data_sufficient": True,
            "evidence": ["测试强趋势"],
        },
    )

    decision = rule_engine.decide_position(None, None, _market(), [], [_market()])

    assert decision["position_action"] == "OPEN"
    assert decision["target_position_pct"] == 15
    assert "total_score" not in decision
    assert "momentum_score" not in decision
    assert "risk_score" not in decision


def test_overheat_guard_uses_boll_rsi_and_multi_period_bias():
    market = MarketSnapshot(
        code="159999",
        name="测试ETF",
        last_price=1.20,
        pct_chg=2.0,
        volume=1_500_000,
        amount=100_000_000,
        ma5=1.15,
        ma5_slope_3=0.02,
        ma10=1.10,
        ma20=1.00,
        boll_position=0.91,
        bias5_ratio=0.02,
        bias12=6.5,
        bias24=11.0,
        rsi6=71,
        vol_ratio_1_5=1.2,
        vol_ratio_5_20=1.0,
        kline_days=120,
    )

    trend = rule_engine._trend_score(market)
    decision = rule_engine.decide_position(None, None, market, [], [market])

    assert trend["score"] >= 75
    assert {"RSI短线偏热", "BIAS12明显正乖离", "BIAS24严重正乖离", "接近或突破布林上轨"} <= set(trend["tags"])
    assert decision["position_action"] != "OPEN"
    assert decision["target_position_pct"] == 0
    assert decision["risk_level"] == "HIGH"


def test_portfolio_limit_blocks_new_position(monkeypatch):
    monkeypatch.setattr(
        rule_engine,
        "_trend_score",
        lambda market: {
            "score": 90,
            "name": "短线强趋势",
            "level": "STRONG_TREND",
            "tags": [],
            "scores": {},
            "indicators": {},
            "data_sufficient": True,
            "evidence": ["测试强趋势"],
        },
    )
    existing = [
        Position("510500", "中证500ETF", 1000, 1, 1, 1000, 0, 0, position_pct=82, position_pct_source="ths_account_total_asset"),
    ]

    decision = rule_engine.decide_position(None, None, _market(), existing, [_market()])

    assert decision["position_action"] == "WATCH"
    assert decision["action"] == "观察"


def test_category_concentration_does_not_block_theme_trend_entry(monkeypatch):
    monkeypatch.setattr(
        rule_engine,
        "_trend_score",
        lambda market: {
            "score": 90,
            "name": "短线强趋势",
            "level": "STRONG_TREND",
            "tags": [],
            "scores": {},
            "indicators": {},
            "data_sufficient": True,
            "evidence": ["测试强趋势"],
        },
    )
    existing = [
        Position("159001", "主题ETF甲", 1000, 1, 1, 1000, 0, 0, position_pct=20, position_pct_source="ths_account_total_asset"),
        Position("159002", "主题ETF乙", 1000, 1, 1, 1000, 0, 0, position_pct=15, position_pct_source="ths_account_total_asset"),
    ]

    decision = rule_engine.decide_position(None, None, _market(), existing, [_market()])

    assert decision["position_action"] == "OPEN"


def test_strong_theme_holding_waits_for_volume_confirmation_without_category_cap():
    position = Position(
        "159326",
        "电网设备ETF华夏",
        1500,
        1.633,
        2.216,
        3324,
        874.96,
        35.72,
        position_pct=4.19,
        position_pct_source="ths_account_total_asset",
    )
    existing = [
        position,
        Position("159141", "人工智能ETF", 3500, 1.333, 1.524, 5334, 667, 14.3, position_pct=6.72, position_pct_source="ths_account_total_asset"),
        Position("562800", "稀有金属ETF", 5000, 1.125, 1.172, 5860, 236, 4.2, position_pct=7.38, position_pct_source="ths_account_total_asset"),
        Position("560280", "工程机械ETF", 3900, 1.713, 1.564, 6099.6, -581, -8.71, position_pct=7.69, position_pct_source="ths_account_total_asset"),
        Position("159516", "半导体设备ETF", 1000, 1.434, 1.702, 1702, 268, 18.71, position_pct=2.14, position_pct_source="ths_account_total_asset"),
        Position("515880", "通信ETF", 1100, 1.471, 1.883, 2071.3, 452, 27.99, position_pct=2.61, position_pct_source="ths_account_total_asset"),
    ]
    market = MarketSnapshot(
        code="159326",
        name="电网设备ETF华夏",
        last_price=2.216,
        pct_chg=1.23,
        volume=4_341_732,
        amount=956_470_000,
        ma5=2.2008,
        ma5_slope_3=0.0238,
        ma10=2.1326,
        ma20=2.09625,
        ma60=2.0197,
        boll_position=0.8946,
        bias5_ratio=0.0069,
        bias12=4.62,
        bias24=5.95,
        rsi6=68.2,
        vol_ratio_1_5=0.723,
        vol_ratio_5_20=0.923,
        kline_days=261,
    )

    decision = rule_engine.decide_position(position, None, market, existing, [market])

    assert decision["trend_score"] == 89
    assert decision["position_action"] == "HOLD_WAIT_ADD"
    assert decision["target_position_pct"] == 30
    assert decision["adjust_pct"] == 0 


def test_same_theme_overlap_is_neutral_screening_signal_not_negative_score():
    position = Position("159516", "半导体设备ETF国泰", 1000, 1.4, 1.7, 1700, 300, 20, position_pct=2)
    peer = Position("588200", "科创芯片ETF嘉实", 1000, 1.0, 1.0, 1000, 0, 0, position_pct=1)
    market = MarketSnapshot(
        code="159516",
        name="半导体设备ETF国泰",
        last_price=1.7,
        pct_chg=1,
        volume=1_000_000,
        amount=100_000_000,
        ma20=1.6,
        ma60=1.5,
        kline_days=240,
        data_quality="quote:tencent;kline:tencent",
    )

    context = build_layered_context(position, None, market, [position, peer])
    signal = next(layer for layer in context.layers if layer.key == "signal")

    assert signal.score == 0
    assert "待筛选" in signal.conclusion
    assert context.total_score >= 0


def test_low_layer_confidence_only_adds_review_note_without_downgrading_strong_trend():
    position = Position(
        "159326",
        "电网设备ETF华夏",
        1500,
        1.633,
        2.216,
        3324,
        874.96,
        35.72,
        position_pct=4.19,
        position_pct_source="ths_account_total_asset",
    )
    market = MarketSnapshot(
        code="159326",
        name="电网设备ETF华夏",
        last_price=2.216,
        pct_chg=1.23,
        volume=4_341_732,
        amount=956_470_000,
        ma5=2.2008,
        ma5_slope_3=0.0238,
        ma10=2.1326,
        ma20=2.09625,
        ma60=2.0197,
        boll_position=0.8946,
        bias5_ratio=0.0069,
        bias12=4.62,
        bias24=5.95,
        rsi6=68.2,
        vol_ratio_1_5=0.723,
        vol_ratio_5_20=0.923,
        kline_days=261,
    )

    item = recommend(position, None, market, [position], [market], layered_context={"confidence": 22, "total_score": 1})

    assert item["action"] == "持有待加仓确认"
    assert any("仅作复核提示" in risk for risk in item["risks"])
    assert not any("不适合扩大仓位" in risk or "强动作降级" in risk for risk in item["risks"])


def test_fallback_holding_pct_does_not_trigger_portfolio_hard_cap(monkeypatch):
    monkeypatch.setattr(
        rule_engine,
        "_trend_score",
        lambda market: {
            "score": 90,
            "name": "短线强趋势",
            "level": "STRONG_TREND",
            "tags": [],
            "scores": {},
            "indicators": {},
            "data_sufficient": True,
            "evidence": ["测试强趋势"],
        },
    )
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
            "action": "趋势复核",
            "position_action": "TREND_REVIEW",
            "risk_level": "HIGH",
            "trend_score": 25,
            "target_position_ratio": 0,
        },
        layered_context={"confidence": 22, "total_score": -3},
    )

    assert advice["action"] == "只卖清仓"
    assert advice["grid_mode"] == "ONLY_SELL_OR_CLEAR"
    assert advice["suggested_buy_quantity"] is None
    assert advice["buy_execution_status"] == "DISABLED"


def test_zero_target_reduce_grid_switches_to_sell_only_even_before_high_risk():
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
            "action": "减仓",
            "position_action": "REDUCE",
            "risk_level": "MEDIUM",
            "trend_score": 35,
            "target_position_ratio": 0,
        },
    )

    assert advice["action"] == "只卖清仓"
    assert advice["grid_mode"] == "ONLY_SELL_OR_CLEAR"
    assert advice["suggested_buy_quantity"] is None
    assert advice["buy_execution_status"] == "DISABLED"


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
    assert advice["suggested_sell_quantity"] >= (advice["suggested_buy_quantity"] or 0)


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


def test_profitable_strong_trend_grid_keeps_existing_sell_rise_when_bias_not_extreme():
    grid = GridConfig(
        code="159326",
        name="电网设备ETF华夏",
        enabled=True,
        base_price=2.172,
        order_quantity=1000,
        buy_quantity=1000,
        sell_quantity=1000,
        buy_fall_pct=2.15,
        buy_rebound_pct=0.15,
        sell_rise_pct=5.15,
        sell_pullback_pct=0.15,
        min_base_quantity=1000,
        max_position_quantity=10000,
    )
    position = Position("159326", "电网设备ETF华夏", 1500, 1.633, 2.216, 3324, 874.96, 35.72, position_pct=4.19)
    market = MarketSnapshot(
        code="159326",
        name="电网设备ETF华夏",
        last_price=2.216,
        pct_chg=1.23,
        volume=4_341_732,
        amount=956_470_000,
        ma20=2.09625,
        ma60=2.0197,
        boll_upper=2.248,
        boll_mid=2.09625,
        boll_position=0.8946,
        bias6=1.16,
        atr14_pct=3.2007,
        kline_days=261,
    )

    advice = advise_grid(
        grid,
        market,
        position,
        layered_context={"confidence": 22, "total_score": 1},
        rule_decision={
            "action": "持有待加仓确认",
            "position_action": "HOLD_WAIT_ADD",
            "trend_score": 89,
            "risk_level": "LOW",
            "target_position_ratio": 0.30,
        },
    )

    assert advice["grid_purpose"] == "加仓网格"
    assert advice["suggested_sell_rise_pct"] == 5.15
    assert advice["suggested_sell_quantity"] == 500
    assert advice["suggested_buy_quantity"] == 1000
    assert any("卖出触发不因 ATR 公式收紧" in reason for reason in advice["reasons"])
    assert not any("胜率优先护栏触发" in reason for reason in advice["reasons"])


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

    advice = advise_grid(
        grid,
        market,
        position,
        rule_decision={
            "action": "减仓",
            "position_action": "REDUCE",
            "trend_score": 57,
            "risk_level": "MEDIUM",
            "trend_overheat_level": "NONE",
        },
    )

    assert advice["action"] == "弱势减仓"
    assert advice["grid_mode"] == "WEAK_REDUCE"
    assert advice["suggested_buy_quantity"] is None
    assert advice["buy_execution_status"] == "DISABLED"
    assert advice["suggested_sell_quantity"] >= 100
    assert any("不用于鼓励补仓" in reason or "买入侧降速" in reason for reason in advice["reasons"])


def test_disabled_grid_side_does_not_render_zero_share_order():
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
            "action": "退出短线仓位",
            "position_action": "EXIT_SHORT_TERM",
            "trend_score": 20,
            "risk_level": "HIGH",
            "target_position_ratio": 0,
        },
    )

    html = _grid_table_html(advice)

    assert advice["suggested_buy_quantity"] is None
    assert "停买" in html
    assert re.search(r"(?<!\d)0股", html) is None


def test_trend_grid_sell_quantity_never_exceeds_current_position_for_report_examples():
    examples = [
        ("515880", "通信ETF国泰", 1100, 1500, 86, "OVERHEATED"),
        ("159781", "科创创业ETF易方达", 1000, 1500, 80, "OVERHEATED"),
        ("562950", "消费电子ETF易方达", 100, 1000, 73, "OVERHEATED"),
        ("159516", "半导体设备ETF国泰", 1000, 1500, 68, "SEVERE_OVERHEATED"),
    ]
    for code, name, quantity, raw_sell_qty, trend_score, overheat_level in examples:
        position = Position(code, name, quantity, 1.0, 1.2, quantity * 1.2, 0, 12, position_pct=3)
        grid = GridConfig(code=code, name=name, enabled=True, order_quantity=raw_sell_qty, sell_quantity=raw_sell_qty, buy_quantity=raw_sell_qty)
        market = MarketSnapshot(
            code=code,
            name=name,
            last_price=1.2,
            pct_chg=1.0,
            volume=1_000_000,
            amount=100_000_000,
            boll_upper=1.2,
            boll_position=0.98,
            rsi6=78,
            bias12=8,
            atr14_pct=3.0,
            kline_days=240,
        )

        advice = advise_grid(
            grid,
            market,
            position,
            rule_decision={
                "action": "持有或小幅减仓",
                "position_action": "HOLD_OR_REDUCE",
                "trend_score": trend_score,
                "risk_level": "MEDIUM",
                "trend_overheat_level": overheat_level,
            },
        )

        assert advice["grid_mode"] == "PROFIT_PROTECTION"
        assert advice["suggested_sell_quantity"] <= quantity
        assert advice["suggested_buy_quantity"] in {None, 100}
        assert advice["suggested_sell_quantity"] % 100 == 0


def test_weak_trend_report_grid_label_is_not_lower_buy():
    assert _compact_grid_action("只卖清仓") == "只卖清仓"
    assert _compact_grid_action("弱势减仓") == "弱减"


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


def test_watchlist_keeps_commodity_gold_and_qdii_etfs():
    snapshot = {
        "text": "\n".join(
            [
                "518880",
                "黄金ETF",
                "159985",
                "豆粕ETF",
                "513100",
                "纳指ETF(QDII)",
                "600519",
                "贵州茅台",
                "123456",
                "测试转债",
            ]
        )
    }

    included, filtered = extract_watchlist(snapshot)
    included_codes = {item["code"] for item in included}
    filtered_codes = {item["code"] for item in filtered}

    assert {"518880", "159985", "513100"} <= included_codes
    assert "600519" in filtered_codes
    assert "123456" in filtered_codes


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


def test_report_etf_display_order_uses_trend_holding_and_pnl_desc():
    recommendations = [
        _report_item("159901", "低趋势", 80, 30, 8),
        _report_item("159902", "高趋势", 90, 1, -5),
        _report_item("159903", "同分高仓低盈", 80, 35, -1),
        _report_item("159904", "同分高仓高盈", 80, 35, 3),
    ]
    grids = [{"code": item["code"], "name": item["name"], "action": "维持网格"} for item in recommendations]

    html = render_html("2026-06-25 10:00:00", recommendations, grids, {}, {})
    expected_codes = ["159902", "159904", "159903", "159901"]

    article_ids = re.findall(r'<article class="etf-card filter-item"[^>]+id="etf-(\d+)"', html)
    assert article_ids == expected_codes
    _assert_link_order(_panel_html(html, "decision", "trend"), expected_codes)
    _assert_link_order(_panel_html(html, "trend", "holding"), expected_codes)
    _assert_link_order(_panel_html(html, "holding", "pnl"), expected_codes)
    _assert_link_order(_panel_html(html, "pnl", "grid"), expected_codes)
    _assert_link_order(_panel_html(html, "grid", "risk"), expected_codes)


def test_report_risk_tab_aggregates_high_risk_items_from_etf_details():
    recommendations = [
        _report_item("159901", "高风险持仓", 40, 12, -8),
        _report_item("159902", "低风险持仓", 90, 4, 5),
        _report_item("159903", "高风险观察", 86, 0, 0),
    ]
    recommendations[0]["position_risk_level"] = "HIGH"
    recommendations[0]["rule_decision"]["risk_level"] = "HIGH"
    recommendations[0]["risks"] = ["跌破MA5", "短线量能不足"]
    recommendations[2]["quantity"] = None
    recommendations[2]["position_pct"] = None
    recommendations[2]["position_risk_level"] = "HIGH"
    recommendations[2]["rule_decision"]["risk_level"] = "HIGH"
    recommendations[2]["risks"] = ["BIAS24严重正乖离"]

    html = render_html("2026-06-25 10:00:00", recommendations, [], {}, {})
    risk_panel = html.split('data-panel="risk"', 1)[1]

    assert "无高风险项" not in risk_panel
    assert "高风险 2 只" in risk_panel
    assert "持仓 1 只" in risk_panel
    assert "159901 高风险持仓" in risk_panel
    assert "159903 高风险观察" in risk_panel


def _report_item(code: str, name: str, trend_score: float, holding_pct: float, pnl_pct: float) -> dict:
    return {
        "code": code,
        "name": name,
        "action": "持有",
        "quantity": 1000,
        "last_price": 1.0,
        "cost_price": 1.0,
        "market_value": 1000,
        "position_pct": holding_pct / 2,
        "holding_pct": holding_pct,
        "pnl_pct": pnl_pct,
        "rule_trend_score": trend_score,
        "rule_decision": {"trend_score": trend_score, "trend_level": "测试趋势"},
    }


def _panel_html(html: str, panel: str, next_panel: str) -> str:
    return html.split(f'data-panel="{panel}"', 1)[1].split(f'data-panel="{next_panel}"', 1)[0]


def _assert_link_order(html: str, expected_codes: list[str]) -> None:
    assert re.findall(r'href="#etf-(\d+)"', html) == expected_codes


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
