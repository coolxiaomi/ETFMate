from __future__ import annotations

from io import StringIO
from datetime import datetime, time, timedelta, timezone
import urllib.request

import pandas as pd
import requests

from etfmate.market.indicators import enrich_indicators
from etfmate.storage.models import MarketSnapshot


def normalize_etf_code(code: str) -> str:
    value = code.strip().lower()
    if value.startswith(("sh", "sz", "bj")):
        value = value[2:]
    if "." in value:
        value = value.split(".", 1)[0]
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) != 6:
        raise ValueError(f"无法识别 ETF 代码: {code}")
    return digits


def market_prefix(code: str) -> str:
    code = normalize_etf_code(code)
    if code.startswith(("5", "6", "9")):
        return "sh"
    if code.startswith("8"):
        return "bj"
    return "sz"


def tencent_quote(codes: list[str]) -> dict[str, dict]:
    normalized = [normalize_etf_code(code) for code in codes]
    if not normalized:
        return {}
    query = ",".join(f"{market_prefix(code)}{code}" for code in normalized)
    req = urllib.request.Request("https://qt.gtimg.cn/q=" + query)
    req.add_header("User-Agent", "Mozilla/5.0")
    raw = urllib.request.urlopen(req, timeout=10).read().decode("gbk", errors="ignore")
    result: dict[str, dict] = {}
    for line in raw.strip().split(";"):
        if "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 50:
            continue
        code = key[2:]
        result[code] = {
            "code": code,
            "name": vals[1],
            "last_price": _float(vals[3]),
            "pct_chg": _float(vals[32]),
            "volume": _float(vals[36]),
            "amount": _float(vals[37]) * 10000,
            "amplitude_pct": _float(vals[43]),
            "turnover_pct": _float(vals[38]),
            "vol_ratio": _float(vals[49]),
            "quote_time": _quote_time(vals[30]),
        }
    return result


