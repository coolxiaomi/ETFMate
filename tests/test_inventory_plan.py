from __future__ import annotations

from copy import deepcopy

import pytest

from etfmate.analysis import account_strategy
from etfmate.analysis.inventory_plan import build_inventory_plan


@pytest.fixture(autouse=True)
def confirmed_account_facts(monkeypatch):
    monkeypatch.setattr(account_strategy, "USER_ACCOUNT_FACTS", {
        "auto_sync_fills": True, "no_manual_orders": True,
        "no_external_cash_flows": True, "confirmed_on": "2026-09-08",
    }, raising=False)


def _account(code="510500", quantity=1000, trades=None):
    return {
        "positions": [{"code": code, "quantity": quantity}],
        "snapshot": {"scroll_complete": True, "text": "*最新上传时间: 2026-09-08 09:42，\n如何上传数据"},
        "trade_snapshots": {"本月": {"scroll_complete": True}},
        "trades": trades or [],
        "trade_collection_quality": {"merge_contract": "trade_view_occurrences_v1", "cycle_complete": False, "ambiguities": []},
    }


def _trade(code="510500", quantity=200, side="买入", day="2026-09-08", **kwargs):
    return {"code": code, "quantity": quantity, "side": side, "trade_date": day, **kwargs}


def test_t1_subtracts_gross_buys_not_net_buys_or_already_reflected_sells():
    # Yesterday 1000, today buy 200/sell 300, current 900 -> eligible 700.
    account = _account(quantity=900, trades=[_trade(), _trade(quantity=300, side="卖出")])
    row = build_inventory_plan(account, "2026-09-08")["510500"]
    assert row["settlement"] == "T1"
    assert row["today_buy_quantity"] == 200
    assert row["sellable_quantity"] == 700
    assert row["quality"] == "AS_OF_COLLECTION_DERIVED"
    assert row["broker_verified"] is False
    assert "不再重复扣减" in row["note"]


def test_complete_auto_sync_account_proves_zero_buys_despite_old_upload_label():
    account = _account()
    account["snapshot"]["text"] = "最新上传时间：2026-09-07 09:42"
    row = build_inventory_plan(account, "2026-09-08")["510500"]
    assert row["today_buy_quantity"] == 0
    assert row["sellable_quantity"] == 1000
    assert row["quality"] == "AS_OF_COLLECTION_DERIVED"
    assert row["upload_time"] == "2026-09-07 09:42"
    assert row["ledger_date"] == "2026-09-08"
    assert "用户已确认" in row["syncnote"]


def test_full_cycle_proof_is_not_required_for_t1_inventory():
    account = _account(trades=[_trade()])
    account["trade_collection_quality"]["cycle_complete"] = False
    assert build_inventory_plan(account, "2026-09-08")["510500"]["sellable_quantity"] == 800


def test_t0_does_not_subtract_today_buys_and_ignores_trade_count_ambiguity():
    account = _account("159687", trades=[_trade("159687", occurrence_ambiguous=True)])
    account["trade_snapshots"] = {}
    row = build_inventory_plan(account, "2026-09-08")["159687"]
    assert row["settlement"] == "T0"
    assert row["sellable_quantity"] == 1000
    assert row["quality"] == "AS_OF_COLLECTION_DERIVED"
    assert row["rule_source_urls"]


def test_t1_ambiguous_today_buys_preserve_quantity_and_only_give_sellable_upper_bound():
    account = _account(trades=[_trade(occurrence_ambiguous=True)])
    row = build_inventory_plan(account, "2026-09-08")["510500"]
    assert row["quantity"] == 1000
    assert row["settlement"] == "T1"
    assert row["sellable_quantity"] is None
    assert row["observed_today_buy_quantity"] == 200
    assert row["today_buy_quantity"] is None
    assert row["sellable_quantity_upper_bound"] == 800
    assert row["quality"] == "AMBIGUOUS_TODAY_BUYS"


@pytest.mark.parametrize("ambiguous_trade", [
    _trade(day="2026-09-07", occurrence_ambiguous=True),
    _trade(side="卖出", occurrence_ambiguous=True),
    _trade(code="159141", occurrence_ambiguous=True),
])
def test_unrelated_trade_ambiguity_does_not_erase_t1_inventory(ambiguous_trade):
    row = build_inventory_plan(_account(trades=[ambiguous_trade]), "2026-09-08")["510500"]
    assert row["sellable_quantity"] == 1000
    assert row["quality"] == "AS_OF_COLLECTION_DERIVED"


