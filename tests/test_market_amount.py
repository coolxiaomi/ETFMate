import pandas as pd
import pytest

from etfmate.market import providers


def daily(amount):
    return pd.DataFrame({
        "open": [1.0] * 80, "high": [1.1] * 80,
        "low": [0.9] * 80, "close": [1.0] * 80,
        "volume": [1000.0] * 80, "amount": amount,
    })


def test_snapshot_uses_real_historical_amount(monkeypatch):
    monkeypatch.setattr(providers, "tencent_quote", lambda codes: {codes[0]: {"last_price": 1.0, "amount": 999}})
    monkeypatch.setattr(providers, "baidu_daily_kline", lambda code: daily([100_000_000.0] * 80))
    monkeypatch.setattr(providers, "tencent_daily_kline", lambda code: pytest.fail("complete source should be used"))
    result = providers.build_market_snapshot("510500")
    assert result.amount_avg20 == 100_000_000.0
    assert result.amount == 999
    assert "kline:baidu" in result.data_quality


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1.0, 0.0])
def test_invalid_amount_cannot_become_low_liquidity_evidence(monkeypatch, invalid):
    monkeypatch.setattr(providers, "tencent_quote", lambda codes: {})
    monkeypatch.setattr(providers, "baidu_daily_kline", lambda code: daily([invalid] * 80))
    monkeypatch.setattr(providers, "tencent_daily_kline", lambda code: daily([float("nan")] * 80))
    result = providers.build_market_snapshot("510500")
    assert result.amount_avg20 is None
    assert "kline:error" in result.data_quality


def test_tencent_missing_amount_remains_unknown(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"sh510500": {"day": [["2026-09-07", "1", "1", "1.1", "0.9", "1000"]]}}}

    monkeypatch.setattr(providers.requests, "get", lambda *args, **kwargs: Response())
    assert providers.tencent_daily_kline("510500")["amount"].isna().all()
