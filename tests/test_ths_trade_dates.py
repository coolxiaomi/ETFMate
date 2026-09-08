from etfmate.browser.ths_account import _merge_trade_snapshots, _trade_records_from_text


def row(date, code, side, price, quantity=500):
    return f"{date}\n{code}\nETF名称\n{side}\n{price:.3f}\n{quantity}\n{price * quantity:.2f}\n0.20\n--"


def test_date_belongs_to_current_trade_and_last_row_is_preserved():
    text = "\n".join([
        row("2026-09-07", "159687", "卖出", 1.877),
        row("2026-09-04", "159781", "买入", 1.030),
        row("2026-09-01", "560280", "卖出", 1.534),
        "Copyright 浙江同花顺网络科技有限公司",
    ])
    trades = _trade_records_from_text(text)
    assert [(t["code"], t["trade_date"], t["amount"]) for t in trades] == [
        ("159687", "2026-09-07", "938.50"),
        ("159781", "2026-09-04", "515.00"),
        ("560280", "2026-09-01", "767.00"),
    ]
    assert "2026-09-04" not in trades[0]["raw_text"]


def test_six_digit_trade_quantity_is_not_mistaken_for_next_security():
    trades = _trade_records_from_text(row("2026-09-07", "510500", "买入", 7.000, 100000))
    assert len(trades) == 1
    assert trades[0]["quantity"] == "100000"


def test_date_and_side_prevent_distinct_transactions_being_deduplicated():
    text = "\n".join([
        row("2026-09-07", "159687", "卖出", 1.877),
        row("2026-09-04", "159687", "卖出", 1.877),
        row("2026-09-04", "159687", "买入", 1.877),
    ])
    trades, _ = _merge_trade_snapshots({"本月": {"text": text}, "今年": {"text": text}})
    assert len(trades) == 3


def test_missing_row_date_cannot_borrow_next_rows_date():
    text = "159687\nETF名称\n卖出\n1.877\n500\n938.50\n0.20\n--\n" + row("2026-09-04", "159781", "买入", 1.030)
    trades = _trade_records_from_text(text)
    assert len(trades) == 1
    assert trades[0]["code"] == "159781"


def table_screen(rows):
    return {"tables": [{"headers": ["成交日期\n代码\n名称\n类型"], "rows": [[value] for value in rows]}]}


def test_two_identical_fills_in_separate_rows_survive_overlapping_views():
    fill = row("2026-09-07", "159687", "卖出", 1.877)
    first, second = table_screen([fill]), table_screen([fill, fill])
    trades, quality = _merge_trade_snapshots({
        "本月": {"scroll_snapshots": [first]},
        "今年": {"scroll_snapshots": [second]},
    })
    assert len(trades) == 2
    assert [t["source_occurrence_ordinal"] for t in trades] == [1, 2]
    assert {s["view"] for s in trades[0]["source_evidence"]} == {"本月", "今年"}
    assert not quality["ambiguities"]
    assert quality["cycle_complete"] is False


def test_same_key_across_scroll_screens_is_ambiguous_not_extra_trades():
    screen = table_screen([row("2026-09-07", "159687", "卖出", 1.877)])
    trades, quality = _merge_trade_snapshots({"今年": {"scroll_snapshots": [screen, screen]}})
    assert len(trades) == 1
    assert trades[0]["occurrence_ambiguous"] is True
    assert quality["ambiguities"]


def test_merged_text_repetition_is_not_invented_as_two_trades():
    fill = row("2026-09-07", "159687", "卖出", 1.877)
    trades, quality = _merge_trade_snapshots({"今年": {"text": fill + "\n" + fill, "scroll_steps": 2}})
    assert len(trades) == 1
    assert quality["ambiguities"]


def test_execution_id_takes_priority_over_equal_economic_fields():
    headers = ["成交编号", "成交日期", "代码", "名称", "类型", "成交价格", "成交数量", "成交金额"]
    common = ["2026-09-07", "159687", "ETF名称", "卖出", "1.877", "500", "938.50"]
    screen = {"tables": [{"headers": headers, "rows": [["F1", *common], ["F2", *common]]}]}
    trades, quality = _merge_trade_snapshots({"今年": {"scroll_snapshots": [screen, screen]}})
    assert len(trades) == 2
    assert {t["成交编号"] for t in trades} == {"F1", "F2"}
    assert {t["side"] for t in trades} == {"卖出"}
    assert not quality["ambiguities"]
    anonymous = table_screen([row("2026-09-07", "159687", "卖出", 1.877)])
    mixed, _ = _merge_trade_snapshots({"今年": {"scroll_snapshots": [screen]}, "本月": {"scroll_snapshots": [anonymous]}})
    assert len(mixed) == 2
    assert all(t["source_occurrence_key"].startswith("trade_id:") for t in mixed)
