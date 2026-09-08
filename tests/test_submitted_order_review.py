from copy import deepcopy

import pytest

from etfmate.analysis.submitted_order_review import build_submitted_order_review


def snapshot(*records, **changes):
    return {"contract": "touker_submitted_audit_v1", "captured_at": "2026-09-08T14:10:00+08:00",
            "selected_tab": "已委托", "selection_verified": True, "complete": True,
            "records": list(records), **changes}


def order(status="已申报", **changes):
    return {"code": "159687", "date": "2026-09-08", "time": "13:50:00", "side": "卖出",
            "quantity": 1000, "price": 1.913, "status": status, "detail_status": None, **changes}


@pytest.mark.parametrize("status,normalized", [
    ("已成交", "FILLED"), ("已成交，成交价1.0650", "FILLED"), ("全部成交", "FILLED"), ("已撤单", "CANCELLED"),
    ("部撤", "CANCELLED"), ("委托失败", "REJECTED"), ("拒单", "REJECTED"), ("废单", "REJECTED"),
])
def test_terminal_records_do_not_become_open_orders(status, normalized):
    result = build_submitted_order_review(snapshot(order(status)))
    assert result["complete"] is True
    assert result["status_counts"] == {normalized: 1}
    assert result["today_open_orders"] == []
    assert result["records"][0]["status"] == status
    assert result["records"][0]["terminal"] is True
    assert result["reservation_evidence"] == "NOT_DERIVED"


@pytest.mark.parametrize("status,normalized", [
    ("已申报", "SUBMITTED"), ("部分成交", "PARTIALLY_FILLED"), ("部成", "PARTIALLY_FILLED"),
    ("撤单中", "CANCEL_PENDING"), ("已报待撤", "CANCEL_PENDING"), ("待申报", "PENDING_SUBMISSION"),
])
def test_today_nonterminal_orders_remain_separate_from_fills(status, normalized):
    result = build_submitted_order_review(snapshot(order(status, filled_quantity=100)))
    assert result["complete"] is True
    assert result["status_counts"] == {normalized: 1}
    assert len(result["today_open_orders"]) == 1
    assert result["today_open_orders"][0]["quantity"] == 1000
    assert result["today_open_orders"][0]["filled_quantity"] == 100
    assert result["today_open_orders"][0]["terminal"] is False
    assert "冻结" not in {key for key in result}


@pytest.mark.parametrize("detail", ["可用资金不足", "库存不足", "数量不合法", "失败：申报数量必须为100的整数倍"])
def test_explicit_failure_detail_supersedes_generic_submission_label(detail):
    result = build_submitted_order_review(snapshot(order(detail_status=detail, date="2026-07-14")))
    assert result["complete"] is True
    assert result["historical_failure_count"] == 1
    assert result["status_counts"] == {"REJECTED": 1}
    assert not result["historical_unresolved_orders"]
    assert result["records"][0]["detail_status"] == detail


def test_cancel_failure_does_not_terminate_original_order():
    result = build_submitted_order_review(snapshot(order(detail_status="撤单失败：可用股份不足")))
    assert result["status_counts"] == {"SUBMITTED": 1}
    assert len(result["today_open_orders"]) == 1
    assert "撤单失败不证明" in result["today_open_orders"][0]["note"]


@pytest.mark.parametrize("detail", ["如可用资金不足，请调整后重试", "未发现资金不足", "说明：库存不足时可能拒单"])
def test_narrative_mentions_of_failures_do_not_prove_rejection(detail):
    result = build_submitted_order_review(snapshot(order(detail_status=detail)))
    assert result["status_counts"] == {"SUBMITTED": 1}
    assert len(result["today_open_orders"]) == 1


@pytest.mark.parametrize("status", [
    "可用资金不足，差额：275.54",
    "委托数量超出该证券:588160的可用数量",
    "委托数量应该是100的整数倍(卖出零股则剩余必须是整股)",
    "委托数量不是100的整数倍",
])
def test_actual_platform_failure_statuses_are_terminal(status):
    result = build_submitted_order_review(snapshot(order(status, date="2026-07-14")))
    assert result["complete"] is True
    assert result["status_counts"] == {"REJECTED": 1}
    assert result["historical_failure_count"] == 1
    assert result["records"][0]["status"] == status
    assert not result["historical_unresolved_orders"]


