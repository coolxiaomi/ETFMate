"""Causal, explainable technical conditions; no allocation or execution authority."""
from __future__ import annotations

from math import isfinite
from typing import Any

from etfmate.storage.models import MarketSnapshot

TECHNICAL_CONTRACT = "multi_indicator_v2"


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (ValueError, TypeError):
        return None


def assess_technical(market: MarketSnapshot) -> dict[str, Any]:
    """Use one daily sample for confirmation; a quote alone never proves recovery."""
    fields = ("ma5", "ma10", "ma20", "ma60", "ma5_slope_3", "bias5_ratio",
              "bias12", "bias24", "rsi6", "rsi14", "boll_position",
              "vol_ratio_1_5", "vol_ratio_5_20", "previous_rsi6", "recent_oversold_count5")
    v = {field: _finite(getattr(market, field)) for field in fields}
    sample_close = _finite(market.signal_close)
    history_available = (sample_close is not None and sample_close > 0
                         and v["previous_rsi6"] is not None and 0 <= v["previous_rsi6"] <= 100
                         and v["recent_oversold_count5"] is not None
                         and 0 <= v["recent_oversold_count5"] <= 5
                         and v["recent_oversold_count5"].is_integer())
    close = sample_close if sample_close is not None else _finite(market.last_price)
    core = {"价格": close, **{key: v[key] for key in (
        "ma5", "ma10", "ma20", "ma60", "ma5_slope_3", "bias5_ratio",
        "rsi6", "boll_position", "vol_ratio_1_5", "vol_ratio_5_20")}}
    missing = [key for key, value in core.items() if value is None]
    missing.extend(key for key in ("bias12", "bias24", "rsi14") if v[key] is None)
    sufficient = all(value is not None for value in core.values())
    sufficient = sufficient and bool(close and close > 0) and (market.kline_days or 0) >= 60
    sufficient = sufficient and all(v[key] is not None and v[key] > 0 for key in ("ma5", "ma10", "ma20", "ma60"))
    sufficient = sufficient and v["rsi6"] is not None and 0 <= v["rsi6"] <= 100
    sufficient = sufficient and v["boll_position"] is not None and 0 <= v["boll_position"] <= 1
    sufficient = sufficient and all(v[key] is not None and v[key] >= 0 for key in ("vol_ratio_1_5", "vol_ratio_5_20"))
    sufficient = sufficient and not any(word in str(market.data_quality) for word in ("missing", "error"))
    incomplete_daily = market.signal_is_complete is False or market.signal_volume_basis in {"intraday_daily", "unknown"}
    sufficient = sufficient and not incomplete_daily

    def fmt(key: str, digits: int = 2, scale: float = 1) -> str:
        value = v[key]
        return f"{value * scale:.{digits}f}" if value is not None else "—"

    evidence = [
        {"label": "趋势", "text": f"MA5/10/20/60：{fmt('ma5',3)} / {fmt('ma10',3)} / {fmt('ma20',3)} / {fmt('ma60',3)}；MA5三日斜率 {fmt('ma5_slope_3',2,100)}%"},
        {"label": "位置与动量", "text": f"BIAS5/12/24：{fmt('bias5_ratio',2,100)}% / {fmt('bias12')}% / {fmt('bias24')}%；RSI6/14：{fmt('rsi6',1)} / {fmt('rsi14',1)}；布林位置 {fmt('boll_position',0,100)}%"},
        {"label": "量能", "text": "日线样本未确认完整，盘中成交量不能与完整日量直接比较。" if incomplete_daily else f"样本日量/5日均量 {fmt('vol_ratio_1_5')}×；5日/20日均量 {fmt('vol_ratio_5_20')}×"},
    ]
    status, summary = "INSUFFICIENT", "技术数据不足，等待补齐后复评"
    buy_condition = "补齐有效均线、动量、量能及至少60日日线；不据残缺评分新增投入。"
    sell_condition = "仅保留部分卖出草案，价格条件待有效行情复评。"
    conflicts: list[str] = []
    overheat_evidence: list[str] = []
    if incomplete_daily:
        summary = "日线样本未确认完整，等待有效完整日线后复评"
        missing.append("完整日线时间证据")
    if sufficient:
        rsi, bias, boll = v["rsi6"], v["bias5_ratio"], v["boll_position"]
        oversold = rsi <= 30 and (bias <= -0.03 or boll <= 0.2)
        hot = rsi >= 75 or bias >= 0.06 or boll >= 0.95 or (v["bias12"] is not None and v["bias12"] >= 7) or (v["bias24"] is not None and v["bias24"] >= 8)
        weak = close < v["ma20"] and v["ma5_slope_3"] <= 0
        up = close > v["ma5"] > v["ma10"] > v["ma20"] and v["ma5_slope_3"] > 0
        volume_ok = v["vol_ratio_1_5"] >= 1 and v["vol_ratio_5_20"] >= 0.9
        pending = []
        if close < v["ma5"]:
            pending.append("站回MA5")
        if v["ma5_slope_3"] <= 0:
            pending.append("MA5斜率转正")
        if rsi < 35:
            pending.append("RSI6回升至≥35")
        if v["vol_ratio_1_5"] < 1:
            pending.append("完整样本日/5日量比≥1")
        if v["vol_ratio_5_20"] < 0.9:
            pending.append("5日/20日量比≥0.9")
        history = v["recent_oversold_count5"]
        recovery = (history_available and history > 0
                    and rsi > v["previous_rsi6"] and rsi >= 35
                    and close >= v["ma5"] and volume_ok)
        if oversold:
            status, summary = "OVERSOLD_UNCONFIRMED", "超卖未企稳，低位不等于买点"
            buy_condition = "等待" + "、".join(pending) + "后复评。"
        elif hot:
            status, summary = "OVERHEATED", "动量或乖离偏热，等待降温"
            cooling = []
            for flag, label, actual in ((rsi >= 75, "RSI6<75", f"RSI6 {rsi:.1f} ≥ 75"),
                                (bias >= .06, "BIAS5<6%", f"BIAS5 {bias * 100:.2f}% ≥ 6%"),
                                (boll >= .95, "布林位置<95%", f"布林位置 {boll * 100:.0f}% ≥ 95%"),
                                (v["bias12"] is not None and v["bias12"] >= 7, "BIAS12<7%", f"BIAS12 {fmt('bias12')}% ≥ 7%"),
                                (v["bias24"] is not None and v["bias24"] >= 8, "BIAS24<8%", f"BIAS24 {fmt('bias24')}% ≥ 8%")):
                if flag:
                    cooling.append(label)
                    overheat_evidence.append(actual)
            buy_condition = "等待" + "、".join(cooling) + "后复评。"
        elif recovery:
            status, summary = "OVERSOLD_RECOVERY", "近期超卖后初步修复，仍需等待回落确认"
            buy_condition = "等待回落反弹；跌回MA5下方或量能转弱时撤回修复判断。"
        elif weak:
            status, summary = "WEAK", "价格低于MA20、短均线下行，弱势未改"
            buy_condition = "等待" + "、".join(pending) + "后复评。"
        elif up and volume_ok and close >= v["ma60"]:
            status, summary = "TREND_UP", "均线偏强、量能配合，等待回落而非追涨"
            buy_condition = "只保留回落后反弹的条件计划；跌破MA20或量能转弱时复评。"
        else:
            status, summary = "MIXED", "信号存在分歧，保留回落观察计划"
            if not up and v["ma5_slope_3"] > 0:
                pending.append("价格与MA5/10/20恢复多头排列")
            if close < v["ma60"]:
                pending.append("站回MA60")
            buy_condition = "等待" + "、".join(pending) + "后复评。" if pending else "价格与量价信号尚未形成一致方向，等待回落后的新样本复评。"
        sell_condition = ("等待反弹，分批回收。"
                          if status in {"OVERSOLD_UNCONFIRMED", "WEAK", "MIXED"} else
                          "当前偏热，评估部分卖出并保留底仓；不额外等待现价再上涨。" if status == "OVERHEATED" else
                          "上涨后回落时分批卖出，保留底仓。")
        if close < v["ma60"]:
            conflicts.append("仍低于MA60，短期修复不能证明中期趋势反转。")
        if v["vol_ratio_1_5"] < 1 or v["vol_ratio_5_20"] < 0.9:
            conflicts.append("量能未配合，价格反弹仍需确认。")
        if v["rsi14"] is not None and v["rsi14"] < 40 and rsi >= 50:
            conflicts.append("RSI6回升而RSI14仍弱，短中期动量分歧。")

    if market.signal_is_complete is True:
        buy_condition = f"下一个完整交易日确认（现有样本 {market.signal_date}）：" + buy_condition

    return {
        "contract": TECHNICAL_CONTRACT, "status": status, "summary": summary,
        "buy_gate": "CONDITIONAL" if status in {"TREND_UP", "OVERSOLD_RECOVERY", "MIXED"} else "WAIT_CONFIRMATION",
        "buy_condition": buy_condition, "sell_condition": sell_condition,
        "evidence": evidence, "conflicts": conflicts, "missing_fields": missing,
        "overheat_evidence": overheat_evidence,
        "data_sufficient": sufficient, "signal_date": market.signal_date,
        "signal_close": sample_close, "recent_oversold_count5": v["recent_oversold_count5"],
        "previous_rsi6": v["previous_rsi6"],
        "history_available": history_available,
    }
