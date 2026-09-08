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


@pytest.mark.parametrize("missing", ["funding_plan", "inventory_plan", "both"])
def test_v9_version_only_migration_without_ledger_plans_is_rejected(tmp_path, monkeypatch, missing):
    from test_ai_review_gate import _prepare_analysis
    from etfmate.analysis.account_strategy import ANALYSIS_CONTRACT
    _, analysis, _ = _prepare_analysis(tmp_path, monkeypatch)
    assert analysis["analysis_contract"] == ANALYSIS_CONTRACT
    for field in ("funding_plan", "inventory_plan"):
        if missing in (field, "both"):
            analysis.pop(field)
    report = build_analysis_data_quality_report(_account(), _grids(), analysis)
    assert report["status"] == "FAIL"
    for field in ("funding_plan", "inventory_plan"):
        if missing in (field, "both"):
            assert any(f"缺少 v9 {field}" in message for message in report["fatal_errors"])


def _ledger_plan_fixture(*, over_cap=False, code="159687"):
    from etfmate.analysis.funding_plan import build_funding_plan
    from etfmate.analysis.inventory_plan import build_inventory_plan
    account, grids = _account(), _grids()
    account["positions"][0]["code"] = code
    grids["grids"][0].update(code=code, enabled=True, condition_type="grid")
    if over_cap:
        account["account_summary"].update(total_asset=4000, cash=100)
    when = "2026-09-08T11:45:37+08:00"
    inventory = build_inventory_plan(account, when[:10])
    analysis = {
        "analysis_time": when,
        "funding_plan": build_funding_plan(account, grids["grids"]),
        "inventory_plan": inventory,
        "grid_advices": [{"code": code, "inventory": dict(inventory[code]),
                          "candidate_sell_quantity": 100,
                          "parameter_plan": {"buy_quantity": 100, "sell_quantity": 100}}],
    }
    return account, grids, analysis


def _ledger_plan_errors(account, grids, analysis):
    from etfmate.analysis.data_quality import _validate_ledger_plans
    errors = []
    _validate_ledger_plans(account, grids, analysis, errors)
    return errors


@pytest.mark.parametrize("mutation", ["cash", "original_condition", "missing_condition", "invented_freeze", "unknown_order_to_confirmed"])
def test_v9_funding_plan_must_match_all_raw_fields(mutation):
    account, grids, analysis = _ledger_plan_fixture()
    assert not _ledger_plan_errors(account, grids, analysis)
    if mutation == "cash":
        account["account_summary"]["cash"] += 1
    elif mutation == "original_condition":
        grids["grids"][0]["order_quantity"] += 100
    elif mutation == "missing_condition":
        grids["grids"].append({"code": "159259", "condition_type": "buy_only", "enabled": True,
                               "order_quantity": 1000, "entry_gate_price": 1.3})
    elif mutation == "invented_freeze":
        analysis["funding_plan"]["frozen_cash"] = 0
    else:
        analysis["funding_plan"]["conditions"][0]["broker_order_status"] = "SUBMITTED"
    assert any("funding_plan" in message and "不一致" in message
               for message in _ledger_plan_errors(account, grids, analysis))


def test_v9_inventory_recomputes_at_analysis_date_instead_of_current_clock():
    from etfmate.analysis.inventory_plan import build_inventory_plan
    account, grids, analysis = _ledger_plan_fixture(code="159870")
    account["trades"] = [{"code": "159870", "trade_date": "2026-09-08", "side": "买入", "quantity": 700}]
    analysis["inventory_plan"] = build_inventory_plan(account, "2026-09-08")
    analysis["grid_advices"][0]["inventory"] = dict(analysis["inventory_plan"]["159870"])
    assert analysis["inventory_plan"]["159870"]["sellable_quantity"] == 300
    assert not _ledger_plan_errors(account, grids, analysis)
    analysis["analysis_time"] = "2026-09-09T11:45:37+08:00"
    assert any("inventory_plan" in message and "不一致" in message
               for message in _ledger_plan_errors(account, grids, analysis))


@pytest.mark.parametrize("mutation", ["missing_time", "invalid_time", "forged_inventory", "forged_grid", "missing_grid_inventory", "bool_as_quantity"])
def test_v9_inventory_plan_and_grid_evidence_cannot_be_forged(mutation):
    account, grids, analysis = _ledger_plan_fixture()
    if mutation == "missing_time":
        analysis.pop("analysis_time")
    elif mutation == "invalid_time":
        analysis["analysis_time"] = "invalid"
    elif mutation == "forged_inventory":
        analysis["inventory_plan"]["159687"]["sellable_quantity"] += 100
    elif mutation == "forged_grid":
        analysis["grid_advices"][0]["inventory"]["sellable_quantity"] += 100
    elif mutation == "missing_grid_inventory":
        analysis["grid_advices"][0].pop("inventory")
    else:
        analysis["inventory_plan"]["159687"]["broker_verified"] = 0
    assert _ledger_plan_errors(account, grids, analysis)


