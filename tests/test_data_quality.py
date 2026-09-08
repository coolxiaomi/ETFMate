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


def test_raw_data_quality_ignores_retired_watchlist():
    account = _account()
    account["watchlist"] = [{"code": "510300", "name": "沪深300ETF", "source_key": "localStorage:defaultPositioin"}]

    report = build_raw_data_quality_report(account, _grids())

    assert report["status"] == "PASS"
    assert "watchlist_count" not in report["metrics"]


def test_raw_data_quality_blocks_incomplete_touker_grid_fields():
    grids = _grids()
    grids["grids"][0].pop("buy_rebound_pct")

    report = build_raw_data_quality_report(_account(), grids)

    assert report["status"] == "FAIL"
    assert any("缺少 买入反弹" in item for item in report["fatal_errors"])


def test_non_grid_orders_are_ignored_but_still_counted_for_completeness():
    grids = _grids()
    grids["grids"].extend([
        {"code": "159259", "condition_type": "grid", "raw_text": "分批建仓\n当前价格1.350\n股价低于(含)1.300元后"},
        {"code": "510300", "condition_type": "sell_only"},
    ])
    grids["expected_count"] = 3
    report = build_raw_data_quality_report(_account(), grids)
    assert report["status"] == "PASS"
    assert report["metrics"]["touker_conditions_count"] == 3
    assert report["metrics"]["touker_grids_count"] == 1
    assert report["metrics"]["touker_ignored_conditions_count"] == 2
    grids["expected_count"] = 4
    assert build_raw_data_quality_report(_account(), grids)["status"] == "FAIL"
    grids["expected_count"] = 3
    grids["grids"][0].pop("buy_rebound_pct")
    assert build_raw_data_quality_report(_account(), grids)["status"] == "FAIL"


def test_only_non_grid_orders_do_not_satisfy_grid_requirement():
    grids = _grids()
    grids["grids"] = [{"code": "159259", "condition_type": "buy_only"}]
    assert build_raw_data_quality_report(_account(), grids)["status"] == "FAIL"


def test_parser_recognizes_buy_only_without_reclassifying_grid():
    from etfmate.browser.touker_grid import _grid_records_from_text, is_grid_condition

    records = _grid_records_from_text("成长ETF易方达\n159259.SZ\n当前价格1.350\n分批建仓\n股价低于(含)1.300元后，每次个股涨跌幅达到-5.00%买入\n委托股数:1000股")
    assert records[0]["condition_type"] == "buy_only"
    assert not is_grid_condition(records[0])
    assert is_grid_condition({"raw_text": "网格交易\n股价低于某边界", "condition_type": "grid"})


def test_raw_data_quality_blocks_snapshot_without_scroll_proof():
    account = _account()
    account["snapshot"].pop("scroll_complete")

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


def test_legacy_analysis_must_be_recomputed_after_evidence_removal():
    analysis = _analysis()
    analysis.pop("analysis_contract")
    report = build_analysis_data_quality_report(_account(), _grids(), analysis)
    assert report["status"] == "FAIL"
    assert any("分析契约已更新" in item for item in report["fatal_errors"])


def test_price_rules_analysis_without_no_loss_guard_is_rejected():
    analysis = _analysis()
    analysis["analysis_contract"] = "etf_price_rules_v1"
    report = build_analysis_data_quality_report(_account(), _grids(), analysis)
    assert report["status"] == "FAIL"
    assert any("清仓不亏规则" in item for item in report["fatal_errors"])


def test_analyze_and_report_without_layer_dependencies(tmp_path, monkeypatch):
    from etfmate import cli
    from etfmate.storage.models import MarketSnapshot
    from etfmate.storage.repository import read_json, write_json

    run_id = "20260907-120000"
    write_json(tmp_path / "data/raw/ths" / run_id / "account.json", _account())
    grid_payload = _grids()
    grid_payload["grids"].insert(0, {"code": "159915", "condition_type": "buy_only", "order_quantity": 9900})
    grid_payload["expected_count"] = 2
    write_json(tmp_path / "data/raw/touker" / run_id / "grids.json", grid_payload)
    monkeypatch.setattr(cli, "build_market_snapshot", lambda code: MarketSnapshot(**_snapshot(code), pct_chg=0, volume=1000000))
    original_advise_grid = cli.advise_grid
    received_grids = []

    def capture_grid(grid, *args, **kwargs):
        received_grids.append(grid)
        return original_advise_grid(grid, *args, **kwargs)

    monkeypatch.setattr(cli, "advise_grid", capture_grid)
    cli.run_analyze(tmp_path, run_id)
    analysis = read_json(tmp_path / "data/raw/market" / run_id / "analysis.json")
    assert analysis["analysis_contract"] == "etf_account_transition_v7"
    assert "layered_contexts" not in analysis
    assert "watchlist" not in analysis
    assert "t_grid_advices" not in analysis
    assert {r["code"] for r in analysis["recommendations"]} == {"510300", "510500", "159141", "159259", "159263"}
    assert analysis["grids_count"] == 1
    assert analysis["ignored_conditions_count"] == 1
    assert all(grid is None or grid.code == "510300" for grid in received_grids)
    cli.run_report(tmp_path, run_id)
    html = (tmp_path / "data/reports" / f"{run_id}-etf-realtime.html").read_text(encoding="utf-8")
    assert "七层" not in html
    assert "多层证据" not in html
    assert "采集条件单 2 条，忽略非网格 1 条" in html


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
        "analysis_contract": "etf_account_transition_v5",
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
