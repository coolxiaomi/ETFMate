import pandas as pd
import pytest

from etfmate.market import providers


def frames():
    precise = pd.DataFrame({
        "datetime": ["2026-09-07", "2026-09-08"],
        "open": [9.021, 9.10], "close": [9.024, 9.05],
        "high": [9.076, 9.12], "low": [9.009, 9.04],
        "volume": [1000, 2000], "amount": [float("nan")] * 2,
    })
    amount = precise.assign(volume=[100000, 200000], amount=[902400, 1809400])
    return precise, amount


def test_rounded_after_close_bar_defers_both_sources_without_replacing_prices():
    precise, amount = frames()
    p, a, deferred = providers._defer_unaligned_current_close(
        precise, amount, {"quote_time": "2026-09-08T15:45:59+08:00", "last_price": 9.047})
    assert deferred
    assert p.datetime.tolist() == a.datetime.tolist() == ["2026-09-07"]
    assert p.close.iloc[-1] == 9.024
    assert precise.close.iloc[-1] == 9.05


@pytest.mark.parametrize("stamp,price", [
    ("2026-09-08T15:45:59+08:00", 9.05),
    ("2026-09-08T14:45:59+08:00", 9.047),
    (None, 9.047),
    ("2026-09-09T15:45:59+08:00", 9.047),
])
def test_no_deferral_without_current_completed_close_mismatch(stamp, price):
    p, a = frames()
    out, _, deferred = providers._defer_unaligned_current_close(p, a, {
        "quote_time": stamp, "last_price": price})
    assert not deferred
    assert len(out) == 2


def test_deferral_cannot_hide_lagging_amount_source():
    p, a = frames()
    out, amount, deferred = providers._defer_unaligned_current_close(p, a.iloc[:-1], {
        "quote_time": "2026-09-08T15:45:59+08:00", "last_price": 9.047})
    assert not deferred
    with pytest.raises(ValueError, match="缺少腾讯同日"):
        providers._join_daily_sources(out, amount)


def test_snapshot_records_deferral_and_preserves_current_quote(monkeypatch):
    dates = pd.bdate_range(end="2026-09-08", periods=140).strftime("%Y-%m-%d")
    p = pd.DataFrame({"datetime": dates, "open": 9.021, "close": 9.024,
                      "high": 9.076, "low": 9.009, "volume": 1000,
                      "amount": float("nan")})
    p.loc[len(p)-1, "close"] = 9.05
    a = p.assign(volume=100000, amount=902400)
    monkeypatch.setattr(providers, "tencent_quote", lambda codes: {codes[0]: {
        "quote_time": "2026-09-08T15:45:59+08:00", "last_price": 9.047}})
    monkeypatch.setattr(providers, "tencent_daily_kline", lambda code: p)
    monkeypatch.setattr(providers, "baidu_daily_kline", lambda code: a)
    snapshot = providers.build_market_snapshot("518880")
    assert snapshot.last_price == 9.047
    assert snapshot.signal_close == 9.024
    assert snapshot.signal_date == "2026-09-07"
    assert snapshot.signal_is_complete
    assert "signal_deferred:current_daily_close_quote_mismatch" in snapshot.data_quality
