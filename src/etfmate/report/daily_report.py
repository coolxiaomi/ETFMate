from __future__ import annotations

import re
from html import escape
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

RULE_VERSION = "2026.06.23-v1"
SCORE_RULE_VERSION = "score-2026.06"
GRID_RULE_VERSION = "grid-2026.06"
RISK_RULE_VERSION = "risk-2026.06"


def render_html(
    date: str,
    recommendations: list[dict],
    grid_advices: list[dict],
    trade_review: dict,
    data_completeness: dict | None = None,
) -> str:
    template = _template_env().get_template("daily_report.html")
    etfs = _sort_etfs_for_display([_etf_view(item) for item in _group_by_etf(recommendations, grid_advices)])
    return template.render(
        date=date,
        recommendations_count=len(recommendations),
        grid_advices_count=len(grid_advices),
        portfolio_stats=_portfolio_stats(recommendations, grid_advices, data_completeness),
        nav_dashboard=_nav_dashboard(etfs),
        rule_versions=_rule_versions(date),
        etfs=etfs,
        trade_review=_trade_review_view(trade_review),
        data_completeness=_data_completeness_view(data_completeness),
    )


def _rule_versions(generated_at: str) -> dict[str, str]:
    return {
        "rule_version": RULE_VERSION,
        "score_rule_version": SCORE_RULE_VERSION,
        "grid_rule_version": GRID_RULE_VERSION,
        "risk_rule_version": RISK_RULE_VERSION,
        "generated_at": generated_at,
    }


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
        result[code]["name"] = _preferred_name(result[code].get("name"), item.get("name"), code)
        if code not in order:
            order.append(code)
    for item in grid_advices:
        code = str(item.get("code") or "")
        if not code or code not in result:
            continue
        result[code]["grid"] = item
        result[code]["name"] = _preferred_name(result[code].get("name"), item.get("name"), code)
    return [result[code] for code in order]


def _etf_view(item: dict) -> dict[str, Any]:
    rec = item.get("recommendation")
    grid = item.get("grid")
    code = item["code"]
    name = item.get("name") or code
    action = str(rec.get("action") if rec else "无持仓建议")
    grid_action = str(grid.get("action") if grid else "无网格")
    nav = _nav_signal(action, grid_action, rec)
    pnl_class = _pnl_class(rec)
    grid_short = _compact_grid_action(grid_action)
    is_held = bool(rec and (_float_or_none(rec.get("quantity")) or 0) > 0)
    is_grid = bool(grid and grid.get("grid_applicable") is not False)
    is_pool = _is_clean_watchlist_item(rec)
    trend_score = _float_or_none(rec.get("rule_trend_score")) if rec else None
    holding_pct = _float_or_none(rec.get("holding_pct")) if rec else None
    if holding_pct is None and rec:
        holding_pct = _float_or_none(rec.get("position_pct"))
    pnl_pct = _float_or_none(rec.get("pnl_pct")) if rec else None
    return {
        "id": f"etf-{_anchor(code)}",
        "code": code,
        "name": str(name),
        "is_held": is_held,
        "is_grid": is_grid,
        "is_pool": is_pool,
        "filter_tags": _filter_tags(is_held, is_grid, is_pool),
        "pnl_class": pnl_class,
        "pnl_text": _pnl_text(rec),
        "holding_pct_value": holding_pct,
        "pnl_pct_value": pnl_pct,
        "position_pct_value": _float_or_none(rec.get("position_pct")) if rec else None,
        "position_pct_text": _pct(rec.get("position_pct")) if rec and rec.get("position_pct") is not None else "-",
        "trend_score": trend_score,
        "trend_score_text": "-" if trend_score is None else f"{trend_score:.0f}",
        "trend_width": f"{max(4, min(100, trend_score or 0)):.1f}",
        "nav_action": nav["action"],
        "nav_action_class": nav["action_class"],
        "nav_heat": nav["heat"],
        "nav_heat_class": nav["heat_class"],
        "nav_heat_tip": nav["heat_tip"],
        "nav_meta": nav["meta"],
        "grid_action_short": grid_short,
        "grid_action_class": _grid_action_class(grid_action),
        "title_meta": _title_meta(rec, grid),
        "action_pill": _pill(_compact_action(_display_action(action)), _action_class(action)),
        "grid_pill": _pill(f"网格:{_display_action(grid_action)}", _grid_action_class(grid_action)),
        "holding": _holding_view(rec, grid),
    }


def _holding_view(item: dict | None, grid: dict | None = None) -> dict[str, Any]:
    if not item:
        return {"empty": True, "message": "无当前持仓或行情建议。", "rows": []}
    rows = [
        _row("BOLL", _boll_summary(item), _boll_levels(item), _boll_alert(item)),
        _row("MA", _ma_summary(item), _ma_compare(item), _ma_alert(item)),
        _row("VOL(成交量)", _volume_summary(item), _volume_compare(item), _volume_alert(item)),
        _row("ATR(真实波幅)", _atr_summary(item), _atr_compare(item), _atr_alert(item)),
        _row("BIAS(乖离率)", _bias_summary(item), _bias_compare(item), _bias_alert(item)),
        _row("RSI(相对强弱)", _rsi_summary(item), _rsi_compare(item), _rsi_alert(item)),
        _row("MACD(指数平滑异同)", _macd_summary(item), _macd_compare(item), _macd_alert(item)),
        _row("规则", _rule_score_summary(item), _rule_score_detail(item), _rule_score_alert(item)),
        _merged_row("网格", _grid_table_html(grid)),
        _merged_row("综合结论", _combined_conclusion_html(item)),
        _merged_row("明细", _detail_drawer_html(item)),
    ]
    return {"empty": False, "message": "", "rows": rows}


def _grid_view(item: dict | None) -> dict[str, Any]:
    if not item:
        return {"empty": True, "message": "无 Touker 网格配置。", "rows": []}
    if item.get("grid_applicable") is False:
        reasons = "；".join(item.get("reasons") or [])
        return {"empty": True, "message": reasons or "当前不适合建仓，本次暂不设网格。", "rows": []}
    rows = [
        _grid_row("基准", item.get("current_base_price"), item.get("suggested_base_price"), ""),
        _grid_sell_row(item),
        _grid_buy_row(item),
        _grid_position_limit_row(item),
        _merged_row("动作", _grid_action_merged_html(item)),
    ]
    return {"empty": False, "message": "", "rows": rows}


