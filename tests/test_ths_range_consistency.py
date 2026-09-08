import pytest

from etfmate.browser import ths_account as ths


class RangeSession:
    def __init__(self, states):
        self.states = iter(states)
        self.queries = 0

    def eval(self, script):
        if "const query =" in script:
            self.queries += 1
            return True
        if "item.click()" in script:
            return True
        return next(self.states)

    def screenshot(self, path):
        pass


def state(selected, *, ready=True, dates=None):
    return {"selected": selected, "ready": ready, "custom_dates": dates or [],
            "row_count": 1 if ready else 0, "empty": False, "loading": False}


def test_click_success_without_changed_selected_range_is_rejected(tmp_path):
    session = RangeSession([state("本月")])
    with pytest.raises(RuntimeError, match="时间筛选未生效"):
        ths._collect_range_snapshot(session, ths.THS_TRADES_TAB, "今年", tmp_path, timeout_seconds=0)


def test_selected_all_without_data_or_explicit_empty_state_is_not_ready(tmp_path):
    session = RangeSession([state("全部", ready=False)])
    with pytest.raises(RuntimeError, match="列表未就绪"):
        ths._collect_range_snapshot(session, ths.THS_CLOSED_TAB, "全部", tmp_path, timeout_seconds=0)


def test_closed_range_selection_is_recorded_before_and_after_scroll(tmp_path, monkeypatch):
    session = RangeSession([state("全部"), state("全部")])
    monkeypatch.setattr(ths, "_collect_scroll_loaded_snapshot", lambda *a: {"text": "", "scroll_complete": True})
    result = ths._collect_range_snapshot(session, ths.THS_CLOSED_TAB, "全部", tmp_path)
    assert result["range_filter"]["selected"] == "全部"
    assert result["range_filter"]["verified"] is True
    assert result["range_filter"]["before"]["selected"] == result["range_filter"]["after"]["selected"]


def test_range_change_during_scroll_is_rejected(tmp_path, monkeypatch):
    session = RangeSession([state("今年"), state("本月")])
    monkeypatch.setattr(ths, "_collect_scroll_loaded_snapshot", lambda *a: {"text": "", "scroll_complete": True})
    with pytest.raises(RuntimeError, match="采集期间时间范围改变"):
        ths._collect_range_snapshot(session, ths.THS_TRADES_TAB, "今年", tmp_path)


def test_custom_submits_query_and_records_real_ui_dates(tmp_path, monkeypatch):
    dates = ["2026-01-01", "2026-09-08"]
    session = RangeSession([state("自定义", dates=dates)] * 3)
    monkeypatch.setattr(ths, "_collect_scroll_loaded_snapshot", lambda *a: {"text": "", "scroll_complete": True})
    result = ths._collect_range_snapshot(session, ths.THS_TRADES_TAB, "自定义", tmp_path)
    assert session.queries == 1
    assert result["range_filter"]["custom_dates"] == dates
    assert result["range_filter"]["query_submitted"] is True


def test_custom_query_cannot_silently_revert_edited_dates(tmp_path):
    session = RangeSession([state("自定义", dates=["2025-01-01", "2026-09-08"]),
                            state("自定义", dates=["2026-09-01", "2026-09-08"])])
    with pytest.raises(RuntimeError, match="时间筛选未生效"):
        ths._collect_range_snapshot(session, ths.THS_TRADES_TAB, "自定义", tmp_path, timeout_seconds=0)


@pytest.mark.parametrize("end_quantity,end_cash,expected", [
    (1000, "0", "PASS"), (900, "100", "FAIL"), (1000, "100", "FAIL"),
])
def test_collection_rejects_auto_fills_between_holdings_and_trade_views(monkeypatch, end_quantity, end_cash, expected):
    monkeypatch.setattr(ths, "_positions_from_snapshot", lambda s: s["positions"])
    start = {"text": "现金余额\n0", "positions": [{"code": "159781", "quantity": 1000, "market_value": 1200}]}
    end = {"text": "现金余额\n" + end_cash,
           "positions": [{"code": "159781", "quantity": end_quantity, "market_value": 1210}]}
    assert ths._collection_consistency(start, end)["status"] == expected


def test_collection_missing_cash_is_not_evidence_of_unchanged_cash(monkeypatch):
    monkeypatch.setattr(ths, "_positions_from_snapshot", lambda s: [{"code": "159781", "quantity": 1000}])
    assert ths._collection_consistency({}, {})["status"] == "FAIL"


def test_closed_parser_keeps_two_completed_cycles_for_same_code():
    first = "2026-04-07\n513120\n测试ETF\n+86.70\n+10.65%\n-5%\n+15%\n1.167\n1.275\n+1%\n19\n1.80\n2026-03-11\n--"
    second = first.replace("2026-04-07", "2026-02-07").replace("2026-03-11", "2026-01-11").replace("+86.70", "+12.00")
    snapshot = {"text": first + "\n" + second, "tables": [{"rows": [[first], [second]]}]}
    records = ths._closed_positions_from_snapshot(snapshot)
    assert len(records) == 2
    assert {r["total_pnl"] for r in records} == {"+86.70", "+12.00"}
    assert all("cost_basis_verified" not in r for r in records)
