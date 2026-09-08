from __future__ import annotations

from io import StringIO
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
    kline_errors: list[str] = []
    for source, fetcher in (("baidu", baidu_daily_kline), ("tencent", tencent_daily_kline)):
        try:
            kline = fetcher(code)
            amounts = pd.to_numeric(kline["amount"], errors="coerce").tail(20)
            if amounts.empty or amounts.isna().any() or not amounts.map(lambda value: 0 <= value < float("inf")).all() or not amounts.gt(0).any():
                raise ValueError("日线成交额缺失或无效，不能用零占位判断流动性")
            enriched = enrich_indicators(kline).tail(1).iloc[0]
            quality.append(f"kline:{source}")
            break
        except Exception as exc:
            kline_errors.append(f"{source}:{type(exc).__name__}")
    if enriched is None:
        quality.append("kline:error:" + ",".join(kline_errors))

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
    )


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
