from __future__ import annotations

import pytest

from etfmate.analysis.data_quality import (
    DataQualityError,
    build_analysis_data_quality_report,
    build_raw_data_quality_report,
    require_data_quality_pass,
)


def test_raw_data_quality_passes_complete_collection():
    report = build_raw_data_quality_report(_account(), _grids())

    assert report["status"] == "PASS"


def test_raw_data_quality_blocks_missing_position_field():
    account = _account()
    account["positions"][0].pop("last_price")

    report = build_raw_data_quality_report(account, _grids())

    assert report["status"] == "FAIL"
    assert any("缺少 现价" in item for item in report["fatal_errors"])


def test_raw_data_quality_blocks_missing_clean_watchlist():
    account = _account()
    account["watchlist"] = [{"code": "510300", "name": "沪深300ETF", "source_key": "localStorage:defaultPositioin"}]

    report = build_raw_data_quality_report(account, _grids())

    assert report["status"] == "FAIL"
    assert any("自选 ETF 池为空" in item for item in report["fatal_errors"])


def test_raw_data_quality_blocks_incomplete_touker_grid_fields():
    grids = _grids()
    grids["grids"][0].pop("buy_rebound_pct")

    report = build_raw_data_quality_report(_account(), grids)

    assert report["status"] == "FAIL"
    assert any("缺少 买入反弹" in item for item in report["fatal_errors"])


def test_raw_data_quality_blocks_snapshot_without_scroll_proof():
    account = _account()
    account["watchlist_snapshot"].pop("scroll_complete")

    report = build_raw_data_quality_report(account, _grids())

    assert report["status"] == "FAIL"
    assert any("缺少滚动完整性标记" in item for item in report["fatal_errors"])


def test_analysis_quality_blocks_missing_universe_snapshot():
    analysis = _analysis()
    analysis["market_snapshots"] = []

    report = build_analysis_data_quality_report(_account(), _grids(), analysis)

    assert report["status"] == "FAIL"
    assert any("行情快照缺少 universe 代码" in item for item in report["fatal_errors"])
    with pytest.raises(DataQualityError):
        require_data_quality_pass(report, "报告前")


def _account() -> dict:
    complete_snapshot = {"scroll_complete": True, "scroll_stop_reason": "ok"}
    trade_snapshots = {key: dict(complete_snapshot) for key in ("本月", "近三月", "近半年", "今年", "自定义")}
    return {
        "positions": [
            {
                "code": "510300",
                "name": "沪深300ETF",
                "quantity": 1000,
                "market_value": 3900,
                "last_price": 3.9,
                "cost_price": 3.5,
                "note": "",
            }
        ],
        "account_summary": {"total_asset": 100000, "cash": 50000, "total_market_value": 3900},
        "trades": [],
        "closed_positions": [],
        "watchlist": [{"code": "159915", "name": "创业板ETF", "source_key": "page_text"}],
        "watchlist_filtered_out": [],
        "watchlist_stats": {
            "source_url": "https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/ISUeEwK",
            "canonical_url": "https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/ISUeEwK",
        },
        "snapshot": dict(complete_snapshot),
        "closed_snapshot": dict(complete_snapshot),
        "watchlist_snapshot": dict(complete_snapshot),
        "trade_snapshots": trade_snapshots,
    }


def _grids() -> dict:
    return {
        "grids": [
            {
                "code": "510300",
                "name": "沪深300ETF",
                "base_price": 3.8,
                "last_price": 3.9,
                "buy_fall_pct": 3.0,
                "buy_rebound_pct": 0.1,
                "sell_rise_pct": 3.0,
                "sell_pullback_pct": 0.1,
                "order_quantity": 100,
                "min_base_quantity": 500,
                "max_position_quantity": 2000,
            }
        ],
        "expected_count": 1,
        "snapshot": {"scroll_complete": True, "scroll_stop_reason": "ok"},
    }


def _analysis() -> dict:
    return {
        "market_snapshots": [
            _snapshot("510300"),
            _snapshot("159915"),
        ],
        "recommendations": [
            {"code": "510300", "rule_decision": {"position_action": "HOLD"}},
            {"code": "159915", "rule_decision": {"position_action": "WATCH"}},
        ],
        "grid_advices": [
            {"code": "510300", "grid_applicable": True},
            {"code": "159915", "grid_applicable": False},
        ],
        "ai_review_input_path": "data/raw/market/test/ai_review_input.json",
    }


def _snapshot(code: str) -> dict:
    return {
        "code": code,
        "name": code,
        "last_price": 3.9,
        "amount": 100000000,
        "ma20": 3.8,
        "ma60": 3.6,
        "boll_mid": 3.8,
        "atr14_pct": 2.5,
        "rsi6": 55,
        "kline_days": 120,
        "data_quality": "quote:tencent;kline:tencent",
    }