def baidu_daily_kline(code: str, start_time: str = "") -> pd.DataFrame:
    """百度股市通日 K 线，提供价格、成交量和成交额。"""
    code = normalize_etf_code(code)
    url = "https://finance.pae.baidu.com/selfselect/getstockquotation"
    params = {
        "all": "1",
        "isIndex": "false",
        "isBk": "false",
        "isBlock": "false",
        "isFutures": "false",
        "isStock": "true",
        "newFormat": "1",
        "group": "quotation_kline_ab",
        "finClientType": "pc",
        "code": code,
        "start_time": start_time,
        "ktype": "1",
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/vnd.finance-web.v1+json",
        "Origin": "https://gushitong.baidu.com",
        "Referer": "https://gushitong.baidu.com/",
    }
    resp = requests.get(url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if str(data.get("ResultCode", -1)) != "0":
        raise RuntimeError(f"百度 K 线返回异常: {data.get('ResultCode')}")
    market_data = data.get("Result", {}).get("newMarketData", {})
    keys = market_data.get("keys") or []
    rows = [row for row in (market_data.get("marketData") or "").split(";") if row]
    if not keys or not rows:
        raise RuntimeError("百度 K 线为空")
    df = pd.read_csv(StringIO("\n".join(rows)), names=keys)
    rename = {"time": "datetime"}
    df = df.rename(columns=rename)
    for column in ("open", "close", "high", "low", "volume", "amount"):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df.dropna(subset=["open", "close", "high", "low", "volume"])


def tencent_daily_kline(code: str, count: int = 260) -> pd.DataFrame:
    code = normalize_etf_code(code)
    symbol = f"{market_prefix(code)}{code}"
    resp = requests.get(
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
        params={"param": f"{symbol},day,,,{count},qfq"},
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {}).get(symbol, {})
    rows = data.get("qfqday") or data.get("day") or []
    if not rows:
        raise RuntimeError("腾讯 K 线为空")
    normalized_rows = [row[:6] for row in rows if len(row) >= 6]
    df = pd.DataFrame(normalized_rows, columns=["datetime", "open", "close", "high", "low", "volume"])
    for column in ("open", "close", "high", "low", "volume"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["amount"] = float("nan")
    return df.dropna(subset=["open", "close", "high", "low", "volume"])


def fetch_daily_ohlcv(code: str, count: int = 260) -> tuple[pd.DataFrame, str]:
    """Return daily OHLCV data with amount when the upstream source provides it."""
    errors: list[str] = []
    for source, fetcher in (("baidu", baidu_daily_kline), ("tencent", tencent_daily_kline)):
        try:
            if source == "tencent":
                df = fetcher(code, count=count)
            else:
                df = fetcher(code)
                if len(df) > count:
                    df = df.tail(count)
            normalized = _normalize_ohlcv(df)
            return normalized, f"kline:{source}"
        except Exception as exc:
            errors.append(f"{source}:{type(exc).__name__}")
    raise RuntimeError("日线数据获取失败: " + ",".join(errors))


def build_market_snapshot(code: str) -> MarketSnapshot:
    code = normalize_etf_code(code)
    quote = tencent_quote([code]).get(code, {})
    quality = ["quote:tencent" if quote else "quote:missing"]
    enriched = None
    signal_is_complete = False
    signal_volume_basis = "unknown"
    try:
        # Baidu's prices are quantized to cents. Tencent qfq retains mill prices,
        # but has no daily amount. Join only after checking every complete date,
        # all four price fields and original volume units across both sources.
        precise, complete, volume_basis = _select_signal_days(tencent_daily_kline(code), quote.get("quote_time"))
        amount_source, amount_complete, _ = _select_signal_days(baidu_daily_kline(code), quote.get("quote_time"))
        precise, amount_source, deferred = _defer_unaligned_current_close(precise, amount_source, quote)
        if deferred:
            quality.append("signal_deferred:current_daily_close_quote_mismatch")
        kline = _join_daily_sources(precise, amount_source)
        enriched = enrich_indicators(kline).tail(1).iloc[0]
        signal_is_complete = complete and amount_complete
        signal_volume_basis = volume_basis
        quality.append("kline:tencent_qfq+baidu_amount;price_adjustment:qfq;volume_unit:share;amount_unit:CNY")
        quality.append(f"daily_alignment:{len(kline)}")
    except Exception as exc:
        quality.append(f"kline:error:daily_alignment:{type(exc).__name__}:{exc}")

    def latest(name: str) -> float | None:
        if enriched is None or name not in enriched:
            return None
        value = enriched[name]
        if pd.isna(value):
            return None
        return float(value)

    last_price = float(quote.get("last_price") or latest("close") or 0)
    return MarketSnapshot(
        code=code,
        name=str(quote.get("name") or code),
        last_price=last_price,
        pct_chg=float(quote.get("pct_chg") or latest("ratio") or 0),
        volume=float(quote.get("volume") or latest("volume") or 0),
        amount=float(quote.get("amount") or latest("amount") or 0),
        amplitude_pct=quote.get("amplitude_pct"),
        turnover_pct=quote.get("turnover_pct"),
        vol_ratio=quote.get("vol_ratio"),
        ma5=latest("ma5"),
        ma5_slope_3=latest("ma5_slope_3"),
        ma10=latest("ma10"),
        ma20=latest("ma20"),
        ma60=latest("ma60"),
        ma120=latest("ma120"),
        ma200=latest("ma200"),
        boll_upper=latest("boll_upper"),
        boll_mid=latest("boll_mid"),
        boll_lower=latest("boll_lower"),
        boll_position=latest("boll_position"),
        atr7=latest("atr7"),
        atr7_pct=latest("atr7_pct"),
        atr14=latest("atr14"),
        atr14_pct=latest("atr14_pct"),
        atr30=latest("atr30"),
        atr30_pct=latest("atr30_pct"),
        atr60=latest("atr60"),
        atr60_pct=latest("atr60_pct"),
        atr20_avg=latest("atr20_avg"),
        atr_expansion_ratio=latest("atr_expansion_ratio"),
        bias5_ratio=latest("bias5_ratio"),
        bias6=latest("bias6"),
        bias12=latest("bias12"),
        bias24=latest("bias24"),
        vol_ma5=latest("vol_ma5"),
        vol_ma20=latest("vol_ma20"),
        vol_ratio_1_5=latest("vol_ratio_1_5"),
        vol_ratio_5_20=latest("vol_ratio_5_20"),
        amount_avg20=latest("amount_avg20"),
        amount_ratio20=latest("amount_ratio20"),
        rsi6=latest("rsi6"),
        rsi14=latest("rsi14"),
        macd_dif=latest("macd_dif"),
        macd_dea=latest("macd_dea"),
        macd_hist=latest("macd_hist"),
        ret3=latest("ret3"),
        ret5=latest("ret5"),
        ret20=latest("ret20"),
        ret60=latest("ret60"),
        max_drawdown_60=latest("max_drawdown_60"),
        ma20_slope_pct=latest("ma20_slope_pct"),
        kline_days=int(latest("kline_days") or 0) if latest("kline_days") is not None else None,
        data_quality=";".join(quality),
        signal_close=latest("close"),
        signal_date=str(enriched["datetime"]) if enriched is not None and "datetime" in enriched else None,
        previous_rsi6=latest("previous_rsi6"),
        recent_oversold_count5=latest("recent_oversold_count5"),
        quote_time=quote.get("quote_time"),
        signal_is_complete=signal_is_complete,
        signal_volume_basis=signal_volume_basis,
    )


def _defer_unaligned_current_close(
    precise: pd.DataFrame, amount_source: pd.DataFrame, quote: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    """Do not score a just-closed provisional bar against a different close.

    Tencent can expose cent-rounded current-day OHLC after the session ends,
    while its quote retains mill prices. Keep the quote for price plans and
    explicitly defer both daily sources to the preceding matched session.
    Never replace OHLC with guessed values or conceal historical misalignment.
    """
    from decimal import Decimal

    if precise.empty or amount_source.empty:
        return precise, amount_source, False
    try:
        stamp = datetime.fromisoformat(str(quote.get("quote_time")))
    except (TypeError, ValueError):
        return precise, amount_source, False
    if stamp.tzinfo is None:
        return precise, amount_source, False
    stamp = stamp.astimezone(timezone(timedelta(hours=8)))
    day = stamp.date().isoformat()
    if stamp.time() < time(15, 0) or str(precise["datetime"].max()) != day:
        return precise, amount_source, False
    # A lagging amount source must still fail the existing date-alignment gate.
    if str(amount_source["datetime"].max()) != day:
        return precise, amount_source, False
    close = Decimal(str(precise.loc[precise["datetime"] == day, "close"].iloc[-1]))
    price = Decimal(str(quote.get("last_price")))
    if not close.is_finite() or not price.is_finite() or close <= 0 or price <= 0:
        raise ValueError("收盘日线与报价缺少有效价格，不能核验精度")
    if close == price:
        return precise, amount_source, False
    return (precise.loc[precise["datetime"] < day].copy(),
            amount_source.loc[amount_source["datetime"] < day].copy(), True)


def _quote_time(value: str) -> str | None:
    """Keep the upstream quote timestamp; retrieval time is not market time."""
    try:
        return datetime.strptime(str(value), "%Y%m%d%H%M%S").replace(
            tzinfo=timezone(timedelta(hours=8))
        ).isoformat()
    except (TypeError, ValueError):
        return None


def _join_daily_sources(precise: pd.DataFrame, amount_source: pd.DataFrame) -> pd.DataFrame:
    """Keep qfq OHLC and original share volume; add same-date original CNY amount.

    Adjustment compatibility is verified to Baidu's half-cent quantization bound.
    Amount is an original traded cash amount and is never price-adjusted. The
    volume tolerance is one 100-share lot, accounting for Tencent lot rounding.
    A failed alignment has no fallback to coarse or zero-filled daily data.
    """
    for source, frame in (("腾讯", precise), ("百度", amount_source)):
        if "datetime" not in frame or frame.empty or frame["datetime"].duplicated().any():
            raise ValueError(f"{source}日线日期缺失、重复或样本为空")
    left = precise.set_index("datetime")
    right = amount_source.set_index("datetime")
    missing = sorted(set(left.index) - set(right.index))
    if missing:
        raise ValueError(f"百度成交额缺少腾讯同日样本:{','.join(missing[:3])}")
    # Never silently use the old intersection when one provider lags a full day.
    if str(left.index.max()) != str(right.index.max()):
        raise ValueError(f"日线最新完成日期不一致:腾讯{left.index.max()}/百度{right.index.max()}")
    missing_prices = sorted(day for day in right.index
                            if left.index.min() <= day <= left.index.max() and day not in left.index)
    if missing_prices:
        raise ValueError(f"腾讯精确价格缺少百度同日样本:{','.join(missing_prices[:3])}")
    matched = right.loc[left.index]
    out = left.copy()
    for column in ("open", "high", "low", "close"):
        p = pd.to_numeric(out[column], errors="coerce")
        q = pd.to_numeric(matched[column], errors="coerce")
        valid = p.map(lambda value: 0 < value < float("inf")) & q.map(lambda value: 0 < value < float("inf"))
        compatible = (p - q).abs() <= 0.0050001
        bad = valid & compatible
        if not bad.all():
            day = str(bad.index[~bad][0])
            raise ValueError(f"复权或价格精度口径不一致:{day}:{column}:腾讯{p.loc[day]}/百度{q.loc[day]}")
        out[column] = p
    if ((out["high"] < out[["open", "close", "low"]].max(axis=1))
            | (out["low"] > out[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("腾讯精确日线高低价关系无效")
    volume = pd.to_numeric(out["volume"], errors="coerce") * 100
    other_volume = pd.to_numeric(matched["volume"], errors="coerce")
    valid_volume = volume.map(lambda value: 0 <= value < float("inf")) & other_volume.map(lambda value: 0 <= value < float("inf"))
    compatible_volume = (volume - other_volume).abs() <= 100.0001
    if not (valid_volume & compatible_volume).all():
        day = str(volume.index[~(valid_volume & compatible_volume)][0])
        raise ValueError(f"日线成交量单位或口径不一致:{day}:腾讯手乘100={volume.loc[day]}/百度份={other_volume.loc[day]}")
    amount = pd.to_numeric(matched["amount"], errors="coerce")
    if not amount.map(lambda value: 0 <= value < float("inf")).all() or not amount.tail(20).gt(0).any():
        raise ValueError("日线成交额缺失或无效，不能用零占位判断流动性")
    out["volume"], out["amount"] = volume, amount
    return out.reset_index().sort_values("datetime").reset_index(drop=True)


def _select_signal_days(df: pd.DataFrame, quote_time: str | None) -> tuple[pd.DataFrame, bool, str]:
    """Score completed daily samples, excluding the partial session at source time.

    The current quote still supplies order reference prices. A morning cumulative
    volume must never be scored against full-session historical daily volumes.
    Missing upstream time keeps completion unknown instead of guessing from the
    local machine clock. Freshness itself is checked by the report quality gate.
    """
    if "datetime" not in df.columns:
        return df.copy(), False, "unknown"
    out = df.copy()
    dates = pd.to_datetime(out["datetime"], errors="coerce")
    if dates.isna().any() or dates.dt.normalize().duplicated().any():
        raise ValueError("日线日期缺失、无效或重复，不能确认同源指标顺序")
    out = out.assign(_signal_day=dates.dt.date).sort_values("_signal_day")
    out["datetime"] = pd.to_datetime(out["datetime"]).dt.strftime("%Y-%m-%d")
    try:
        stamp = datetime.fromisoformat(str(quote_time))
        if stamp.tzinfo is None:
            return out.drop(columns="_signal_day"), False, "unknown"
        stamp = stamp.astimezone(timezone(timedelta(hours=8)))
    except (TypeError, ValueError):
        return out.drop(columns="_signal_day"), False, "unknown"
    if (out["_signal_day"] > stamp.date()).any():
        raise ValueError("日线日期晚于真实报价时间，拒绝混合未来样本")
    # All instruments in the research scope are listed on mainland exchanges.
    # Their listing session is complete at 15:00, including cross-border ETFs.
    completed = out["_signal_day"] < stamp.date()
    if stamp.time() >= time(15, 0):
        completed |= out["_signal_day"] == stamp.date()
    out = out.loc[completed].drop(columns="_signal_day")
    if out.empty:
        raise ValueError("尚无已完成交易日样本，不能使用盘中全日量作技术判断")
    return out.reset_index(drop=True), True, "completed_daily"


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    rename = {"date": "trade_date", "datetime": "trade_date", "time": "trade_date"}
    out = out.rename(columns=rename)
    if "trade_date" not in out.columns:
        out["trade_date"] = range(len(out))
    for column in ("open", "high", "low", "close", "volume"):
        if column not in out.columns:
            raise ValueError(f"K线缺少字段: {column}")
        out[column] = pd.to_numeric(out[column], errors="coerce")
    if "amount" not in out.columns:
        out["amount"] = 0.0
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce").fillna(0.0)
    columns = ["trade_date", "open", "high", "low", "close", "volume", "amount"]
    return out[columns].dropna(subset=["open", "high", "low", "close", "volume"]).reset_index(drop=True)


def _float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