@pytest.mark.parametrize("field", ["candidate_sell_quantity", "suggested_sell_quantity", "partial_sell_plan.candidate_quantity"])
@pytest.mark.parametrize("quantity", [1001, 0, True])
def test_v9_all_current_sell_quantities_are_bounded_by_ledger_inventory(field, quantity):
    account, grids, analysis = _ledger_plan_fixture()
    grid = analysis["grid_advices"][0]
    if field.startswith("partial_sell_plan"):
        grid["partial_sell_plan"] = {"candidate_quantity": quantity}
    else:
        grid[field] = quantity
    assert any("可卖量" in message for message in _ledger_plan_errors(account, grids, analysis))


def test_v9_unknown_inventory_does_not_become_current_sell_permission():
    account, grids, analysis = _ledger_plan_fixture(code="510300")
    assert analysis["inventory_plan"]["510300"]["sellable_quantity"] is None
    assert any("可卖量未确定" in message for message in _ledger_plan_errors(account, grids, analysis))
    analysis["grid_advices"][0]["candidate_sell_quantity"] = None
    assert not _ledger_plan_errors(account, grids, analysis)


@pytest.mark.parametrize("field", ["candidate_buy_quantity", "conditional_buyback_quantity", "suggested_buy_quantity"])
def test_v9_zero_cap_blocks_current_buy_quantities_but_keeps_parameter_draft(field):
    account, grids, analysis = _ledger_plan_fixture(over_cap=True)
    assert analysis["funding_plan"]["cash"] == 100
    assert analysis["funding_plan"]["buy_capacity_under_cap"] == 0
    assert analysis["grid_advices"][0]["parameter_plan"]["buy_quantity"] == 100
    assert not _ledger_plan_errors(account, grids, analysis)
    analysis["grid_advices"][0][field] = 100
    assert any("可买额度为0" in message for message in _ledger_plan_errors(account, grids, analysis))


def _formal_capture_errors(account):
    from etfmate.analysis.data_quality import _validate_formal_collection_evidence
    errors = []
    _validate_formal_collection_evidence(account, errors)
    return errors


@pytest.mark.parametrize("mutation", [
    "missing_filter", "wrong_closed_range", "before_drift", "after_drift", "not_ready", "false_ready",
    "loading", "unverified", "custom_not_submitted", "custom_missing_dates", "custom_invalid_date",
    "custom_reversed_dates", "custom_after_drift",
])
def test_formal_report_requires_actual_selected_ranges_and_custom_query(mutation):
    account = _account()
    assert not _formal_capture_errors(account)
    selected = account["trade_snapshots"]["今年"]["range_filter"]
    custom = account["trade_snapshots"]["自定义"]["range_filter"]
    if mutation == "missing_filter":
        account["trade_snapshots"]["今年"].pop("range_filter")
    elif mutation == "wrong_closed_range":
        account["closed_snapshot"]["range_filter"]["selected"] = "本月"
    elif mutation in {"before_drift", "after_drift"}:
        selected[mutation.split("_")[0]]["selected"] = "本月"
    elif mutation == "not_ready":
        selected["after"]["ready"] = False
    elif mutation == "false_ready":
        selected["after"].update(row_count=0, empty=False)
    elif mutation == "loading":
        selected["after"]["loading"] = True
    elif mutation == "unverified":
        selected["verified"] = False
    elif mutation == "custom_not_submitted":
        custom["query_submitted"] = False
    elif mutation == "custom_missing_dates":
        custom["custom_dates"] = None
    elif mutation == "custom_invalid_date":
        custom["custom_dates"] = ["2026-02-30", "2026-09-08"]
    elif mutation == "custom_reversed_dates":
        custom["custom_dates"] = ["2026-09-08", "2026-09-01"]
    else:
        custom["after"]["custom_dates"] = ["2026-01-01", "2026-09-08"]
    assert any("实际范围选中" in message for message in _formal_capture_errors(account))
    assert build_raw_data_quality_report(account, _grids())["status"] == "PASS"


@pytest.mark.parametrize("mutation", [
    "missing_consistency", "claimed_fail", "forged_pass", "end_quantity", "end_cash", "missing_cash",
    "missing_end", "incomplete_end", "account_cash", "account_quantity",
])
def test_formal_report_recomputes_collection_boundary_cash_and_quantities(mutation):
    account = _account()
    assert not _formal_capture_errors(account)
    if mutation == "missing_consistency":
        account.pop("collection_consistency")
    elif mutation == "claimed_fail":
        account["collection_consistency"]["status"] = "FAIL"
    elif mutation == "forged_pass":
        account["collection_consistency"]["start"]["cash"] += 1
    elif mutation == "end_quantity":
        account["end_snapshot"]["tables"][0]["rows"][0][1] += 100
    elif mutation == "end_cash":
        account["end_snapshot"]["text"] = "现金余额\n50001"
    elif mutation == "missing_cash":
        account["end_snapshot"]["text"] = ""
    elif mutation == "missing_end":
        account.pop("end_snapshot")
    elif mutation == "incomplete_end":
        account["end_snapshot"]["scroll_complete"] = False
    elif mutation == "account_cash":
        account["account_summary"]["cash"] += 1
    else:
        account["positions"][0]["quantity"] += 100
    assert any("首尾" in message for message in _formal_capture_errors(account))