def test_actual_old_order_detail_prefix_preserves_historical_state():
    result = build_submitted_order_review(snapshot(order(
        "已申报", code="588160", date="2026-07-14", time="13:33:38",
        quantity=500, price=1.280, detail_status="订单状态：已申报")))
    assert result["complete"] is True
    assert len(result["historical_unresolved_orders"]) == 1
    assert result["today_open_orders"] == []
    assert result["records"][0]["detail_status"] == "订单状态：已申报"


@pytest.mark.parametrize("status,detail", [("已成交", "已撤单"), ("已撤单", "已申报"), ("部分成交", "委托失败")])
def test_conflicting_states_are_not_silently_resolved(status, detail):
    result = build_submitted_order_review(snapshot(order(status, detail_status=detail)))
    assert result["complete"] is False
    assert result["status_counts"] == {"UNKNOWN_CONFLICT": 1}
    assert result["records"][0]["terminal"] is None
    assert len(result["unknown_orders"]) == 1


def test_old_july14_and_june5_submissions_are_not_todays_reservations():
    result = build_submitted_order_review(snapshot(order(date="2026-07-14"), order(date="2026-06-05")))
    assert result["complete"] is True
    assert result["today_open_orders"] == []
    assert len(result["historical_unresolved_orders"]) == 2
    assert result["label"] == "历史委托状态待更新"
    assert all("不能当作今日冻结" in row["note"] for row in result["historical_unresolved_orders"])
    assert result["read_range"] == {"earliest": "2026-06-05", "latest": "2026-07-14"}


def test_partial_history_shows_observed_failures_without_inventing_complete_total():
    result = build_submitted_order_review(snapshot(
        order("委托失败", date="2026-02-25"), order(date="2026-07-14"), complete=False))
    assert result["complete"] is False
    assert result["observed_count"] == 2
    assert result["historical_failure_count"] is None
    assert result["observed_historical_failure_count"] == 1
    assert result["label"] == "已委托记录 · 已读取范围复核"
    assert "2026-02-25至2026-07-14" in result["note"]
    assert "不改变账本现金与库存的独立推导" in result["note"]


@pytest.mark.parametrize("changes", [
    {"selected_tab": "监控中"}, {"selection_verified": False}, {"contract": "unknown"},
])
def test_unverified_or_monitoring_sources_never_become_submitted_orders(changes):
    result = build_submitted_order_review(snapshot(order(), **changes))
    assert result["complete"] is False
    assert result["observed_count"] is None
    assert result["today_open_orders"] == []
    assert result["status_counts"] == {}
    assert result["historical_failure_count"] is None
    assert result["monitoring_is_submission"] is False


@pytest.mark.parametrize("captured_at", [None, "", "invalid", "2026-09-08"])
def test_missing_or_invalid_capture_time_cannot_define_today(captured_at):
    result = build_submitted_order_review(snapshot(order(), captured_at=captured_at))
    assert result["complete"] is False
    assert result["observation_date"] is None
    assert result["today_open_orders"] == []
    assert len(result["unknown_orders"]) == 1
    assert result["historical_failure_count"] is None


def test_capture_and_submission_iso_timezones_use_shanghai_date():
    result = build_submitted_order_review(snapshot(
        order(date=None, submitted_at="2026-09-08T16:30:00Z"),
        order(date="2026-09-08"), captured_at="2026-09-08T17:00:00Z"))
    assert result["observation_date"] == "2026-09-09"
    assert len(result["today_open_orders"]) == 1
    assert result["today_open_orders"][0]["order_date"] == "2026-09-09"
    assert len(result["historical_unresolved_orders"]) == 1


