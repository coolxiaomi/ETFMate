from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape


def render_html(
    date: str,
    recommendations: list[dict],
    grid_advices: list[dict],
    trade_review: dict,
    data_completeness: dict | None = None,
) -> str:
    template = _template_env().get_template("daily_report.html")
    etfs = [_etf_view(item) for item in _group_by_etf(recommendations, grid_advices)]
    return template.render(
        date=date,
        recommendations_count=len(recommendations),
        grid_advices_count=len(grid_advices),
        etfs=etfs,
        trade_review=_trade_review_view(trade_review),
        data_completeness=_data_completeness_view(data_completeness),
    )


def render_markdown(
    date: str,
    recommendations: list[dict],
    grid_advices: list[dict],
    trade_review: dict,
    data_completeness: dict | None = None,
) -> str:
    return render_html(date, recommendations, grid_advices, trade_review, data_completeness)


def write_report(
    path: Path,
    date: str,
    recommendations: list[dict],
    grid_advices: list[dict],
    trade_review: dict,
    data_completeness: dict | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(date, recommendations, grid_advices, trade_review, data_completeness), encoding="utf-8")
    return path


def _template_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(Path(__file__).with_name("templates")),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _group_by_etf(recommendations: list[dict], grid_advices: list[dict]) -> list[dict]:
    result: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in recommendations:
        code = str(item.get("code") or "")
        if not code:
            continue
        result.setdefault(code, {"code": code, "recommendation": None, "grid": None})
        result[code]["recommendation"] = item
        result[code]["name"] = item.get("name") or result[code].get("name") or code
        if code not in order:
            order.append(code)
    for item in grid_advices:
        code = str(item.get("code") or "")
        if not code:
            continue
        result.setdefault(code, {"code": code, "recommendation": None, "grid": None})
        result[code]["grid"] = item
        result[code]["name"] = item.get("name") or result[code].get("name") or code
        if code not in order:
            order.append(code)
    return [result[code] for code in order]


def _etf_view(item: dict) -> dict[str, Any]:
    rec = item.get("recommendation")
    grid = item.get("grid")
    code = item["code"]
    name = item.get("name") or code
    action = str(rec.get("action") if rec else "无持仓建议")
    grid_action = str(grid.get("action") if grid else "无网格")
    return {
        "id": f"etf-{_anchor(code)}",
        "code": code,
        "name": str(name),
        "title_meta": _title_meta(rec, grid),
        "action_pill": _pill(action, _action_class(action)),
        "grid_pill": _pill(grid_action, _grid_action_class(grid_action)),
        "holding": _holding_view(rec),
        "grid": _grid_view(grid),
    }


def _holding_view(item: dict | None) -> dict[str, Any]:
    if not item:
        return {"empty": True, "message": "无当前持仓或行情建议。", "rows": []}
    rows = [
        _row("持仓", _holding_summary(item), _price_summary(item), _pnl_alert(item.get("pnl_pct"))),
        _row("BOLL", _boll_summary(item), _boll_levels(item), _boll_alert(item)),
        _row("MA", _ma_summary(item), _ma_compare(item), _ma_alert(item)),
        _row("量能(VOL)", _volume_summary(item), _volume_compare(item), _volume_alert(item)),
        _row("真实波幅(ATR)", _atr_summary(item), _atr_compare(item), _atr_alert(item)),
        _row("乖离率(BIAS)", _bias_summary(item), _bias_compare(item), _bias_alert(item)),
        _merged_row("动作", _action_merged_html(item)),
        _merged_row("总述", _overview_html(item)),
    ]
    return {"empty": False, "message": "", "rows": rows}


