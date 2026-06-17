from __future__ import annotations

from pathlib import Path


def render_markdown(date: str, recommendations: list[dict], grid_advices: list[dict], trade_review: dict, data_completeness: dict | None = None) -> str:
    lines = [f"# ETFMate 每日复盘 {date}", ""]
    lines.extend(["## 持仓建议", ""])
    if not recommendations:
        lines.append("暂无可分析 ETF，需先完成采集或导入 raw 数据。")
    else:
        lines.extend([
            "| 代码 | 名称 | 数量 | 市值 | 仓位% | 成本 | 现价 | 盈亏% | BOLL% | 均线 | ATR% | BIAS6 | 动作 | 观察位 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|---|",
        ])
        for item in recommendations:
            lines.append(
                "| {code} | {name} | {quantity} | {market_value} | {position_pct} | {cost_price} | {last_price} | {pnl_pct} | {boll} | {ma} | {atr} | {bias} | {action} | {watch} |".format(
                    code=item["code"],
                    name=_cell(item["name"]),
                    quantity=_num(item.get("quantity"), 0),
                    market_value=_num(item.get("market_value"), 2),
                    position_pct=_num(item.get("position_pct"), 2),
                    cost_price=_num(item.get("cost_price"), 3),
                    last_price=_num(item.get("last_price"), 3),
                    pnl_pct=_num(item.get("pnl_pct"), 2),
                    boll=_num(item.get("boll_position_pct"), 1),
                    ma=_cell(item.get("ma_status", "")),
                    atr=_num(item.get("atr14_pct"), 2),
                    bias=_num(item.get("bias6"), 2),
                    action=item["action"],
                    watch=_cell(item["watch_price"]),
                )
            )
        lines.extend(["", "### 持仓理由与风险", ""])
        lines.extend([
            "| 代码 | 动作 | 理由 | 风险 |",
            "|---|---|---|---|",
        ])
        for item in recommendations:
            lines.append(f"| {item['code']} | {item['action']} | {_cell('；'.join(item['reasons']))} | {_cell('；'.join(item['risks']))} |")

    lines.extend(["## 网格参数评估", ""])
    if not grid_advices:
        lines.append("暂无网格配置数据。")
    else:
        lines.extend([
            "| 代码 | 名称 | 动作 | 当前买入跌幅% | 建议买入跌幅% | 当前卖出涨幅% | 建议卖出涨幅% | 当前股数 | 建议买入股数 | 建议卖出股数 | 依据 |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ])
        for item in grid_advices:
            lines.append(
                "| {code} | {name} | {action} | {cur_buy} | {buy} | {cur_sell} | {sell} | {cur_qty} | {buy_qty} | {sell_qty} | {reason} |".format(
                    code=item["code"],
                    name=_cell(item["name"]),
                    action=item["action"],
                    cur_buy=_num(item.get("current_buy_fall_pct"), 2),
                    buy=_num(item.get("suggested_buy_fall_pct"), 2),
                    cur_sell=_num(item.get("current_sell_rise_pct"), 2),
                    sell=_num(item.get("suggested_sell_rise_pct"), 2),
                    cur_qty=_num(item.get("current_quantity"), 0),
                    buy_qty=_num(item.get("suggested_buy_quantity"), 0),
                    sell_qty=_num(item.get("suggested_sell_quantity"), 0),
                    reason=_cell("；".join(item["reasons"])),
                )
            )

    lines.extend([
        "",
        "## 当日交易复盘",
        "",
    ])
    trade_reviews = trade_review.get("periods") or []
    if trade_reviews:
        lines.extend([
            "| 周期 | 评分 | 笔数 | 买入金额 | 卖出金额 | 手续费 | 优点 | 问题 | 改进 | 计划 |",
            "|---|---:|---:|---:|---:|---:|---|---|---|---|",
        ])
        for item in trade_reviews:
            lines.append(
                f"| {item['period']} | {item['score']}/10 | {item['trade_count']} | {_num(item['buy_amount'], 2)} | {_num(item['sell_amount'], 2)} | {_num(item['fee'], 2)} | {_cell('；'.join(item['positives']))} | {_cell('；'.join(item['problems']))} | {_cell(item['improvement'])} | {_cell(item['plan'])} |"
            )
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
