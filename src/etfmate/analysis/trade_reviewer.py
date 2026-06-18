from __future__ import annotations

from datetime import date, datetime, timedelta

from etfmate.storage.models import Trade


def review_trade_periods(trades: list[Trade], run_date: str) -> list[dict]:
    return [
        _review_period("本次日内复盘", trades, run_date, 0),
        _review_period("近3日复盘", trades, run_date, 3),
        _review_period("近7日复盘", trades, run_date, 7),
        _review_period("近30日复盘", trades, run_date, 30),
    ]


def review_trades(trades: list[Trade]) -> dict:
    score = 6
    positives: list[str] = []
    problems: list[str] = []

    if not trades:
        return {
            "score": 6,
            "positives": ["今日无交易，避免了无效操作"],
            "problems": ["无交易样本，无法评估买卖点质量"],
            "improvement": "保持记录完整，等待有交易日再复盘",
            "tomorrow_plan": "按网格和趋势条件执行，不追涨杀跌",
        }

    if len(trades) <= 5:
        score += 1
        positives.append("交易频率可控")
    else:
        score -= 1
        problems.append("交易笔数偏多，需要检查手续费和策略偏离")

    total_amount = sum(trade.amount for trade in trades)
    if total_amount > 0:
        positives.append(f"已记录成交金额 {total_amount:.2f} 元")

    score = max(0, min(10, score))
    return {
        "score": score,
        "positives": positives or ["交易记录完整"],
        "problems": problems or ["需要结合技术指标进一步评价买卖点"],
        "improvement": "逐笔标注是否符合网格触发条件",
        "tomorrow_plan": "先确认仓位上限，再决定是否加仓或调参",
    }


def _review_period(label: str, trades: list[Trade], run_date: str, days: int) -> dict:
    selected = _filter_trades(trades, run_date, days)
    base = review_trades(selected)
    buy_amount = sum(trade.amount for trade in selected if trade.side.upper() in {"BUY", "买入"})
    sell_amount = sum(trade.amount for trade in selected if trade.side.upper() in {"SELL", "卖出"})
    fees = sum(trade.fee or 0 for trade in selected)
    return {
        "period": label,
        "score": base["score"],
        "trade_count": len(selected),
        "buy_amount": round(buy_amount, 2),
        "sell_amount": round(sell_amount, 2),
        "fee": round(fees, 2),
        "positives": base["positives"],
        "problems": base["problems"],
        "improvement": base["improvement"],
        "plan": base["tomorrow_plan"],
    }


def _filter_trades(trades: list[Trade], run_date: str, days: int) -> list[Trade]:
    end = _parse_date(run_date)
    start = end if days == 0 else end - timedelta(days=days - 1)
    selected: list[Trade] = []
    for trade in trades:
        trade_date = _parse_date(trade.trade_date)
        if start <= trade_date <= end:
            selected.append(trade)
    return selected


def _parse_date(value: str) -> date:
    return datetime.strptime(value[:10], "%Y-%m-%d").date()