def _grid_view(item: dict | None) -> dict[str, Any]:
    if not item:
        return {"empty": True, "message": "无 Touker 网格配置。", "rows": []}
    rows = [
        _grid_row("买入触发", item.get("current_buy_fall_pct"), item.get("suggested_buy_fall_pct"), "%"),
        _grid_row("卖出触发", item.get("current_sell_rise_pct"), item.get("suggested_sell_rise_pct"), "%"),
        _grid_row("委托股数", item.get("current_quantity"), item.get("suggested_buy_quantity"), " 股"),
        _grid_row("卖出股数", item.get("current_quantity"), item.get("suggested_sell_quantity"), " 股"),
        _merged_row("动作", _grid_action_merged_html(item)),
    ]
    return {"empty": False, "message": "", "rows": rows}


def _trade_review_view(trade_review: dict) -> dict[str, Any]:
    reviews = trade_review.get("periods") or []
    if reviews:
        rows = [
            {
                "period": _period_label(item.get("period")),
                "score": f"{_cell(item.get('score'))}/10",
                "trade_count": _cell(item.get("trade_count")),
                "buy_amount": _num(item.get("buy_amount"), 2),
                "sell_amount": _num(item.get("sell_amount"), 2),
                "fee": _num(item.get("fee"), 2),
                "problems": "；".join(item.get("problems") or []),
                "plan": _cell(item.get("plan")),
            }
            for item in reviews
        ]
        return {"periods": rows, "summary": []}
    return {
        "periods": [],
        "summary": [
            _row("今日评分", _cell_html(f"{trade_review.get('score', '-')}/10"), _cell_html(""), _cell_html("；".join(trade_review.get("problems") or []))),
            _row("计划", _cell_html(trade_review.get("tomorrow_plan")), _cell_html(""), _cell_html(trade_review.get("improvement"))),
        ],
    }


def _data_completeness_view(data_completeness: dict | None) -> dict[str, Any]:
    if not data_completeness:
        return {"empty": True, "rows": []}
    rows = []
    for item in data_completeness.get("items", []):
        source = _market_source_text(item.get("source")) if str(item.get("label") or "") == "行情/K 线" else _cell(item.get("source"))
        rows.append(
            {
                "label": _cell(item.get("label")),
                "count": _cell(item.get("count")),
                "source": source,
                "note": _cell(item.get("note")),
            }
        )
    return {"empty": False, "rows": rows}


def _title_meta(item: dict | None, grid: dict | None) -> str:
    if not item:
        return " · 未出现在当前持仓分析中"
    parts = [
        f"现价 {_num(item.get('last_price'), 3)}",
        f"涨跌 {_signed_pct(item.get('pct_chg'))}" if item.get("pct_chg") is not None else "",
    ]
    if item.get("quantity") is not None:
        parts.extend(
            [
                f"持仓 {_num(item.get('quantity'), 0)}",
                f"浮盈亏 {_color_number(item.get('pnl_pct'), suffix='%')}",
            ]
        )
    parts.append("网格启用" if grid else "无网格")
    return " · " + "；".join(part for part in parts if part)


def _holding_summary(item: dict) -> str:
    return "；".join(
        [
            f"数量 {_num(item.get('quantity'), 0)}",
            f"市值 {_num(item.get('market_value'), 2)}",
            f"仓位 {_pct(item.get('position_pct'))}",
        ]
    )


def _price_summary(item: dict) -> str:
    return "；".join(
        [
            f"成本 {_num(item.get('cost_price'), 3)}",
            f"现价 {_num(item.get('last_price'), 3)}",
            f"浮盈亏 {_color_number(item.get('pnl_pct'), suffix='%')}",
        ]
    )


def _pnl_alert(value: Any) -> str:
    number = _float_or_none(value)
    if number is None:
        return _cell_html("-")
    if number >= 10:
        return _span("盈利较多，注意分批兑现", "profit strong")
    if number > 0:
        return _span("盈利", "profit")
    if number <= -10:
        return _span("亏损较深，避免盲目补仓", "loss strong")
    if number < 0:
        return _span("亏损", "loss")
    return _cell_html("持平")


def _boll_summary(item: dict) -> str:
    return f"分位 {_pct(item.get('boll_position_pct'))}；现价 {_num(item.get('last_price'), 3)}"


