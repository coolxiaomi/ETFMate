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
    avg_trade_amount = total_amount / len(trades) if trades else 0
    fee_total = sum(trade.fee or 0 for trade in trades)
    fee_to_turnover_ratio = fee_total / total_amount if total_amount > 0 else 0
    ineffective_trade_count = sum(1 for trade in trades if 0 < trade.amount < 500)
    estimated_grid_profit = _estimate_grid_profit(trades)
    buy_after_down_count, sell_after_up_count = _follow_through_counts(trades)
    if total_amount > 0:
        positives.append(f"已记录成交金额 {total_amount:.2f} 元")
    if avg_trade_amount < 500 and trades:
        score -= 1
        problems.append("单笔金额偏小，手续费和滑点可能侵蚀网格收益")
    if fee_to_turnover_ratio > 0.001:
        score -= 1
        problems.append("手续费占成交额比例偏高")
    if buy_after_down_count:
        problems.append(f"有 {buy_after_down_count} 次买入后出现更低价同标的交易，需检查是否过早接跌")
    if sell_after_up_count:
        problems.append(f"有 {sell_after_up_count} 次卖出后出现更高价同标的交易，需检查止盈是否过密")

    score = max(0, min(10, score))
    return {
        "score": score,
        "positives": positives or ["交易记录完整"],
        "problems": problems or ["需要结合技术指标进一步评价买卖点"],
        "improvement": "逐笔标注是否符合网格触发条件",
        "tomorrow_plan": "先确认仓位上限，再决定是否加仓或调参",
        "avg_trade_amount": round(avg_trade_amount, 2),
        "fee_to_turnover_ratio": round(fee_to_turnover_ratio, 6),
        "estimated_grid_profit": None if estimated_grid_profit is None else round(estimated_grid_profit, 2),
        "ineffective_trade_count": ineffective_trade_count,
        "buy_after_down_count": buy_after_down_count,
        "sell_after_up_count": sell_after_up_count,
        "overtrading_flag": len(trades) > 80 or ineffective_trade_count >= 10,
    }


def _review_period(label: str, trades: list[Trade], run_date: str, days: int) -> dict:
    selected = _filter_trades(trades, run_date, days)
    base = review_trades(selected)
    buy_amount = sum(trade.amount for trade in selected if trade.side.upper() in {"BUY", "买入"})
    sell_amount = sum(trade.amount for trade in selected if trade.side.upper() in {"SELL", "卖出"})
    fees = sum(trade.fee or 0 for trade in selected)
    avg_trade_amount = sum(trade.amount for trade in selected) / len(selected) if selected else 0
    turnover = buy_amount + sell_amount
    fee_to_turnover_ratio = fees / turnover if turnover > 0 else 0
    estimated_grid_profit = _estimate_grid_profit(selected)
    ineffective_trade_count = sum(1 for trade in selected if 0 < trade.amount < 500)
    buy_after_down_count, sell_after_up_count = _follow_through_counts(selected)
    return {
        "period": label,
        "score": base["score"],
        "trade_count": len(selected),
        "buy_amount": round(buy_amount, 2),
        "sell_amount": round(sell_amount, 2),
        "fee": round(fees, 2),
        "avg_trade_amount": round(avg_trade_amount, 2),
        "fee_to_turnover_ratio": round(fee_to_turnover_ratio, 6),
        "estimated_grid_profit": None if estimated_grid_profit is None else round(estimated_grid_profit, 2),
        "ineffective_trade_count": ineffective_trade_count,
        "buy_after_down_count": buy_after_down_count,
        "sell_after_up_count": sell_after_up_count,
        "overtrading_flag": bool(base.get("overtrading_flag")),
        "positives": base["positives"],
        "problems": base["problems"],
        "improvement": base["improvement"],
        "plan": base["tomorrow_plan"],
    }


def _filter_trades(trades: list[Trade], run_date: str, days: int) -> list[Trade]:
    end = _parse_date(run_date)
    if end is None:
        return []
    start = end if days == 0 else end - timedelta(days=days - 1)
    selected: list[Trade] = []
    for trade in trades:
        trade_date = _parse_date(trade.trade_date)
        if trade_date is not None and start <= trade_date <= end:
            selected.append(trade)
    return selected


def _parse_date(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _estimate_grid_profit(trades: list[Trade]) -> float | None:
    lots: dict[str, list[list[float]]] = {}
    profit = 0.0
    matched = False
    for trade in sorted(trades, key=lambda item: (str(item.trade_date), str(item.trade_time or ""))):
        code = trade.code
        side = _side(trade)
        if side == "BUY":
            lots.setdefault(code, []).append([trade.quantity, trade.price])
        elif side == "SELL":
            remaining = trade.quantity
            queue = lots.setdefault(code, [])
            while remaining > 0 and queue:
                qty, price = queue[0]
                matched_qty = min(qty, remaining)
                profit += (trade.price - price) * matched_qty
                matched = True
                qty -= matched_qty
                remaining -= matched_qty
                if qty <= 0:
                    queue.pop(0)
                else:
                    queue[0][0] = qty
    return profit if matched else None


def _follow_through_counts(trades: list[Trade]) -> tuple[int, int]:
    by_code: dict[str, list[Trade]] = {}
    for trade in trades:
        by_code.setdefault(trade.code, []).append(trade)
    buy_after_down = 0
    sell_after_up = 0
    for rows in by_code.values():
        ordered = sorted(rows, key=lambda item: (str(item.trade_date), str(item.trade_time or "")))
        for idx, trade in enumerate(ordered[:-1]):
            future = ordered[idx + 1 :]
            side = _side(trade)
            if side == "BUY" and any(item.price < trade.price for item in future):
                buy_after_down += 1
            elif side == "SELL" and any(item.price > trade.price for item in future):
                sell_after_up += 1
    return buy_after_down, sell_after_up


def _side(trade: Trade) -> str:
    text = str(trade.side or "").upper()
    if text in {"BUY", "B"} or "买" in text or "申购" in text:
        return "BUY"
    if text in {"SELL", "S"} or "卖" in text or "赎回" in text:
        return "SELL"
    return text
