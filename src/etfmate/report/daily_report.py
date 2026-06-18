from __future__ import annotations

from pathlib import Path


def render_markdown(date: str, recommendations: list[dict], grid_advices: list[dict], trade_review: dict, data_completeness: dict | None = None) -> str:
    lines = [f"# ETFMate 每日复盘 {date}", ""]
    lines.extend(["## 持仓建议", ""])
    if not recommendations:
        lines.append("暂无可分析 ETF，需先完成采集或导入 raw 数据。")
    else:
        for item in recommendations:
            lines.extend([
                f"### {item['code']} {item['name']}",
                _metric_line(
                    [
                        ("数量", _num(item.get("quantity"), 0)),
                        ("市值", _num(item.get("market_value"), 2)),
                        ("仓位", _pct(item.get("position_pct"))),
                        ("成本", _num(item.get("cost_price"), 3)),
                        ("现价", _num(item.get("last_price"), 3)),
                        ("盈亏", _pct(item.get("pnl_pct"))),
                    ]
                ),
                _metric_line(
                    [
                        ("BOLL", _pct(item.get("boll_position_pct"))),
                        ("均线", _cell(item.get("ma_status", ""))),
                        ("ATR14", _pct(item.get("atr14_pct"))),
                        ("BIAS6", _pct(item.get("bias6"))),
                    ]
                ),
                f"建议动作：{item['action']}",
                "理由：" + "；".join(item["reasons"]),
                "风险：" + "；".join(item["risks"]),
                f"观察价位：{item['watch_price']}",
                "",
            ])

    lines.extend(["## 网格参数评估", ""])
    if not grid_advices:
        lines.append("暂无网格配置数据。")
    else:
        for item in grid_advices:
            lines.extend([
                f"### {item['code']} {item['name']}",
                f"建议动作：{item['action']}",
                _metric_line(
                    [
                        ("当前买入跌幅", _pct(item.get("current_buy_fall_pct"))),
                        ("建议买入跌幅", _pct(item.get("suggested_buy_fall_pct"))),
                        ("当前卖出涨幅", _pct(item.get("current_sell_rise_pct"))),
                        ("建议卖出涨幅", _pct(item.get("suggested_sell_rise_pct"))),
                    ]
                ),
                _metric_line(
                    [
                        ("当前股数", _num(item.get("current_quantity"), 0)),
                        ("建议买入股数", _num(item.get("suggested_buy_quantity"), 0)),
                        ("建议卖出股数", _num(item.get("suggested_sell_quantity"), 0)),
                    ]
                ),
                "依据：" + "；".join(item["reasons"]),
                "",
            ])

    lines.extend([
        "",
        "## 当日交易复盘",
        "",
    ])
    trade_reviews = trade_review.get("periods") or []
    if trade_reviews:
        lines.extend([
            "| 周期 | 评分 | 笔数 | 买入金额 | 卖出金额 | 手续费 |",
            "|---|---:|---:|---:|---:|---:|",
        ])
        for item in trade_reviews:
            lines.append(f"| {item['period']} | {item['score']}/10 | {item['trade_count']} | {_num(item['buy_amount'], 2)} | {_num(item['sell_amount'], 2)} | {_num(item['fee'], 2)} |")
        lines.append("")
        for item in trade_reviews:
            lines.extend([
                f"### {item['period']}",
                "优点：" + "；".join(item["positives"]),
                "问题：" + "；".join(item["problems"]),
                f"最需要改进的一点：{item['improvement']}",
                f"下一步计划：{item['plan']}",
                "",
            ])
    else:
        lines.extend([
            f"今日评分：{trade_review['score']}/10",
            "优点：" + "；".join(trade_review["positives"]),
            "问题：" + "；".join(trade_review["problems"]),
            f"最需要改进的一点：{trade_review['improvement']}",
            f"明日计划：{trade_review['tomorrow_plan']}",
        ])
    lines.extend(["", "## 数据完整性", ""])
    if data_completeness:
        lines.extend([
            "| 项目 | 数量 | 来源 | 备注 |",
            "|---|---:|---|---|",
        ])
        for item in data_completeness.get("items", []):
            lines.append(f"| {item['label']} | {item['count']} | {item['source']} | {item['note']} |")
    else:
        lines.append("数据完整性信息未提供。")
    lines.extend(["", "报告发布：如需公网分享，询问用户是否使用 shareone 发布，名称格式 `ETFMate-report-YYYY-MM-DD-HH-mm-ss`。", ""])
    return "\n".join(lines)


def write_report(path: Path, date: str, recommendations: list[dict], grid_advices: list[dict], trade_review: dict, data_completeness: dict | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(date, recommendations, grid_advices, trade_review, data_completeness), encoding="utf-8")
    return path


def _num(value, digits: int) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:.{digits}f}" if digits > 0 else f"{number:.0f}"


def _cell(value) -> str:
    return str(value or "-").replace("|", "/").replace("\n", " ")


def _pct(value) -> str:
    number = _num(value, 2)
    return "-" if number == "-" else f"{number}%"


def _metric_line(items: list[tuple[str, str]]) -> str:
    return "；".join(f"{label} {value}" for label, value in items)