def _boll_levels(item: dict) -> str:
    return "；".join(
        [
            f"上: {_num(item.get('boll_upper'), 3)}",
            f"中: {_num(item.get('boll_mid'), 3)}",
            f"下: {_num(item.get('boll_lower'), 3)}",
        ]
    )


def _boll_alert(item: dict) -> str:
    price = _float_or_none(item.get("last_price"))
    lower = _float_or_none(item.get("boll_lower"))
    upper = _float_or_none(item.get("boll_upper"))
    pos = _float_or_none(item.get("boll_position_pct"))
    if price is not None and upper is not None and price >= upper:
        return _span("突破上轨，短线过热", "danger")
    if price is not None and lower is not None and price <= lower:
        return _span("跌破下轨，先看止跌", "loss strong")
    if pos is not None and pos >= 90:
        return _span("接近上轨，适合偏卖出", "warn")
    if pos is not None and pos <= 15:
        return _span("接近下轨，只适合分批", "attention")
    return _span("轨道内运行", "neutral")


def _ma_summary(item: dict) -> str:
    return "；".join(
        [
            f"5: {_num(item.get('ma5'), 3)}",
            f"10: {_num(item.get('ma10'), 3)}",
            f"20: {_num(item.get('ma20'), 3)}",
            f"60: {_num(item.get('ma60'), 3)}",
            f"200: {_num(item.get('ma200'), 3)}",
        ]
    )


def _ma_compare(item: dict) -> str:
    return _cell_html(item.get("ma_status"))


def _ma_alert(item: dict) -> str:
    price = _float_or_none(item.get("last_price"))
    ma20 = _float_or_none(item.get("ma20"))
    ma60 = _float_or_none(item.get("ma60"))
    ma200 = _float_or_none(item.get("ma200"))
    if price is None:
        return _cell_html("-")
    if ma200 and price < ma200:
        return _span("跌破年线，趋势风险高", "danger")
    if ma20 and ma60 and price < ma20 and price < ma60:
        return _span("跌破20/60日线，偏弱", "loss strong")
    if ma20 and price < ma20:
        return _span("跌破20日线，短线转弱", "warn")
    if ma20 and ma60 and price > ma20 and price > ma60:
        return _span("站上20/60日线，趋势偏强", "profit")
    return _span("均线信号中性", "neutral")


def _atr_summary(item: dict) -> str:
    return "；".join(
        [
            f"7: {_pct(item.get('atr7_pct'))}",
            f"14: {_pct(item.get('atr14_pct'))}",
            f"30: {_pct(item.get('atr30_pct'))}",
            f"60: {_pct(item.get('atr60_pct'))}",
        ]
    )


def _atr_compare(item: dict) -> str:
    atr14 = _float_or_none(item.get("atr14_pct"))
    atr30 = _float_or_none(item.get("atr30_pct"))
    if atr14 is None or atr30 is None:
        return _cell_html("波动数据不足")
    ratio = atr14 / atr30 if atr30 else 0
    return _cell_html(f"14/30 {ratio:.2f} 倍")


def _atr_alert(item: dict) -> str:
    atr14 = _float_or_none(item.get("atr14_pct"))
    atr30 = _float_or_none(item.get("atr30_pct"))
    if atr14 is None:
        return _cell_html("-")
    if atr14 >= 5:
        return _span("波动偏大，网格别太密", "danger")
    if atr30 and atr14 > atr30 * 1.25:
        return _span("短期波动放大，调宽间距", "warn")
    if atr14 <= 2:
        return _span("波动偏低，触发会减少", "attention")
    return _span("波动正常", "neutral")


def _bias_summary(item: dict) -> str:
    return "；".join(
        [
            f"6: {_signed_metric_pct(item.get('bias6'))}",
            f"12: {_signed_metric_pct(item.get('bias12'))}",
            f"24: {_signed_metric_pct(item.get('bias24'))}",
        ]
    )