def test_formal_capture_accepts_real_zero_cash_and_price_movement_but_not_unknown_cash():
    from etfmate.browser.ths_account import _collection_consistency
    account = _account()
    account["account_summary"]["cash"] = 0
    account["snapshot"]["text"] = account["end_snapshot"]["text"] = "现金余额\n0"
    account["end_snapshot"]["tables"][0]["rows"][0][2] += 10
    account["collection_consistency"] = _collection_consistency(account["snapshot"], account["end_snapshot"])
    assert not _formal_capture_errors(account)
    account["account_summary"]["cash"] = "--"
    assert _formal_capture_errors(account)


def test_old_capture_can_analyze_but_cannot_be_promoted_to_formal_report(tmp_path, monkeypatch):
    from test_ai_review_gate import _prepare_analysis, _review_payload
    from etfmate.analysis.data_quality import build_report_data_quality_report
    _, analysis, review_input = _prepare_analysis(tmp_path, monkeypatch)
    account = _account()
    account.pop("end_snapshot")
    account.pop("collection_consistency")
    account["closed_snapshot"].pop("range_filter")
    for snapshot in account["trade_snapshots"].values():
        snapshot.pop("range_filter")
    assert build_analysis_data_quality_report(account, _grids(), analysis)["status"] == "PASS"
    formal = build_report_data_quality_report(account, _grids(), analysis, _review_payload(review_input))
    assert formal["formal_report_ready"] is False
    assert any("旧批次仅用于开发分析" in message for message in formal["fatal_errors"])
    assert any("不能仅重新分析旧批次" in message for message in formal["fatal_errors"])


def test_analyze_and_report_without_layer_dependencies(tmp_path, monkeypatch):
    from etfmate.analysis.account_strategy import ANALYSIS_CONTRACT
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
    assert analysis["analysis_contract"] == ANALYSIS_CONTRACT
    assert "layered_contexts" not in analysis
    assert "watchlist" not in analysis
    assert "t_grid_advices" not in analysis
    assert {r["code"] for r in analysis["recommendations"]} == {"510300", "510500", "159141", "159259", "159263"}
    assert analysis["grids_count"] == 1
    assert analysis["ignored_conditions_count"] == 1
    assert all(grid is None or grid.code == "510300" for grid in received_grids)
    from test_ai_review_gate import _write_valid_review
    _write_valid_review(tmp_path, run_id)
    cli.run_report(tmp_path, run_id)
    html = (tmp_path / "data/reports" / f"{run_id}-etf-realtime.html").read_text(encoding="utf-8")
    assert "七层" not in html
    assert "多层证据" not in html
    assert "全部 2 条；其中非网格 1 条已纳入资金和冲突复核" in html


def _account() -> dict:
    complete_snapshot = {"scroll_complete": True, "scroll_stop_reason": "ok"}
    trade_snapshots = {key: dict(complete_snapshot) for key in ("本月", "近三月", "近半年", "今年", "自定义")}
    account = {
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
    # Synthetic capture evidence for formal-gate tests, never a live account substitute.
    from copy import deepcopy
    from etfmate.browser.ths_account import _collection_consistency
    account["snapshot"].update(
        text="现金余额\n50000",
        tables=[{"headers": ["code", "quantity", "market_value"], "rows": [["510300", 1000, 3900]]}],
    )
    account["end_snapshot"] = deepcopy(account["snapshot"])
    account["collection_consistency"] = _collection_consistency(account["snapshot"], account["end_snapshot"])
    ranges = [("已清仓", "全部", account["closed_snapshot"])]
    ranges.extend(("交易记录", label, snapshot) for label, snapshot in trade_snapshots.items())
    for tab, label, snapshot in ranges:
        dates = ["2026-09-01", "2026-09-08"] if label == "自定义" else None
        state = {"selected": label, "ready": True, "loading": False, "row_count": 0,
                 "empty": True, "custom_dates": dates or []}
        snapshot.update(tab_label=tab, tab_clicked=True, range_filter={
            "contract": "ths_date_range_v1", "requested": label, "selected": label,
            "verified": True, "query_submitted": label == "自定义", "custom_dates": dates,
            "before": dict(state), "after": dict(state),
            "note": "测试采集证据",
        })
    return account


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
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone(timedelta(hours=8)))
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
        "quote_time": now.isoformat(timespec="seconds"),
        "signal_date": (now - timedelta(days=1)).date().isoformat(),
        "signal_is_complete": True,
        "signal_volume_basis": "completed_daily",
    }
