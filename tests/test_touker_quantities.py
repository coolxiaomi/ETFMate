from etfmate.browser.touker_grid import _grid_records_from_text


def _card(quantity: str) -> str:
    return (
        "截止日期：2026-11-16\n中证500ETF南方\n510500.SH\n"
        "最新基准价7.610现价7.771现价距基准+2.12%\n网格交易\n"
        f"委托股数:{quantity}\n"
    )


def test_separate_quantities_preserve_actual_values_without_common_fallback():
    record = _grid_records_from_text(_card("买入:100股(每笔) 卖出:1股 (每笔)"))[0]
    assert record["buy_quantity"] == "100"
    assert record["sell_quantity"] == "1"
    assert "order_quantity" not in record


def test_common_quantity_still_populates_both_sides():
    record = _grid_records_from_text(_card("500股 (每笔)"))[0]
    assert record["order_quantity"] == "500"
    assert record["buy_quantity"] == record["sell_quantity"] == "500"


def test_different_side_quantities_have_distinct_condition_identities():
    records = _grid_records_from_text(
        _card("买入：100股(每笔) 卖出：1股 (每笔)")
        + _card("买入：100股(每笔) 卖出：200股 (每笔)")
    )
    assert len(records) == 2
    assert records[0]["condition_identity"] != records[1]["condition_identity"]


def test_optional_limits_accept_labels_units_and_explicit_zero():
    record = _grid_records_from_text(_card("100股") + "最小底仓：0 份\n最大底仓：1,200 份\n")[0]
    assert record["min_base_quantity"] == "0"
    assert record["max_position_quantity"] == "1200"
    unset = _grid_records_from_text(_card("100股") + "最小底仓：未设置\n最大持仓：不限\n")[0]
    assert "min_base_quantity" not in unset and "max_position_quantity" not in unset


def test_malformed_visible_limit_is_preserved_for_quality_validation():
    record = _grid_records_from_text(_card("100股") + "最小底仓：-100份\n最大持仓：1.5份\n")[0]
    assert record["min_base_quantity"] == "-100"
    assert record["max_position_quantity"] == "1.5"