def _bias_compare(item: dict) -> str:
    return _cell_html("+涨得快,-跌得深")


def _bias_alert(item: dict) -> str:
    bias6 = _float_or_none(item.get("bias6"))
    bias12 = _float_or_none(item.get("bias12"))
    if bias6 is None:
        return _cell_html("-")
    if bias6 >= 6:
        return _span("短线明显过热，优先减仓", "danger")
    if bias6 <= -6:
        return _span("短线超跌，等止跌再分批", "attention")
    if bias12 is not None and bias6 > 3 and bias12 > 3:
        return _span("多周期正乖离，别追高", "warn")
    if bias12 is not None and bias6 < -3 and bias12 < -3:
        return _span("多周期负乖离，控制仓位试探", "attention")
    return _span("乖离温和", "neutral")


def _action_merged_html(item: dict) -> str:
    parts = [
        _action_text(item),
        _inline_label("备注", item.get("investor_note")),
        _inline_label("仓位", item.get("position_plan")),
        _inline_label("理由", "；".join(item.get("reasons") or [])),
    ]
    return _join_html(parts)


def _action_text(item: dict) -> str:
    action = str(item.get("action") or "-")
    qty = item.get("action_quantity")
    qty_text = "" if qty in (None, "") else f"；参考 {_num(qty, 0)} 份"
    return _span(action + qty_text, _action_class(action))


def _overview_html(item: dict) -> str:
    risks = _filtered_risks(item)
    risk_text = "；".join(risks) if risks else "暂无明显新增风险"
    cls = "danger" if any(word in risk_text for word in ("跌破", "浮亏", "风险", "低于")) else "neutral"
    return _join_html(
        [
            _inline_label("观察", item.get("watch_price")),
            f'<span class="{cls}">{escape(risk_text)}</span>',
        ]
    )


def _filtered_risks(item: dict) -> list[str]:
    return [
        str(risk)
        for risk in (item.get("risks") or [])
        if not str(risk).startswith("行情数据完整性:")
    ]


def _grid_row(label: str, current: Any, suggested: Any, suffix: str) -> dict[str, Any]:
    changed = _changed(current, suggested)
    return _row(
        label,
        _cell_html(_format_with_suffix(current, suffix)),
        _span(_format_with_suffix(suggested, suffix), "warn" if changed else "neutral"),
        _span("需调整", "warn") if changed else _span("维持", "neutral"),
    )


def _volume_summary(item: dict) -> str:
    return "；".join(
        [
            f"成交量 {_num(item.get('volume'), 0)}",
            f"量比 {_num(item.get('vol_ratio'), 2)}",
            f"换手 {_pct(item.get('turnover_pct'))}",
        ]
    )


def _volume_compare(item: dict) -> str:
    vol5 = _float_or_none(item.get("vol_ma5"))
    vol20 = _float_or_none(item.get("vol_ma20"))
    if vol5 is None or vol20 is None:
        return _cell_html("量能均线不足")
    return _cell_html(f"5/20: {vol5 / vol20:.2f} 倍")


def _volume_alert(item: dict) -> str:
    vol5 = _float_or_none(item.get("vol_ma5"))
    vol20 = _float_or_none(item.get("vol_ma20"))
    vol_ratio = _float_or_none(item.get("vol_ratio"))
    if vol_ratio is not None and vol_ratio >= 2:
        return _span("量比明显放大，注意冲高回落", "warn")
    if vol5 is not None and vol20 is not None and vol5 > vol20 * 1.2:
        return _span("近期成交活跃", "profit")
    if vol5 is not None and vol20 is not None and vol5 < vol20 * 0.75:
        return _span("量能不足，反弹需确认", "attention")
    return _span("量能正常", "neutral")


def _grid_action_merged_html(item: dict) -> str:
    return _join_html(
        [
            _span(item.get("action"), _grid_action_class(str(item.get("action") or ""))),
            _inline_label("依据", "；".join(item.get("reasons") or [])),
        ]
    )