@pytest.mark.parametrize("changes", [
    {"date": None}, {"date": "07-14"}, {"date": "2026-09-09"}, {"date": "2026-02-30"},
    {"submitted_at": "2026-09-07T13:00:00+08:00"}, {"status": "监控中"}, {"status": "未知状态"},
])
def test_unknown_or_inconsistent_record_evidence_is_not_current_permission(changes):
    result = build_submitted_order_review(snapshot(order(**changes)))
    assert result["complete"] is False
    assert len(result["unknown_orders"]) == 1
    assert result["today_open_orders"] == []


def test_missing_snapshot_and_verified_empty_list_are_distinct():
    missing = build_submitted_order_review(None)
    assert missing["observed_count"] is None
    assert missing["historical_failure_count"] is None
    assert missing["complete"] is False
    empty = build_submitted_order_review(snapshot())
    assert empty["observed_count"] == 0
    assert empty["historical_failure_count"] == 0
    assert empty["complete"] is True


def test_review_preserves_source_without_mutating_it():
    source = snapshot(order("部分成交", raw_text="真实页面原文", order_id="123"))
    original = deepcopy(source)
    result = build_submitted_order_review(source)
    assert source == original
    assert result["records"][0]["source_record"] == original["records"][0]
    result["records"][0]["source_record"]["status"] = "changed"
    assert source == original


@pytest.mark.parametrize("status,category", [
    ("可用资金不足，差额：275.54", "INSUFFICIENT_FUNDS"),
    ("委托数量超出该证券:588160的可用数量", "INSUFFICIENT_SELLABLE"),
    ("委托数量应该是100的整数倍(卖出零股则剩余必须是整股)", "INVALID_PRICE_OR_PARAMETER"),
    ("失败：申报数量必须为100的整数倍", "INVALID_PRICE_OR_PARAMETER"),
    ("委托价格不合法", "INVALID_PRICE_OR_PARAMETER"),
    ("失败：未知错误代码E999", "UNCLASSIFIED"),
])
def test_failure_summary_classifies_explicit_results_and_preserves_exact_evidence(status, category):
    raw_text = "原始委托记录\n" + status
    source = snapshot(order(status, date="2026-07-14", raw_text=raw_text, order_id="order-42"), complete=False)
    result = build_submitted_order_review(source)
    summary = result["failure_summary"]
    assert summary["scope"] == "OBSERVED_RECORDS_ONLY"
    assert summary["complete"] is False and summary["observed_rejected_count"] == 1
    group = next(row for row in summary["categories"] if row["code"] == category)
    assert group["count"] == 1
    assert group["examples"][0]["evidence_fields"] == {"status": status}
    assert group["examples"][0]["raw_text"] == raw_text
    assert group["examples"][0]["order_id"] == "order-42"
    assert summary["read_range"] == {"earliest": "2026-07-14", "latest": "2026-07-14"}
    assert result["records"][0]["failure_reason"]["category"] == category


def test_failure_summary_does_not_classify_unconfirmed_or_cancel_failures():
    result = build_submitted_order_review(snapshot(
        order("已成交", detail_status="失败：资金不足"),
        order(detail_status="撤单失败：可用股份不足"),
        order("委托失败", date="07-14"),
        order("委托失败", raw_text="平台说明：如可用资金不足，请重试"),
    ))
    summary = result["failure_summary"]
    assert summary["observed_rejected_count"] == 1
    assert summary["unclassified_count"] == 1
    assert all(row["count"] == 0 for row in summary["categories"] if row["code"] != "UNCLASSIFIED")
    assert len(result["today_open_orders"]) == 1


@pytest.mark.parametrize("reason", ["如资金不足，请调整后重试", "未发现资金不足", "说明：库存不足时可能拒单"])
def test_unknown_rejection_reason_does_not_inherit_hypothetical_error(reason):
    result = build_submitted_order_review(snapshot(order("委托失败", failure_reason=reason)))
    failure = result["records"][0]["failure_reason"]
    assert failure["category"] == "UNCLASSIFIED"
    assert failure["evidence_fields"]["failure_reason"] == reason


def test_conflicting_explicit_rejection_reasons_are_left_unclassified():
    result = build_submitted_order_review(snapshot(order("资金不足", detail_status="库存不足")))
    failure = result["records"][0]["failure_reason"]
    assert failure["category"] == "UNCLASSIFIED"
    assert "不同失败原因" in failure["note"]