def _grid_table_html(item: dict | None) -> str:
    grid = _grid_view(item)
    if grid["empty"]:
        return f'<span class="empty">{escape(grid["message"])}</span>'
    body = []
    for row in grid["rows"]:
        label = escape(str(row["label"]))
        if row.get("merged"):
            body.append(f'<tr><th>{label}</th><td class="merged-cell" colspan="3">{row["content"]}</td></tr>')
        else:
            body.append(
                "<tr>"
                f"<th>{label}</th>"
                f"<td>{row['current']}</td>"
                f"<td>{row['reference']}</td>"
                f"<td>{row['alert']}</td>"
                "</tr>"
            )
    return (
        '<div class="table-scroll embedded-scroll">'
        '<table class="dense embedded-grid">'
        '<colgroup><col class="grid-item-col"><col class="grid-num-col"><col class="grid-num-col"><col></colgroup>'
        "<thead><tr><th>项</th><th>当前</th><th>建议</th><th>提醒</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table>"
        "</div>"
    )


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
                "avg_trade_amount": _num(item.get("avg_trade_amount"), 2),
                "fee_to_turnover_ratio": _pct((_float_or_none(item.get("fee_to_turnover_ratio")) or 0) * 100),
                "estimated_grid_profit": "-" if item.get("estimated_grid_profit") is None else _num(item.get("estimated_grid_profit"), 2),
                "ineffective_trade_count": _cell(item.get("ineffective_trade_count")),
                "buy_after_down_count": _cell(item.get("buy_after_down_count")),
                "sell_after_up_count": _cell(item.get("sell_after_up_count")),
                "overtrading_flag": "是" if item.get("overtrading_flag") else "否",
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


def _portfolio_stats(recommendations: list[dict], grid_advices: list[dict], data_completeness: dict | None = None) -> dict[str, int]:
    stats = data_completeness.get("stats", {}) if isinstance(data_completeness, dict) else {}
    pool_count = _int_or_none(stats.get("watchlist_count"))
    if pool_count is None:
        pool_count = _data_count(data_completeness, "同花顺自选ETF池")
    if pool_count is None:
        pool_count = 0
    held_count = _int_or_none(stats.get("positions_count"))
    if held_count is None:
        held_count = _data_count(data_completeness, "同花顺持仓")
    grid_count = sum(1 for item in grid_advices if item.get("grid_applicable") is not False)
    if held_count is None:
        held_count = sum(1 for item in recommendations if (_float_or_none(item.get("quantity")) or 0) > 0)
    all_count = len({str(item.get("code") or "") for item in recommendations if item.get("code")})
    return {
        "held_count": held_count,
        "grid_count": grid_count,
        "pool_count": pool_count,
        "all_count": all_count,
    }


def _filter_tags(is_held: bool, is_grid: bool, is_pool: bool) -> str:
    tags = ["all"]
    if is_held:
        tags.append("held")
    if is_grid:
        tags.append("grid")
    if is_pool:
        tags.append("pool")
    return " ".join(tags)


