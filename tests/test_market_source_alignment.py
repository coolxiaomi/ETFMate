import pandas as pd
import pytest

from etfmate.market import providers


def sources():
    precise = pd.DataFrame({
        "datetime": pd.bdate_range(end="2026-09-07", periods=260).strftime("%Y-%m-%d"),
        "open": [1.876] * 260, "close": [1.895] * 260,
        "high": [1.898] * 260, "low": [1.872] * 260,
        "volume": [724533.0] * 260, "amount": [float("nan")] * 260,
    })
    rounded = precise.assign(open=1.88, close=1.90, high=1.90, low=1.87,
                             volume=72453300.0, amount=136603980.0)
    return precise, rounded


def test_exact_qfq_prices_and_original_amount_keep_full_analysis_window():
    precise, rounded = sources()
    result = providers._join_daily_sources(precise, rounded)
    assert len(result) == 260
    assert result.close.iloc[-1] == 1.895
    assert result.volume.iloc[-1] == 72453300.0
    assert result.amount.iloc[-1] == 136603980.0


@pytest.mark.parametrize("column", ["open", "high", "low", "close"])
def test_incompatible_adjustment_or_any_price_field_cannot_be_joined(column):
    precise, rounded = sources()
    rounded.loc[0, column] *= 2
    with pytest.raises(ValueError, match="复权或价格精度"):
        providers._join_daily_sources(precise, rounded)


def test_volume_conversion_requires_a_match_including_old_days():
    precise, rounded = sources()
    rounded.loc[0, "volume"] /= 100
    with pytest.raises(ValueError, match="成交量单位"):
        providers._join_daily_sources(precise, rounded)


def test_small_lot_rounding_is_allowed_but_large_divergence_is_not():
    precise, rounded = sources()
    rounded.loc[0, "volume"] -= 49
    assert len(providers._join_daily_sources(precise, rounded)) == 260
    rounded.loc[0, "volume"] -= 100
    with pytest.raises(ValueError, match="成交量单位"):
        providers._join_daily_sources(precise, rounded)


def test_missing_amount_dates_or_a_lagging_provider_cannot_be_silently_dropped():
    precise, rounded = sources()
    with pytest.raises(ValueError, match="缺少腾讯同日"):
        providers._join_daily_sources(precise, rounded.drop(index=10))
    with pytest.raises(ValueError, match="腾讯精确价格缺少百度同日"):
        providers._join_daily_sources(precise.drop(index=10), rounded)
    with pytest.raises(ValueError, match="最新完成日期不一致"):
        providers._join_daily_sources(precise.iloc[:-1], rounded)


def test_failed_alignment_never_falls_back_to_cent_prices(monkeypatch):
    precise, rounded = sources()
    rounded.loc[0, "close"] = 3.8
    monkeypatch.setattr(providers, "tencent_quote", lambda codes: {codes[0]: {
        "last_price": 1.913, "quote_time": "2026-09-08T10:38:54+08:00",
    }})
    monkeypatch.setattr(providers, "tencent_daily_kline", lambda code: precise)
    monkeypatch.setattr(providers, "baidu_daily_kline", lambda code: rounded)
    result = providers.build_market_snapshot("159687")
    assert "kline:error:daily_alignment" in result.data_quality
    assert result.rsi6 is None
    assert result.signal_is_complete is False
