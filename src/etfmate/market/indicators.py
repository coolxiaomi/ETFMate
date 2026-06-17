from __future__ import annotations

import pandas as pd


def enrich_indicators(df: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"K 线缺少字段: {', '.join(sorted(missing))}")
    out = df.copy()
    close = out["close"].astype(float)
    high = out["high"].astype(float)
    low = out["low"].astype(float)
    volume = out["volume"].astype(float)

    for window in (5, 10, 20, 60):
        out[f"ma{window}"] = close.rolling(window).mean()
    out["vol_ma5"] = volume.rolling(5).mean()
    out["vol_ma20"] = volume.rolling(20).mean()

    mid = close.rolling(20).mean()
    std = close.rolling(20).std()
    out["boll_mid"] = mid
    out["boll_upper"] = mid + 2 * std
    out["boll_lower"] = mid - 2 * std

    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    out["atr14"] = tr.rolling(14).mean()
    out["atr14_pct"] = out["atr14"] / close * 100

    for window in (6, 12, 24):
        ma = close.rolling(window).mean()
        out[f"bias{window}"] = (close - ma) / ma * 100
    return out