def test_failure_summary_counts_every_observed_record_but_limits_examples():
    result = build_submitted_order_review(snapshot(*(order("资金不足", order_id=f"id-{i}") for i in range(5))))
    summary = result["failure_summary"]
    group = next(row for row in summary["categories"] if row["code"] == "INSUFFICIENT_FUNDS")
    assert summary["observed_rejected_count"] == group["count"] == 5
    assert len(group["examples"]) == 3
    assert "未来失败概率" in summary["note"] and "不是交易亏损" in summary["note"]


def test_failure_summary_distinguishes_missing_source_from_observed_empty_history():
    missing = build_submitted_order_review(None)["failure_summary"]
    assert missing["observed_rejected_count"] is None and missing["categories"] == []
    assert missing["source_verified"] is False
    unverified = build_submitted_order_review(snapshot(order("资金不足"), selection_verified=False))["failure_summary"]
    assert unverified["observed_rejected_count"] is None and unverified["categories"] == []
    empty = build_submitted_order_review(snapshot())["failure_summary"]
    assert empty["observed_rejected_count"] == 0 and empty["complete"] is True


@pytest.mark.parametrize("changes", [
    {"submitted_at": "2026-09-08T15:00:00+08:00", "time": "15:00:00"},
    {"submitted_at": "2026-09-08T07:00:00Z", "time": "15:00:00"},
    {"time": "15:00:00"},
    {"time": "07:00:00+00:00"},
])
def test_same_day_order_after_capture_is_unknown_and_excluded_from_failure_counts(changes):
    result = build_submitted_order_review(snapshot(
        order("资金不足", **changes), order("资金不足", date="2026-09-07"),
        captured_at="2026-09-08T10:00:00+08:00"))
    assert result["complete"] is False
    assert result["status_counts"] == {"UNKNOWN": 1, "REJECTED": 1}
    assert result["failure_summary"]["observed_rejected_count"] == 1
    assert result["observed_historical_failure_count"] == 1
    unknown = result["unknown_orders"][0]
    assert unknown["terminal"] is None and unknown["failure_reason"] is None
    assert "委托时刻晚于采集时刻" in "".join(unknown["issues"])
    assert unknown["observed_time_basis"] == "TIMESTAMP"
    assert unknown["order_timestamp"] == "2026-09-08T15:00:00+08:00"


@pytest.mark.parametrize("changes", [
    {"submitted_at": "2026-09-08T02:00:00Z", "time": "10:00:00"},
    {"time": "10:00:00+08:00"},
    {"time": "09:59:59"},
])
def test_order_at_or_before_capture_uses_real_timezone_without_rejecting_it(changes):
    result = build_submitted_order_review(snapshot(order("资金不足", **changes),
                                                  captured_at="2026-09-08T10:00:00+08:00"))
    assert result["complete"] is True and result["unknown_orders"] == []
    assert result["failure_summary"]["observed_rejected_count"] == 1
    assert result["records"][0]["observed_time_basis"] == "TIMESTAMP"


def test_date_only_record_exposes_intraday_limit_without_inventing_a_time():
    result = build_submitted_order_review(snapshot(order("资金不足", time=None),
                                                  captured_at="2026-09-08T10:00:00+08:00"))
    record = result["records"][0]
    assert record["observed_time_basis"] == "DATE_ONLY" and record["order_timestamp"] is None
    assert "不能证明同日委托发生在采集之前" in record["note"]
    assert record["submitted_at"] is None and record["time"] is None


def test_disagreeing_timestamp_and_separate_time_are_not_silently_selected():
    result = build_submitted_order_review(snapshot(order("资金不足", submitted_at="2026-09-08T09:00:00+08:00",
                                                        time="15:00:00"), captured_at="2026-09-08T10:00:00+08:00"))
    assert len(result["unknown_orders"]) == 1
    assert "字段不一致" in "".join(result["unknown_orders"][0]["issues"])
    assert result["failure_summary"]["observed_rejected_count"] == 0