def _data_count(data_completeness: dict | None, label: str) -> int | None:
    if not data_completeness:
        return None
    for item in data_completeness.get("items", []):
        if str(item.get("label") or "") != label:
            continue
        text = str(item.get("count") or "")
        digits = ""
        for ch in text:
            if ch.isdigit():
                digits += ch
            elif digits:
                break
        return int(digits) if digits else None
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nav_groups(etfs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = ["热", "温", "平", "凉", "寒"]
    meanings = {
        "热": "趋势评分≥85",
        "温": "趋势评分75-84",
        "平": "趋势评分60-74",
        "凉": "趋势评分45-59",
        "寒": "趋势评分<45",
    }
    grouped = {key: [] for key in order}
    for etf in etfs:
        grouped.setdefault(str(etf.get("nav_heat") or "平"), []).append(etf)
    result = []
    for key in order:
        items = _sort_etfs_for_display(grouped.get(key) or [])
        if not items:
            continue
        action_counts: dict[str, int] = {}
        for etf in items:
            action = str(etf.get("nav_action") or "待定")
            action_counts[action] = action_counts.get(action, 0) + 1
        summary = " / ".join(f"{name}{count}" for name, count in sorted(action_counts.items(), key=lambda pair: (-pair[1], pair[0])))
        result.append({"heat": key, "heat_class": items[0].get("nav_heat_class", "heat-flat"), "meaning": meanings[key], "summary": summary, "etfs": items})
    return result


def _nav_dashboard(etfs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "decision_groups": _nav_groups(etfs),
        "action_groups": _action_groups(etfs),
        "trend_items": _trend_items(etfs),
        "holding": _holding_pie(etfs),
        "pnl": _pnl_dashboard(etfs),
        "grid_groups": _grid_groups(etfs),
        "risk_items": _risk_items(etfs),
    }


def _action_groups(etfs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = ["加仓", "建仓", "持有", "观察/等待", "减仓", "暂停买入", "卖出", "待定"]
    groups: dict[str, list[dict[str, Any]]] = {}
    for etf in etfs:
        groups.setdefault(str(etf.get("nav_action") or "待定"), []).append(etf)
    result = []
    for key in order + sorted(key for key in groups if key not in order):
        items = _sort_etfs_for_display(groups.get(key) or [])
        if items:
            result.append({"action": key, "count": len(items), "class": items[0].get("nav_action_class", "neutral"), "etfs": items})
    return result


def _holding_pie(etfs: list[dict[str, Any]]) -> dict[str, Any]:
    held = [item for item in etfs if (item.get("position_pct_value") or 0) > 0]
    metric_held = sorted(held, key=lambda item: item.get("position_pct_value") or 0, reverse=True)
    held = _sort_etfs_for_display(held)
    total = sum(item.get("position_pct_value") or 0 for item in held)
    top3 = sum(item.get("position_pct_value") or 0 for item in metric_held[:3])
    max_item = metric_held[0] if metric_held else None
    metrics = [
        {"label": "持", "value": f"{len(held)}只"},
        {"label": "资金仓", "value": f"{total:.2f}%"},
        {"label": "Top3", "value": f"{top3:.2f}%"},
        {"label": "最大", "value": f"{max_item['code']} {_pct(max_item.get('position_pct_value'))}" if max_item else "-"},
    ]
    colors = ["#d8001b", "#107d32", "#006bff", "#aa4d00", "#4d4d4d", "#00ac96", "#f22782", "#0059ec", "#279141", "#8500d1"]
    segments = []
    cursor = 0.0
    for idx, item in enumerate(held):
        pct = item.get("position_pct_value") or 0
        share = 0 if total <= 0 else pct / total * 100
        start = cursor
        end = cursor + share
        cursor = end
        color = colors[idx % len(colors)]
        segments.append({**item, "color": color, "share": f"{share:.1f}", "start": f"{start:.2f}", "end": f"{end:.2f}"})
    gradient = "conic-gradient(#eef3f4 0 100%)"
    if segments:
        gradient = "conic-gradient(" + ", ".join(f"{seg['color']} {seg['start']}% {seg['end']}%" for seg in segments) + ")"
    return {"empty": not held, "total_pct": f"{total:.2f}%", "gradient": gradient, "segments": segments[:10], "held": held, "metrics": metrics}


def _pnl_dashboard(etfs: list[dict[str, Any]]) -> dict[str, Any]:
    items = _sort_etfs_for_display([item for item in etfs if item.get("pnl_class") in {"profit", "loss"}])
    max_abs = max((abs(_float_or_none_from_text(item.get("pnl_text")) or 0) for item in items), default=0)
    rows = []
    for item in items:
        value = _float_or_none_from_text(item.get("pnl_text")) or 0
        rows.append({**item, "pnl_value": f"{value:+.2f}%", "width": f"{0 if max_abs <= 0 else max(4, min(100, abs(value) / max_abs * 100)):.1f}"})
    return {
        "profit_count": sum(1 for item in rows if item["pnl_class"] == "profit"),
        "loss_count": sum(1 for item in rows if item["pnl_class"] == "loss"),
        "rows": rows,
    }


def _grid_groups(etfs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for etf in etfs:
        groups.setdefault(str(etf.get("grid_action_short") or "无网格"), []).append(etf)
    return [
        {"action": key, "count": len(items), "class": items[0].get("grid_action_class", "neutral"), "etfs": items}
        for key, items in (
            (key, _sort_etfs_for_display(items))
            for key, items in sorted(groups.items(), key=lambda pair: (-len(pair[1]), pair[0]))
        )
    ]


def _risk_items(etfs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return []


def _trend_items(etfs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _sort_etfs_for_display([item for item in etfs if item.get("trend_score") is not None])


def _sort_etfs_for_display(etfs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(etfs, key=_etf_display_sort_key)


def _etf_display_sort_key(item: dict[str, Any]) -> tuple[float, float, float, str]:
    return (
        -_sort_number(item.get("trend_score")),
        -_sort_number(item.get("holding_pct_value")),
        -_sort_number(item.get("pnl_pct_value")),
        str(item.get("code") or ""),
    )


def _sort_number(value: Any) -> float:
    number = _float_or_none(value)
    return number if number is not None else float("-inf")


def _title_meta(item: dict | None, grid: dict | None) -> str:
    if not item:
        return " · 未出现在当前持仓分析中"
    parts = [
        str(item.get("candidate_source") or ""),
        f"现价 {_num(item.get('last_price'), 3)}",
        f"涨跌 {_signed_pct(item.get('pct_chg'))}" if item.get("pct_chg") is not None else "",
    ]
    if item.get("quantity") is not None:
        parts.extend(
            [
                f"持 {_num(item.get('quantity'), 0)}",
                f"资金仓 {_pct(item.get('position_pct'))}",
                f"持仓内 {_pct(item.get('holding_pct'))}" if item.get("holding_pct") is not None else "",
                f"成本 {_num(item.get('cost_price'), 3)}",
                f"市值 {_num(item.get('market_value'), 2)}",
                f"盈亏 {_color_number(item.get('pnl_pct'), suffix='%')}",
            ]
        )
    else:
        parts.extend(["未持仓", f"目标仓位 {_pct(item.get('target_position_pct'))}"])
    parts.append("网格开" if grid and grid.get("grid_applicable") is not False else "无网格")
    return " · " + "；".join(_simplify_direction_text(part) for part in parts if part)


def _holding_summary(item: dict) -> str:
    if item.get("quantity") is None:
        return "；".join(
            [
                "未持仓",
                _cell(item.get("candidate_source")),
                f"目标仓位 {_pct(item.get('target_position_pct'))}",
            ]
        )
    return "；".join(
        [
            f"量 {_num(item.get('quantity'), 0)}",
            f"值 {_num(item.get('market_value'), 2)}",
            f"资金仓 {_pct(item.get('position_pct'))}",
            f"持仓内 {_pct(item.get('holding_pct'))}" if item.get("holding_pct") is not None else "",
        ]
    )


def _price_summary(item: dict) -> str:
    if item.get("quantity") is None:
        return "；".join(
            [
                f"现价 {_num(item.get('last_price'), 3)}",
                f"涨跌 {_signed_pct(item.get('pct_chg'))}" if item.get("pct_chg") is not None else "涨跌 -",
                _cell(item.get("watchlist_include_reason")),
            ]
        )
    return "；".join(
        [
            f"本 {_num(item.get('cost_price'), 3)}",
            f"现 {_num(item.get('last_price'), 3)}",
            f"盈亏 {_color_number(item.get('pnl_pct'), suffix='%')}",
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


def _colored_num(value: Any, digits: int, cls: str) -> str:
    number = _float_or_none(value)
    if number is None:
        return "-"
    return _span(f"{number:.{digits}f}" if digits > 0 else f"{number:.0f}", cls)


def _colored_signed_num(value: Any, digits: int, cls: str, suffix: str = "") -> str:
    number = _float_or_none(value)
    if number is None:
        return "-"
    return _span(f"{number:+.{digits}f}{suffix}", cls)


def _colored_pct(value: Any, cls: str) -> str:
    number = _float_or_none(value)
    if number is None:
        return "-"
    return _span(f"{number:.2f}%", cls)


def _boll_position_class(item: dict) -> str:
    price = _float_or_none(item.get("last_price"))
    lower = _float_or_none(item.get("boll_lower"))
    upper = _float_or_none(item.get("boll_upper"))
    pos = _float_or_none(item.get("boll_position_pct"))
    if price is not None and upper is not None and price >= upper:
        return "danger"
    if price is not None and lower is not None and price <= lower:
        return "loss strong"
    if pos is None:
        return "neutral"
    if pos >= 85:
        return "warn"
    if pos <= 20:
        return "attention"
    return "neutral"


def _colored_price_against_band(value: Any, item: dict) -> str:
    price = _float_or_none(value)
    if price is None:
        return "-"
    lower = _float_or_none(item.get("boll_lower"))
    upper = _float_or_none(item.get("boll_upper"))
    pos = _float_or_none(item.get("boll_position_pct"))
    cls = "neutral"
    if upper is not None and price >= upper:
        cls = "danger"
    elif lower is not None and price <= lower:
        cls = "loss strong"
    elif pos is not None and pos >= 85:
        cls = "warn"
    elif pos is not None and pos <= 20:
        cls = "attention"
    return _colored_num(price, 3, cls)


def _boll_summary(item: dict) -> str:
    return "；".join(
        [
            f"分位 {_colored_pct(item.get('boll_position_pct'), _boll_position_class(item))}",
            f"现价 {_colored_price_against_band(item.get('last_price'), item)}",
        ]
    )


def _boll_levels(item: dict) -> str:
    return "；".join(
        [
            f"上: {_colored_num(item.get('boll_upper'), 3, 'warn')}",
            f"中: {_colored_num(item.get('boll_mid'), 3, 'neutral')}",
            f"下: {_colored_num(item.get('boll_lower'), 3, 'attention')}",
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


def _colored_ma_value(value: Any, price: float | None) -> str:
    ma = _float_or_none(value)
    if ma is None:
        return "-"
    if price is None:
        return _colored_num(ma, 3, "neutral")
    return _colored_num(ma, 3, "profit" if price >= ma else "loss")


def _ma_status_html(value: Any) -> str:
    text = _cell(value)
    if text == "-":
        return "-"
    parts = []
    for part in text.split("/"):
        cls = "profit" if part.startswith("上") else "loss" if part.startswith("下") else "neutral"
        parts.append(_span(part, cls))
    return "/".join(parts)


def _ma_summary(item: dict) -> str:
    price = _float_or_none(item.get("last_price"))
    return "；".join(
        [
            f"5: {_colored_ma_value(item.get('ma5'), price)}",
            f"10: {_colored_ma_value(item.get('ma10'), price)}",
            f"20: {_colored_ma_value(item.get('ma20'), price)}",
            f"60: {_colored_ma_value(item.get('ma60'), price)}",
            f"200: {_colored_ma_value(item.get('ma200'), price)}",
        ]
    )


def _ma_compare(item: dict) -> str:
    return _ma_status_html(item.get("ma_status"))


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


def _atr_class(value: Any) -> str:
    number = _float_or_none(value)
    if number is None:
        return "neutral"
    if number >= 5:
        return "danger"
    if number >= 4:
        return "warn"
    if number <= 2:
        return "attention"
    return "neutral"


def _atr_ratio_class(value: float) -> str:
    if value >= 1.25:
        return "warn"
    if value <= 0.8:
        return "attention"
    return "neutral"


def _atr_summary(item: dict) -> str:
    return "；".join(
        [
            f"7: {_colored_pct(item.get('atr7_pct'), _atr_class(item.get('atr7_pct')))}",
            f"14: {_colored_pct(item.get('atr14_pct'), _atr_class(item.get('atr14_pct')))}",
            f"30: {_colored_pct(item.get('atr30_pct'), _atr_class(item.get('atr30_pct')))}",
            f"60: {_colored_pct(item.get('atr60_pct'), _atr_class(item.get('atr60_pct')))}",
        ]
    )


def _atr_compare(item: dict) -> str:
    atr14 = _float_or_none(item.get("atr14_pct"))
    atr30 = _float_or_none(item.get("atr30_pct"))
    if atr14 is None or atr30 is None:
        return _cell_html("波动数据不足")
    ratio = atr14 / atr30 if atr30 else 0
    return f"14/30 {_colored_num(ratio, 2, _atr_ratio_class(ratio))} 倍"


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
            f"6: {_colored_bias_pct(item.get('bias6'))}",
            f"12: {_colored_bias_pct(item.get('bias12'))}",
            f"24: {_colored_bias_pct(item.get('bias24'))}",
        ]
    )


def _colored_bias_pct(value: Any) -> str:
    number = _float_or_none(value)
    if number is None:
        return "-"
    if number >= 6:
        cls = "danger"
    elif number >= 3:
        cls = "warn"
    elif number > 0:
        cls = "profit"
    elif number <= -6:
        cls = "loss strong"
    elif number <= -3:
        cls = "attention"
    elif number < 0:
        cls = "loss"
    else:
        cls = "neutral"
    return _colored_signed_num(number, 2, cls, "%")


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


def _rsi_class(value: Any) -> str:
    number = _float_or_none(value)
    if number is None:
        return "neutral"
    if number >= 85:
        return "danger"
    if number >= 70:
        return "warn"
    if number <= 20:
        return "loss strong"
    if number <= 40:
        return "attention"
    return "neutral"


def _rsi_summary(item: dict) -> str:
    return "；".join(
        [
            f"6: {_colored_num(item.get('rsi6'), 1, _rsi_class(item.get('rsi6')))}",
            f"14: {_colored_num(item.get('rsi14'), 1, _rsi_class(item.get('rsi14')))}",
        ]
    )


def _rsi_compare(item: dict) -> str:
    return (
        "RSI6用于短线趋势评分；"
        f"{_span('<30偏弱/超卖', 'attention')}；"
        f"{_span('30-70中性', 'neutral')}；"
        f"{_span('>70偏强/过热', 'warn')}"
    )


def _rsi_alert(item: dict) -> str:
    rsi6 = _float_or_none(item.get("rsi6"))
    rsi14 = _float_or_none(item.get("rsi14"))
    if rsi6 is not None and rsi6 > 85:
        return _span("RSI6短线过热，避免追高", "danger")
    if rsi6 is not None and rsi6 < 40:
        return _span("RSI6偏弱，等修复确认", "attention")
    if rsi14 is None:
        return _cell_html("RSI数据不足")
    if rsi14 >= 80:
        return _span("短线明显过热，避免追高", "danger")
    if rsi14 >= 70:
        return _span("偏强但接近过热", "warn")
    if rsi14 <= 20:
        return _span("极弱区，先等止跌", "loss strong")
    if rsi14 <= 30:
        return _span("偏弱/超卖，反弹需确认", "attention")
    return _span("强弱中性", "neutral")


def _macd_summary(item: dict) -> str:
    return "；".join(
        [
            f"DIF(快线): {_num(item.get('macd_dif'), 4)}",
            f"DEA(慢线): {_num(item.get('macd_dea'), 4)}",
            f"柱(动能柱): {_num(item.get('macd_hist'), 4)}",
        ]
    )


def _macd_compare(item: dict) -> str:
    return _cell_html("DIF(快线)>DEA(慢线)偏多；DIF<DEA偏空；柱(动能柱)扩大代表动能增强")


def _macd_alert(item: dict) -> str:
    dif = _float_or_none(item.get("macd_dif"))
    dea = _float_or_none(item.get("macd_dea"))
    hist = _float_or_none(item.get("macd_hist"))
    if dif is None or dea is None or hist is None:
        return _cell_html("MACD数据不足")
    if dif > dea and hist > 0 and dif > 0 and dea > 0:
        return _span("零轴上方多头，动能偏强", "profit")
    if dif > dea and hist > 0:
        return _span("DIF在DEA上方，短线修复", "attention")
    if dif < dea and hist < 0 and dif < 0 and dea < 0:
        return _span("零轴下方空头，趋势偏弱", "loss strong")
    if dif < dea and hist < 0:
        return _span("DIF在DEA下方，动能转弱", "warn")
    return _span("多空接近，等待方向确认", "neutral")


def _action_merged_html(item: dict) -> str:
    parts = [
        _action_text(item),
        _inline_label("来源", item.get("candidate_source")),
        _inline_label("交易过滤", item.get("rule_filter_status")),
        _inline_label("持仓备注", item.get("investor_note")),
        _inline_label("仓位", _position_text(item)),
        _inline_label("目标", _position_decision_text(item)),
        _inline_label("风险等级", _risk_level_text(item.get("position_risk_level"))),
        _inline_label("执行计划", item.get("position_plan")),
        _inline_label("入场计划", item.get("entry_plan")),
        _inline_label("决策依据", "；".join(_filtered_action_reasons(item))),
    ]
    return _join_html(parts)


def _action_text(item: dict) -> str:
    action = str(item.get("action") or "-")
    qty = item.get("action_quantity")
    qty_text = "" if qty in (None, "") else f"；参考 {_num(qty, 0)} 份"
    return _span(_display_action(action) + qty_text, _action_class(action))


def _ai_judgement_html(item: dict) -> str:
    judgement = item.get("ai_judgement") or {}
    if not isinstance(judgement, dict):
        return _cell_html("AI 综合研判未生成")
    enabled = bool(judgement.get("enabled"))
    confidence = _float_or_none(judgement.get("confidence")) or 0
    if not enabled or confidence <= 0:
        return _join_html(
            [
                _span("AI复核未启用", "neutral"),
                _inline_label("说明", "本次完全采用规则引擎和风控约束"),
            ]
        )
    cls = "attention" if enabled else "neutral"
    if confidence < 60:
        return _join_html(
            [
                _span(str(judgement.get("ai_action") or "低置信复核"), "neutral"),
                _inline_label("置信度", f"{_num(confidence, 0)}%"),
                _inline_label("说明", "低置信度，仅作备注，不改变规则动作"),
                _inline_label("最终倾向", judgement.get("final_bias")),
            ]
        )
    conflicts = "；".join(judgement.get("conflicts") or [])
    guardrails = "；".join(judgement.get("guardrails") or [])
    parts = [
        _span(str(judgement.get("ai_action") or "未启用"), cls),
        _inline_label("置信度", f"{_num(judgement.get('confidence'), 0)}%"),
        _inline_label("最终倾向", judgement.get("final_bias")),
        _inline_label("研判", judgement.get("judgement")),
        _inline_label("冲突点", conflicts),
        _inline_label("护栏", guardrails),
    ]
    return _join_html(parts)


def _overview_html(item: dict) -> str:
    risks = _filtered_risks(item)
    risk_text = "；".join(risks) if risks else "暂无明显新增风险"
    cls = "danger" if any(word in risk_text for word in ("跌破", "浮亏", "风险", "低于")) else "neutral"
    return _join_html(
        [
            _inline_label("观察价位", item.get("watch_price")),
            _inline_label("入场计划", item.get("entry_plan")),
            f'<span class="{cls}">{escape(_simplify_direction_text(risk_text))}</span>',
        ]
    )


def _combined_conclusion_html(item: dict) -> str:
    judgement = item.get("ai_judgement") or {}
    ai_text = ""
    if isinstance(judgement, dict):
        ai_action = judgement.get("ai_action")
        final_bias = judgement.get("final_bias")
        ai_text = "；".join(str(part) for part in (ai_action, final_bias) if part)
    parts = [
        _action_text(item),
        _inline_label("仓位", _position_text(item)),
        _inline_label("计划", item.get("position_plan")),
        _inline_label("依据", "；".join(_filtered_action_reasons(item)[:2])),
        _inline_label("AI", ai_text),
        _inline_label("风险", "；".join(_filtered_risks(item)[:2])),
    ]
    return _join_html(parts)


def _detail_drawer_html(item: dict) -> str:
    content = _join_html(
        [
            f"<strong>动作</strong>{_action_merged_html(item)}",
            f"<strong>AI</strong>{_ai_judgement_html(item)}",
            f"<strong>证据</strong>{_layered_evidence_html(item)}",
            f"<strong>摘要</strong>{_overview_html(item)}",
        ]
    )
    return f'<details class="detail-drawer"><summary>展开动作 / AI / 证据 / 摘要</summary><div class="detail-body">{content}</div></details>'


def _layered_evidence_html(item: dict) -> str:
    context = item.get("layered_context") or {}
    if not isinstance(context, dict):
        return _cell_html("七层证据未生成")
    layers = context.get("layers") or []
    if not layers:
        return _cell_html("七层证据未生成")
    chips = []
    for layer in layers:
        name = _cell(layer.get("name"))
        status = _cell(layer.get("status"))
        if status == "待接入":
            continue
        score = _float_or_none(layer.get("score"))
        score_text = "" if score is None or score == 0 else f" {score:+.0f}"
        cls = _layer_status_class(status, score)
        chips.append(_span(f"{_short_layer_name(name)}:{score_text.strip() or '0'}", cls))
    summary = _clean_layer_summary(_cell(context.get("summary")))
    return _join_html(
        [
            _inline_label("置信度", f"{_num(context.get('confidence'), 0)}%"),
            _inline_label("总分", _num(context.get("total_score"), 0)),
            " ".join(chips),
            escape(summary),
        ]
    )


def _short_layer_name(name: str) -> str:
    mapping = {
        "行情技术层": "行情",
        "研报预期层": "研报",
        "热点信号层": "热点",
        "资金筹码层": "资金",
        "新闻舆情层": "新闻",
        "基础数据层": "基本面",
        "公告事件层": "公告",
    }
    return mapping.get(name, name.replace("层", ""))


def _clean_layer_summary(text: str) -> str:
    text = re.sub(r"七层证据当前置信度\s*\d+(?:\.\d+)?%[；,，。]?", "", text)
    text = re.sub(r"证据置信度[:：]\s*\d+(?:\.\d+)?%[；,，。]?", "", text)
    return _simplify_direction_text(text.strip("；,，。 ")) or "-"


def _layer_status_class(status: str, score: float | None) -> str:
    if status == "待接入":
        return "attention"
    if score is not None and score < 0:
        return "warn"
    if score is not None and score > 0:
        return "profit"
    return "neutral"


def _filtered_risks(item: dict) -> list[str]:
    return [
        str(risk)
        for risk in (item.get("risks") or [])
        if not str(risk).startswith("行情数据完整性:") and not _is_internal_guardrail_text(str(risk))
    ]


def _filtered_action_reasons(item: dict) -> list[str]:
    reasons = [
        str(reason)
        for reason in (item.get("reasons") or [])
        if "七层证据" not in str(reason) and "缺少 " not in str(reason)
    ]
    if not reasons:
        reasons = [
            str(risk)
            for risk in _filtered_risks(item)
            if "七层证据" not in str(risk) and "缺少 " not in str(risk)
        ]
    return reasons[:4]


def _position_text(item: dict) -> str:
    if item.get("quantity") is None:
        tier = _cell(item.get("position_tier"))
        target = _pct(item.get("target_position_pct"))
        return f"未持仓，{tier}，目标仓位 {target}"
    tier = _cell(item.get("position_tier"))
    pct = _pct(item.get("position_pct"))
    holding_pct = _pct(item.get("holding_pct")) if item.get("holding_pct") is not None else "-"
    value = _num(item.get("market_value"), 2)
    source = _position_pct_source_text(item.get("position_pct_source"))
    return f"资金仓 {pct}，持仓内 {holding_pct}，{tier}，市值 {value}，口径 {source}"


def _position_decision_text(item: dict) -> str:
    target = _pct(item.get("target_position_pct"))
    new_position = _pct(item.get("new_position_pct"))
    adjust = _signed_pct(item.get("adjust_pct")) if item.get("adjust_pct") is not None else "-"
    action = _position_action_text(item.get("position_action"))
    return f"目标 {target}，本次后 {new_position}，调整 {adjust}，动作 {action}"


def _grid_row(label: str, current: Any, suggested: Any, suffix: str) -> dict[str, Any]:
    changed = _changed(current, suggested)
    return _row(
        label,
        _cell_html(_format_with_suffix(current, suffix)),
        _span(_format_with_suffix(suggested, suffix), "warn" if changed else "neutral"),
        _span("需调整", "warn") if changed else "",
    )


def _grid_sell_row(item: dict) -> dict[str, Any]:
    current_qty = item.get("current_sell_quantity") or item.get("current_quantity")
    suggested_qty = item.get("suggested_sell_quantity")
    changed = any(
        _changed(left, right)
        for left, right in (
            (item.get("current_sell_rise_pct"), item.get("suggested_sell_rise_pct")),
            (item.get("current_sell_pullback_pct"), item.get("suggested_sell_pullback_pct")),
            (current_qty, suggested_qty),
        )
    )
    return _row(
        "卖",
        _grid_sell_text(item.get("current_sell_rise_pct"), item.get("current_sell_pullback_pct"), current_qty),
        _grid_sell_text(item.get("suggested_sell_rise_pct"), item.get("suggested_sell_pullback_pct"), suggested_qty),
        _span("需调整", "warn") if changed else "",
    )


def _grid_buy_row(item: dict) -> dict[str, Any]:
    current_qty = item.get("current_buy_quantity") or item.get("current_quantity")
    suggested_qty = item.get("suggested_buy_quantity")
    changed = any(
        _changed(left, right)
        for left, right in (
            (item.get("current_buy_fall_pct"), item.get("suggested_buy_fall_pct")),
            (item.get("current_buy_rebound_pct"), item.get("suggested_buy_rebound_pct")),
            (current_qty, suggested_qty),
        )
    )
    return _row(
        "买",
        _grid_buy_text(item.get("current_buy_fall_pct"), item.get("current_buy_rebound_pct"), current_qty),
        _grid_buy_text(item.get("suggested_buy_fall_pct"), item.get("suggested_buy_rebound_pct"), suggested_qty),
        _span("需调整", "warn") if changed else "",
    )


def _grid_position_limit_row(item: dict) -> dict[str, Any]:
    changed = any(
        _changed(left, right)
        for left, right in (
            (item.get("current_min_base_quantity"), item.get("suggested_min_base_quantity")),
            (item.get("current_max_position_quantity"), item.get("suggested_max_position_quantity")),
        )
    )
    return _row(
        "仓位",
        _grid_limit_text(item.get("current_min_base_quantity"), item.get("current_max_position_quantity")),
        _grid_limit_text(item.get("suggested_min_base_quantity"), item.get("suggested_max_position_quantity")),
        _span("需调整", "warn") if changed else "",
    )


def _grid_sell_text(rise: Any, pullback: Any, qty: Any) -> str:
    return "".join(
        [
            "涨",
            _grid_pct_html(rise, "profit", "+"),
            "，回落",
            _grid_pct_html(pullback, "loss", "-"),
            "，",
            _grid_qty_html(qty),
        ]
    )


def _grid_buy_text(fall: Any, rebound: Any, qty: Any) -> str:
    return "".join(
        [
            "跌",
            _grid_pct_html(fall, "loss", "-"),
            "，反弹",
            _grid_pct_html(rebound, "profit", "+"),
            "，",
            _grid_qty_html(qty),
        ]
    )


def _grid_limit_text(min_base: Any, max_position: Any) -> str:
    return f"底仓{_grid_qty_html(min_base)}，最大{_grid_qty_html(max_position)}"


def _grid_pct_html(value: Any, cls: str, sign: str) -> str:
    number = _float_or_none(value)
    if number is None:
        return "-"
    return f'<span class="{cls}">{sign}{abs(number):.2f}%</span>'


def _grid_qty_html(value: Any) -> str:
    number = _float_or_none(value)
    if number is None:
        return "-"
    return f'<span class="attention">{number:.0f}股</span>'


def _rule_score_summary(item: dict) -> str:
    rule = item.get("rule_decision") or {}
    return "；".join(
        [
            f"趋势评分 {_num(item.get('rule_trend_score'), 0)}",
            f"趋势等级 {_cell(rule.get('trend_level') if isinstance(rule, dict) else None)}",
            f"过滤状态 {_cell(item.get('rule_filter_status'))}",
            f"风险等级 {_risk_level_text(item.get('position_risk_level'))}",
        ]
    )


def _rule_score_detail(item: dict) -> str:
    rule = item.get("rule_decision") or {}
    if not isinstance(rule, dict):
        return _cell_html("规则评分未生成")
    scores = rule.get("trend_scores") or {}
    tags = "、".join(rule.get("trend_tags") or [])
    trend_parts = ""
    if isinstance(scores, dict) and scores:
        trend_parts = "趋势评分分项 " + "/".join(
            [
                f"MA{_num(scores.get('ma_score'), 0)}",
                f"VOL{_num(scores.get('vol_score'), 0)}",
                f"BOLL{_num(scores.get('boll_score'), 0)}",
                f"BIAS{_num(scores.get('bias_score'), 0)}",
                f"RSI{_num(scores.get('rsi_score'), 0)}",
            ]
        )
    return _cell_html(
        "；".join(
            part
            for part in [
                f"类型 {rule.get('category') or '-'}",
                f"短线趋势 {rule.get('trend_level') or '-'}",
                trend_parts,
                f"标签 {tags}" if tags else "",
                f"仓位动作 {_position_action_text(rule.get('position_action') or rule.get('action_name') or rule.get('action'))}",
                f"风险等级 {_risk_level_text(rule.get('risk_level'))}",
                f"当前/目标/本次后 {_pct(rule.get('current_position_pct'))}/{_pct(rule.get('target_position_pct'))}/{_pct(rule.get('new_position_pct'))}",
                f"调整 {_signed_pct(rule.get('adjust_pct'))}",
            ]
            if part
        )
    )


def _rule_score_alert(item: dict) -> str:
    rule = item.get("rule_decision") or {}
    if not isinstance(rule, dict):
        return _cell_html("-")
    status = str(rule.get("filter_status") or "")
    blocked = rule.get("blocked_actions") or []
    if status == "禁止交易" or "全部" in blocked:
        return _span("触发硬过滤", "danger")
    if {"买入", "加仓", "提高网格买入侧"} & set(blocked):
        return _span("限制新增买入", "warn")
    if str(rule.get("risk_level") or "") == "HIGH":
        return _span("风险等级偏高", "danger")
    return _span("规则允许正常复核", "neutral")


def _volume_ratio_class(value: Any) -> str:
    number = _float_or_none(value)
    if number is None:
        return "neutral"
    if number >= 2:
        return "warn"
    if number >= 1.2:
        return "profit"
    if number <= 0.75:
        return "attention"
    return "neutral"


def _turnover_class(value: Any) -> str:
    number = _float_or_none(value)
    if number is None:
        return "neutral"
    if number >= 10:
        return "warn"
    if number >= 5:
        return "profit"
    if number < 1:
        return "attention"
    return "neutral"


def _amount_ratio_class(value: Any) -> str:
    number = _float_or_none(value)
    if number is None:
        return "neutral"
    if number >= 1.5:
        return "warn"
    if number >= 1.1:
        return "profit"
    if number <= 0.7:
        return "attention"
    return "neutral"


def _volume_summary(item: dict) -> str:
    return "；".join(
        [
            f"成交量 {_colored_num(item.get('volume'), 0, 'neutral')}",
            f"量比 {_colored_num(item.get('vol_ratio'), 2, _volume_ratio_class(item.get('vol_ratio')))}",
            f"换手 {_colored_pct(item.get('turnover_pct'), _turnover_class(item.get('turnover_pct')))}",
            f"成交额/20日 {_colored_num(item.get('amount_ratio20'), 2, _amount_ratio_class(item.get('amount_ratio20')))}",
        ]
    )


def _volume_compare(item: dict) -> str:
    vol5 = _float_or_none(item.get("vol_ma5"))
    vol20 = _float_or_none(item.get("vol_ma20"))
    if vol5 is None or vol20 is None:
        return _cell_html("量能均线不足")
    ratio = vol5 / vol20 if vol20 else 0
    return f"5/20: {_colored_num(ratio, 2, _volume_ratio_class(ratio))} 倍"


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
            _span(f"网格:{_display_action(str(item.get('action') or '-'))}", _grid_action_class(str(item.get("action") or ""))),
            _inline_label("用途", item.get("grid_purpose")),
            _inline_label("胜率护栏", "；".join(_report_guardrails(item))),
            _inline_label("基准", item.get("base_price_status")),
            _inline_label("基准判断", item.get("base_price_reason")),
            _inline_label("依据", "；".join(item.get("reasons") or [])),
        ]
    )


def _report_guardrails(item: dict) -> list[str]:
    return [
        str(guardrail)
        for guardrail in (item.get("strategy_guardrails") or [])
        if "条件单用于替代盯盘" not in str(guardrail)
    ]


def _changed(left: Any, right: Any) -> bool:
    lnum = _float_or_none(left)
    rnum = _float_or_none(right)
    if lnum is None or rnum is None:
        return False
    return abs(lnum - rnum) >= max(0.01, abs(lnum) * 0.1)


def _format_with_suffix(value: Any, suffix: str) -> str:
    digits = 2 if suffix.strip() == "%" else 4 if not suffix.strip() else 0
    number = _num(value, digits)
    return "-" if number == "-" else f"{number}{suffix}"


def _row(label: str, current: str, reference: str, alert: str) -> dict[str, Any]:
    return {
        "label": label,
        "current": _metric_value_html(current),
        "reference": _metric_value_html(reference),
        "alert": alert,
        "merged": False,
    }


def _merged_row(label: str, content: str) -> dict[str, Any]:
    return {"label": label, "content": content, "merged": True}


def _pill(text: str, cls: str) -> str:
    return f'<span class="pill {escape(cls)}">{escape(text)}</span>'


def _display_action(action: str) -> str:
    return _simplify_direction_text(_enum_text(action))


def _enum_text(value: Any) -> str:
    text = str(value or "")
    mapping = {
        "NO_ACTION": "不操作",
        "WATCH": "观察",
        "OPEN": "建仓",
        "LIGHT_OPEN": "轻仓建仓",
        "HOLD": "持有",
        "ADD": "加仓",
        "HOLD_OR_ADD": "持有观察",
        "HOLD_WAIT_ADD": "持有待加仓确认",
        "HOLD_OR_REDUCE": "持有或小幅减仓",
        "REDUCE": "减仓",
        "TREND_REVIEW": "趋势复核",
        "EXIT_TREND_POSITION": "退出短线仓位",
        "RISK_REVIEW": "风控复核",
        "EXIT_SHORT_TERM": "退出短线仓位",
    }
    return mapping.get(text, text)


def _position_action_text(value: Any) -> str:
    return _display_action(_cell(value))


def _risk_level_text(value: Any) -> str:
    mapping = {"HIGH": "高", "MEDIUM": "中", "LOW": "低"}
    return mapping.get(str(value or ""), _cell(value))


def _position_pct_source_text(value: Any) -> str:
    mapping = {
        "ths_account_total_asset": "同花顺账户总资产",
        "ths_position_fund_pct": "同花顺资金仓",
        "positions_market_value_fallback": "持仓市值估算",
        "missing": "缺失",
    }
    return mapping.get(str(value or ""), _cell(value))


def _preferred_name(current: Any, candidate: Any, code: str) -> str:
    current_text = _cell(current)
    candidate_text = _cell(candidate)
    if _is_human_etf_name(current_text, code):
        return current_text
    if _is_human_etf_name(candidate_text, code):
        return candidate_text
    return candidate_text if candidate_text != "-" else current_text if current_text != "-" else code


def _is_human_etf_name(value: str, code: str) -> bool:
    text = str(value or "").strip()
    if not text or text == "-" or text == code:
        return False
    if text.lower() in {code.lower(), f"{code}.sh", f"{code}.sz", f"sh{code}", f"sz{code}"}:
        return False
    return bool(any("\u4e00" <= ch <= "\u9fff" for ch in text))


def _span(value: Any, cls: str) -> str:
    return f'<span class="{escape(cls)}">{escape(_simplify_direction_text(_cell(value)))}</span>'


def _inline_label(label: str, value: Any) -> str:
    text = _simplify_direction_text(_cell(value))
    if text == "-":
        return ""
    return f'<span class="inline-label">{escape(label)}：</span>{_highlight_keywords(text)}'


def _join_html(parts: list[str]) -> str:
    return "".join(f'<div class="info-line">{part}</div>' for part in parts if part)


def _cell_html(value: Any) -> str:
    return escape(_simplify_direction_text(_cell(value)))


def _metric_value_html(value: Any) -> str:
    text = _simplify_direction_text(_cell(value))
    if "<" in text and ">" in text:
        return text
    if "&lt;" in text or "&gt;" in text:
        return text
    escaped = escape(text)
    return re.sub(r"([+-]\d+(?:\.\d+)?%?)", _signed_number_span, escaped)


def _signed_number_span(match: re.Match[str]) -> str:
    value = match.group(1)
    cls = "profit" if value.startswith("+") else "loss"
    return f'<span class="{cls}">{value}</span>'


def _highlight_keywords(text: str) -> str:
    escaped = escape(_simplify_direction_text(text))
    rules = [
        (r"(停买|暂停|风控|禁止|高风险|跌破|过热)", "danger"),
        (r"(降低买|降买|调宽|调窄|需调整|谨慎)", "warn"),
        (r"(买入|加仓|建仓|偏强|盈利|修复)", "profit"),
        (r"(卖出|减仓|退出|亏损|偏弱)", "loss"),
        (r"(持有|观察|等待|维持)", "attention"),
    ]
    for pattern, cls in rules:
        escaped = re.sub(pattern, rf'<strong class="{cls}">\1</strong>', escaped)
    return escaped


def _simplify_direction_text(value: Any) -> str:
    text = str(value)
    replacements = {
        "ShortTrendScore": "趋势评分",
        "持有或加仓": "持有观察",
        "持有待加仓确认": "持有观察",
        "持有待确认": "持有观察",
        "暂停买入侧": "降低买",
        "暂停买入": "降低买",
        "降低买入侧": "降低买",
        "提高买入侧": "提高买",
        "网格买入侧": "网格买",
        "买入侧": "买",
        "卖出侧": "卖",
        "买入触发": "买触发",
        "卖出触发": "卖触发",
        "买触发": "买条件",
        "卖触发": "卖条件",
        "买入数量": "买数量",
        "卖出数量": "卖数量",
        "风险等级 HIGH": "风险等级高",
        "风险等级 MEDIUM": "风险等级中",
        "风险等级 LOW": "风险等级低",
        "风险等级高 且": "风险等级高且",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _is_clean_watchlist_item(item: dict | None) -> bool:
    if not item or not item.get("is_watchlist_candidate"):
        return False
    return not _is_position_cache_source_key(item.get("watchlist_source_key"))


def _is_position_cache_source_key(value: Any) -> bool:
    text = str(value or "").lower()
    return any(token in text for token in ("defaultpositioin", "defaultposition", "positionlist"))


def _is_internal_guardrail_text(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "今日不应给",
            "不生成今日",
            "不输出今日",
            "今日可立即执行",
        )
    )


def _color_number(value: Any, suffix: str = "") -> str:
    number = _float_or_none(value)
    if number is None:
        return "-"
    cls = "profit" if number > 0 else "loss" if number < 0 else "neutral"
    return _span(f"{number:.2f}{suffix}", cls)


def _pnl_class(item: dict | None) -> str:
    if not item or item.get("quantity") is None:
        return "neutral"
    number = _float_or_none(item.get("pnl_pct"))
    if number is None:
        return "neutral"
    if number > 0:
        return "profit"
    if number < 0:
        return "loss"
    return "neutral"


def _pnl_text(item: dict | None) -> str:
    if not item or item.get("quantity") is None:
        return "未持仓"
    number = _float_or_none(item.get("pnl_pct"))
    if number is None:
        return "-"
    return f"{number:+.2f}%"


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
    if "持有待" in action or "持有或加仓" in action or "持有观察" in action:
        return "attention"
    if "暂停" in action:
        return "action-pause"
    if "风控" in action:
        return "action-pause"
    if any(word in action for word in ("买入", "加仓", "建仓")):
        return "action-buy"
    if any(word in action for word in ("减仓", "卖出", "退出")):
        return "action-sell"
    return "neutral"


def _grid_action_class(action: str) -> str:
    if "暂停" in action or "只保留卖出" in action or "人工复核" in action:
        return "action-pause"
    if "暂不设" in action:
        return "attention"
    if "新建" in action:
        return "action-buy"
    if any(word in action for word in ("调宽", "调窄", "调整", "降低")):
        return "warn"
    return "neutral"


def _nav_signal(action: str, grid_action: str, item: dict | None) -> dict[str, str]:
    display_action = _compact_action(_display_action(action))
    action_class = _action_class(action)
    rule = (item or {}).get("rule_decision") or {}
    trend_code = rule.get("trend_code") if isinstance(rule, dict) else None
    heat, heat_class = _trend_heat((item or {}).get("rule_trend_score"), trend_code)
    meta = _nav_meta(item)
    return {
        "heat": heat,
        "heat_class": heat_class,
        "heat_tip": _trend_heat_tip(item, heat),
        "action": display_action,
        "action_class": action_class,
        "meta": meta,
    }


def _trend_heat_tip(item: dict | None, heat: str) -> str:
    if not item:
        return f"温度 {heat}；趋势评分 -；趋势等级 -"
    rule = item.get("rule_decision") or {}
    trend_level = rule.get("trend_level") if isinstance(rule, dict) else None
    trend_score = item.get("rule_trend_score")
    return f"温度 {heat}；趋势评分 {_num(trend_score, 0)}；趋势等级 {_cell(trend_level)}"


def _trend_heat(value: Any, trend_code: Any = None) -> tuple[str, str]:
    by_code = {
        "STRONG_TREND": ("热", "heat-hot"),
        "UPTREND": ("温", "heat-warm"),
        "WEAK_UPTREND": ("平", "heat-flat"),
        "SIDEWAYS": ("凉", "heat-cool"),
        "WEAK": ("寒", "heat-cold"),
    }
    if trend_code in by_code:
        return by_code[str(trend_code)]
    score = _float_or_none(value)
    if score is None:
        return "平", "heat-flat"
    if score >= 85:
        return "热", "heat-hot"
    if score >= 75:
        return "温", "heat-warm"
    if score >= 60:
        return "平", "heat-flat"
    if score >= 45:
        return "凉", "heat-cool"
    return "寒", "heat-cold"


def _compact_action(action: str) -> str:
    if "暂停" in action:
        return "暂停买入"
    if "风控" in action:
        return "风控复核"
    if "退出" in action:
        return "退出短线"
    if "持有待" in action or "持有观察" in action:
        return "持有"
    if "持有或加仓" in action:
        return "持有"
    if "轻仓建仓" in action:
        return "轻仓建仓"
    if "分批买入" in action:
        return "分批加仓"
    if "买入" in action or "加仓" in action:
        return "加仓"
    if "建仓" in action:
        return "建仓"
    if "减仓" in action:
        return "减仓"
    if "卖出" in action:
        return "卖出"
    if "观察" in action or "等待" in action:
        return "观察/等待"
    if "持有" in action:
        return "持有"
    return action if action and action != "-" else "待定"


def _compact_grid_action(action: str) -> str:
    display = _display_action(action)
    if "暂不设" in display:
        return "暂不设"
    if "新建" in display:
        return "新建"
    if "只保留卖出" in display:
        return "只卖"
    if "暂停" in display:
        return "暂停买"
    if "人工复核" in display:
        return "复核"
    if "停买" in display:
        return "降买"
    if "降低买" in display:
        return "降买"
    if "调宽" in display:
        return "调宽"
    if "调窄" in display:
        return "调窄"
    if "维持" in display:
        return "维持"
    if "无网格" in display:
        return "无网格"
    return display if display and display != "-" else "待定"


def _nav_meta(item: dict | None) -> str:
    if not item:
        return "无持仓建议"
    parts = []
    position_pct = item.get("position_pct")
    target_pct = item.get("target_position_pct")
    if position_pct is not None:
        parts.append(f"{_pct(position_pct)}")
    elif target_pct is not None:
        parts.append(f"目标 {_pct(target_pct)}")
    pct_chg = item.get("pct_chg")
    if pct_chg is not None:
        parts.append(_signed_pct(pct_chg))
    return " · ".join(part for part in parts if part) or _cell(item.get("position_tier"))


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


def _float_or_none_from_text(value: Any) -> float | None:
    text = str(value or "")
    match = re.search(r"[+-]?\d+(?:\.\d+)?", text)
    return _float_or_none(match.group(0)) if match else None


def _cell(value: Any) -> str:
    text = "-" if value is None or value == "" else str(value)
    text = text.replace("\n", " ").strip()
    text = _simplify_direction_text(text)
    return text if text else "-"