def _changed(left: Any, right: Any) -> bool:
    lnum = _float_or_none(left)
    rnum = _float_or_none(right)
    if lnum is None or rnum is None:
        return False
    return abs(lnum - rnum) >= max(0.01, abs(lnum) * 0.1)


def _format_with_suffix(value: Any, suffix: str) -> str:
    digits = 2 if suffix.strip() == "%" else 0
    number = _num(value, digits)
    return "-" if number == "-" else f"{number}{suffix}"


def _row(label: str, current: str, reference: str, alert: str) -> dict[str, Any]:
    return {"label": label, "current": current, "reference": reference, "alert": alert, "merged": False}


def _merged_row(label: str, content: str) -> dict[str, Any]:
    return {"label": label, "content": content, "merged": True}


def _pill(text: str, cls: str) -> str:
    return f'<span class="pill {escape(cls)}">{escape(text)}</span>'


def _span(value: Any, cls: str) -> str:
    return f'<span class="{escape(cls)}">{escape(_cell(value))}</span>'


def _inline_label(label: str, value: Any) -> str:
    text = _cell(value)
    if text == "-":
        return ""
    return f'<span class="inline-label">{escape(label)}：</span>{escape(text)}'


def _join_html(parts: list[str]) -> str:
    return "；".join(part for part in parts if part)


def _cell_html(value: Any) -> str:
    return escape(_cell(value))


def _color_number(value: Any, suffix: str = "") -> str:
    number = _float_or_none(value)
    if number is None:
        return "-"
    cls = "profit" if number > 0 else "loss" if number < 0 else "neutral"
    return _span(f"{number:.2f}{suffix}", cls)


def _signed_pct(value: Any) -> str:
    number = _float_or_none(value)
    if number is None:
        return "-"
    return f"{number:+.2f}%"


def _signed_metric_pct(value: Any) -> str:
    number = _float_or_none(value)
    if number is None:
        return "-"
    return f"{number:+.2f}%"


def _action_class(action: str) -> str:
    if any(word in action for word in ("买入", "加仓")):
        return "action-buy"
    if any(word in action for word in ("减仓", "卖出")):
        return "action-sell"
    if "暂停" in action:
        return "action-pause"
    return "neutral"


def _grid_action_class(action: str) -> str:
    if any(word in action for word in ("调宽", "调窄", "调整")):
        return "warn"
    if "暂停" in action:
        return "action-pause"
    return "neutral"


def _period_label(value: Any) -> str:
    text = _cell(value)
    mapping = {
        "当日复盘": "本次日内复盘",
        "三日复盘": "近3日复盘",
        "3日复盘": "近3日复盘",
        "7日复盘": "近7日复盘",
        "30日复盘": "近30日复盘",
    }
    return mapping.get(text, text)


def _market_source_text(value: Any) -> str:
    text = _cell(value)
    if text in {"-", "N/A"}:
        return text
    labels: list[str] = []
    if "quote:tencent" in text:
        labels.append("实时行情：腾讯")
    if "kline:tencent" in text:
        labels.append("K线：腾讯")
    if "kline:mootdx" in text:
        labels.append("K线：通达信")
    if "quote:mootdx" in text:
        labels.append("实时行情：通达信")
    if "kline:baidu" in text:
        labels.append("K线：百度")
    return "；".join(dict.fromkeys(labels)) if labels else text


def _anchor(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-") or "etf"


def _num(value: Any, digits: int) -> str:
    number = _float_or_none(value)
    if number is None:
        return "-"
    return f"{number:.{digits}f}" if digits > 0 else f"{number:.0f}"


def _pct(value: Any) -> str:
    number = _num(value, 2)
    return "-" if number == "-" else f"{number}%"


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cell(value: Any) -> str:
    text = "-" if value is None or value == "" else str(value)
    text = text.replace("\n", " ").strip()
    return text if text else "-"
