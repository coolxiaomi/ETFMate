import pandas as pd
import pytest

from etfmate.market import providers


def daily_frame():
    days = pd.bdate_range(end="2026-09-08", periods=80)
    frame = pd.DataFrame({
        "datetime": days.strftime("%Y-%m-%d"),
        "open": [1.0] * 80, "high": [1.01] * 80,
        "low": [.99] * 80, "close": [1.0] * 80,
        "volume": [1000.0] * 80, "amount": [1_000_000.0] * 80,
    })
    frame.loc[79, ["close", "high", "volume", "amount"]] = [1.1, 1.11, 200.0, 200_000.0]
    return frame


def snapshot(monkeypatch, quote_time, last_price=1.103):
    monkeypatch.setattr(providers, "tencent_quote", lambda codes: {
        codes[0]: {"last_price": last_price, "amount": 200_000.0, "quote_time": quote_time},
    })
    monkeypatch.setattr(providers, "baidu_daily_kline", lambda code: daily_frame())
    monkeypatch.setattr(providers, "tencent_daily_kline", lambda code: daily_frame().assign(volume=lambda df: df.volume / 100))
    return providers.build_market_snapshot("510500")


def test_morning_quote_does_not_make_daily_volume_look_weak(monkeypatch):
    result = snapshot(monkeypatch, "2026-09-08T10:38:54+08:00")
    assert result.last_price == 1.103
    assert result.signal_close == 1.0
    assert result.signal_date == "2026-09-07"
    assert result.vol_ratio_1_5 == 1.0
    assert result.amount_avg20 == 1_000_000.0
    assert result.kline_days == 79
    assert result.signal_is_complete is True
    assert result.signal_volume_basis == "completed_daily"


def test_closing_quote_can_use_completed_current_day(monkeypatch):
    result = snapshot(monkeypatch, "2026-09-08T15:00:03+08:00", last_price=1.1)
    assert result.signal_date == "2026-09-08"
    assert result.signal_close == 1.1
    assert result.vol_ratio_1_5 == pytest.approx(200 / 840)
    assert result.signal_is_complete is True


@pytest.mark.parametrize("stamp", [None, "", "bad", "2026-09-08T10:38:54"])
def test_missing_source_time_never_proves_daily_completion(monkeypatch, stamp):
    result = snapshot(monkeypatch, stamp)
    assert result.signal_is_complete is False
    assert result.signal_volume_basis == "unknown"


def test_daily_sequence_is_sorted_before_indicators():
    selected, complete, _ = providers._select_signal_days(
        daily_frame().iloc[::-1], "2026-09-08T10:38:54+08:00",
    )
    assert selected.iloc[-1]["datetime"] == "2026-09-07"
    assert complete is True


def test_future_or_duplicate_daily_dates_are_rejected():
    with pytest.raises(ValueError, match="晚于"):
        providers._select_signal_days(daily_frame(), "2026-09-07T15:00:00+08:00")
    duplicated = pd.concat([daily_frame(), daily_frame().tail(1)])
    with pytest.raises(ValueError, match="重复"):
        providers._select_signal_days(duplicated, "2026-09-08T15:00:00+08:00")


def test_quote_parser_preserves_exchange_timestamp(monkeypatch):
    fields = ["0"] * 50
    fields[1], fields[3], fields[30] = "500ETF", "7.838", "20260908103854"

    class Response:
        def read(self):
            return ('v_sh510500="' + "~".join(fields) + '";').encode("gbk")

    monkeypatch.setattr(providers.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    result = providers.tencent_quote(["510500"])["510500"]
    assert result["quote_time"] == "2026-09-08T10:38:54+08:00"
    assert result["last_price"] == 7.838