def test_quality_ambiguity_without_surviving_trade_row_is_scoped_to_code_day_and_buy():
    account = _account()
    account["positions"].append({"code": "159141", "quantity": 1000})
    account["trade_collection_quality"]["ambiguities"] = [{
        "key": "fields:510500:2026-09-08:买入::7.7:100", "reasons": ["滚动重叠笔数不确定"],
    }]
    rows = build_inventory_plan(account, "2026-09-08")
    assert rows["510500"]["quality"] == "AMBIGUOUS_TODAY_BUYS"
    assert rows["159141"]["sellable_quantity"] == 1000


def test_unidentified_distinct_fills_are_not_silently_deduplicated():
    account = _account(trades=[_trade(), _trade()])
    row = build_inventory_plan(account, "2026-09-08")["510500"]
    assert row["today_buy_quantity"] == 400
    assert row["sellable_quantity"] == 600


def test_duplicate_execution_id_is_counted_once():
    account = _account(trades=[_trade(trade_id="fill-1"), _trade(trade_id="fill-1")])
    assert build_inventory_plan(account, "2026-09-08")["510500"]["sellable_quantity"] == 800


def test_conflicting_same_execution_id_blocks_quantity_proof():
    account = _account(trades=[_trade(trade_id="fill-1"), _trade(quantity=300, trade_id="fill-1")])
    row = build_inventory_plan(account, "2026-09-08")["510500"]
    assert row["sellable_quantity"] is None
    assert row["quality"] == "AMBIGUOUS_TODAY_BUYS"


@pytest.mark.parametrize("change", ["missing_view", "not_complete", "missing_buy_date", "invalid_buy_quantity"])
def test_missing_relevant_evidence_is_not_assumed_to_be_zero(change):
    account = _account()
    if change == "missing_view":
        account.pop("trade_snapshots")
    elif change == "not_complete":
        account["trade_snapshots"]["本月"]["scroll_complete"] = False
    elif change == "missing_buy_date":
        account["trades"] = [_trade(day="")]
    else:
        account["trades"] = [_trade(quantity="无法识别")]
    row = build_inventory_plan(account, "2026-09-08")["510500"]
    assert row["quantity"] == 1000
    assert row["sellable_quantity"] is None
    assert row["today_buy_quantity"] is None


def test_today_buys_exceeding_t1_current_position_rejects_contradictory_ledger():
    row = build_inventory_plan(_account(quantity=100, trades=[_trade()]), "2026-09-08")["510500"]
    assert row["sellable_quantity"] is None
    assert row["quality"] == "INCONSISTENT_INVENTORY"


def test_zero_position_and_zero_settlement_inventory_are_real_numbers():
    empty = build_inventory_plan(_account(quantity=0), "2026-09-08")["510500"]
    newly_bought = build_inventory_plan(_account(quantity=200, trades=[_trade()]), "2026-09-08")["510500"]
    assert empty["sellable_quantity"] == 0
    assert newly_bought["sellable_quantity"] == 0


def test_unknown_settlement_preserves_position_without_defaulting_to_t1():
    row = build_inventory_plan(_account("999999"), "2026-09-08")["999999"]
    assert row["quantity"] == 1000
    assert row["settlement"] == "UNKNOWN"
    assert row["sellable_quantity"] is None
    assert row["quality"] == "UNKNOWN_SETTLEMENT"


def test_without_confirmed_sync_keep_snapshot_derivation_distinct(monkeypatch):
    monkeypatch.setattr(account_strategy, "USER_ACCOUNT_FACTS", {"auto_sync_fills": False})
    account = _account(trades=[_trade(day="2026-09-07")])
    account["snapshot"]["text"] = "最新上传时间: 2026-09-07 09:42"
    row = build_inventory_plan(account, "2026-09-08")["510500"]
    assert row["quality"] == "LEDGER_SNAPSHOT"
    assert row["ledger_date"] == "2026-09-07"
    assert row["sellable_quantity"] == 800


def test_next_day_releases_prior_day_t1_buys():
    row = build_inventory_plan(_account(trades=[_trade(day="2026-09-07")]), "2026-09-08")["510500"]
    assert row["today_buy_quantity"] == 0
    assert row["sellable_quantity"] == 1000


def test_build_inventory_plan_does_not_mutate_account():
    account = _account(trades=[_trade()])
    before = deepcopy(account)
    build_inventory_plan(account, "2026-09-08")
    assert account == before
