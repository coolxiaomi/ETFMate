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

    for window in (5, 10, 20, 60, 120, 200):
        out[f"ma{window}"] = close.rolling(window).mean()
    out["ma5_slope_3"] = (out["ma5"] - out["ma5"].shift(3)) / out["ma5"].shift(3)
    out["vol_ma5"] = volume.rolling(5).mean()
    out["vol_ma20"] = volume.rolling(20).mean()
    out["vol_ratio_1_5"] = volume / out["vol_ma5"]
    out["vol_ratio_5_20"] = out["vol_ma5"] / out["vol_ma20"]
    if "amount" in out.columns:
        amount = out["amount"].astype(float)
        out["amount_avg20"] = amount.rolling(20).mean()
        out["amount_ratio20"] = amount / out["amount_avg20"]
    else:
        out["amount_avg20"] = None
        out["amount_ratio20"] = None

    mid = close.rolling(20).mean()
    std = close.rolling(20).std()
    out["boll_mid"] = mid
    out["boll_upper"] = mid + 2 * std
    out["boll_lower"] = mid - 2 * std
    boll_width = out["boll_upper"] - out["boll_lower"]
    out["boll_position"] = ((close - out["boll_lower"]) / boll_width).clip(lower=0, upper=1)

    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    for window in (7, 14, 30, 60):
        out[f"atr{window}"] = tr.rolling(window).mean()
        out[f"atr{window}_pct"] = out[f"atr{window}"] / close * 100
    out["atr20_avg"] = out["atr14"].rolling(20).mean()
    out["atr_expansion_ratio"] = out["atr14"] / out["atr20_avg"]

    out["bias5_ratio"] = (close - out["ma5"]) / out["ma5"]
    for window in (6, 12, 24):
        ma = close.rolling(window).mean()
        out[f"bias{window}"] = (close - ma) / ma * 100
    delta = close.diff()
    out["rsi6"] = _rsi(delta, 6)
    out["rsi14"] = _rsi(delta, 14)
    out["previous_rsi6"] = out["rsi6"].shift(1)
    oversold = ((out["rsi6"] <= 30) & ((out["bias5_ratio"] <= -0.03) | (out["boll_position"] <= 0.2))).astype(float)
    # Unknown history is not evidence of zero oversold days. Exclude the current sample.
    oversold = oversold.where(out[["rsi6", "bias5_ratio", "boll_position"]].notna().all(axis=1))
    out["recent_oversold_count5"] = oversold.shift(1).rolling(5, min_periods=5).sum()
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    out["macd_dif"] = ema12 - ema26
    out["macd_dea"] = out["macd_dif"].ewm(span=9, adjust=False).mean()
    out["macd_hist"] = (out["macd_dif"] - out["macd_dea"]) * 2
    for window in (3, 5, 20, 60):
        out[f"ret{window}"] = (close / close.shift(window) - 1) * 100
    rolling_peak = close.rolling(60).max()
    out["max_drawdown_60"] = (close / rolling_peak - 1) * 100
    out["ma20_slope_pct"] = (out["ma20"] / out["ma20"].shift(5) - 1) * 100
    out["kline_days"] = range(1, len(out) + 1)
    return out


def _rsi(delta: pd.Series, window: int) -> pd.Series:
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.mask(loss == 0)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((loss == 0) & (gain > 0), 100)
    rsi = rsi.mask((gain == 0) & (loss > 0), 0)
    return rsi.mask((gain == 0) & (loss == 0), 50)
