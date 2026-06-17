from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from etfmate.analysis.grid_advisor import advise_grid
from etfmate.analysis.recommendation import recommend
from etfmate.analysis.trade_reviewer import review_trade_periods, review_trades
from etfmate.browser import ths_account, touker_grid
from etfmate.market.providers import build_market_snapshot, normalize_etf_code
from etfmate.report.daily_report import write_report
from etfmate.storage.models import GridConfig, Position, Trade
from etfmate.storage.repository import date_str, write_json
from etfmate.storage.repository import read_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="etfmate")
    parser.add_argument("--root", default=".", help="项目根目录")
    sub = parser.add_subparsers(dest="cmd", required=True)

    login = sub.add_parser("login")
    login.add_argument("site", choices=["ths", "touker"])

    collect = sub.add_parser("collect")
    collect.add_argument("--date")

    analyze = sub.add_parser("analyze")
    analyze.add_argument("--date")
    analyze.add_argument("--codes", nargs="*", default=[], help="没有持仓文件时手工指定 ETF 代码")

    report = sub.add_parser("report")
    report.add_argument("--date")

    daily = sub.add_parser("daily")
    daily.add_argument("--date")
    daily.add_argument("--codes", nargs="*", default=[], help="没有持仓文件时手工指定 ETF 代码")

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    run_date = date_str(getattr(args, "date", None))

    if args.cmd == "login":
        ths_account.login(root) if args.site == "ths" else touker_grid.login(root)
        return 0
    if args.cmd == "collect":
        run_collect(root, run_date)
        return 0
    if args.cmd == "analyze":
        run_analyze(root, run_date, args.codes)
        return 0
    if args.cmd == "report":
        run_report(root, run_date)
        return 0
    if args.cmd == "daily":
        run_collect(root, run_date)
        run_analyze(root, run_date, args.codes)
        run_report(root, run_date)
        return 0
    return 1


def run_collect(root: Path, run_date: str) -> None:
    ths = ths_account.collect(root, root / "data/raw/ths" / run_date)
    touker = touker_grid.collect(root, root / "data/raw/touker" / run_date)
    write_json(root / "data/raw/ths" / run_date / "account.json", ths)
    write_json(root / "data/raw/touker" / run_date / "grids.json", touker)


def run_analyze(root: Path, run_date: str, extra_codes: list[str] | None = None) -> None:
    account = _read_first_json(
        root / "data/raw/ths" / run_date / "account.json",
        root / "data/manual/account.json",
        default={},
    )
    grid_payload = _read_first_json(
        root / "data/raw/touker" / run_date / "grids.json",
        root / "data/manual/grids.json",
        default={},
    )
    positions = [_position(item) for item in _items(account, "positions")]
    trades = [_trade(item) for item in _items(account, "trades")]
    grids = [_grid(item) for item in _items(grid_payload, "grids")]

    codes = sorted({
        *[item.code for item in positions],
        *[item.code for item in trades],
        *[item.code for item in grids],
        *[normalize_etf_code(code) for code in (extra_codes or [])],
    })
    if not codes:
        print("未找到持仓/网格/交易 ETF。可在 data/manual/account.json 放入 positions，或运行 etfmate analyze --codes 510300。")

    snapshots = [build_market_snapshot(code) for code in codes]
    snapshots_by_code = {item.code: item for item in snapshots}
    positions_by_code = {item.code: item for item in positions}
    grids_by_code = {item.code: item for item in grids}
    recommendations = [
        recommend(positions_by_code.get(item.code), grids_by_code.get(item.code), item)
        for item in snapshots
    ]
    grid_advices = [
        advise_grid(item, snapshots_by_code[item.code])
        for item in grids
        if item.code in snapshots_by_code
    ]
    payload = {
        "date": run_date,
        "positions_count": len(positions),
        "grids_count": len(grids),
        "market_snapshots": snapshots,
        "recommendations": recommendations,
        "grid_advices": grid_advices,
        "trade_review": review_trades(trades),
        "trade_reviews": review_trade_periods(trades, run_date),
    }
    write_json(root / "data/raw/market" / run_date / "snapshots.json", snapshots)
    write_json(root / "data/raw/market" / run_date / "analysis.json", payload)
    print(f"已生成分析结果: data/raw/market/{run_date}/analysis.json")


def run_report(root: Path, run_date: str) -> None:
    analysis = read_json(root / "data/raw/market" / run_date / "analysis.json", default={})
    account = _read_first_json(
        root / "data/raw/ths" / run_date / "account.json",
        root / "data/manual/account.json",
        default={},
    )
    grid_payload = _read_first_json(
        root / "data/raw/touker" / run_date / "grids.json",
        root / "data/manual/grids.json",
        default={},
    )
    recommendations = analysis.get("recommendations", [])
    grid_advices = analysis.get("grid_advices", [])
    review = analysis.get("trade_review") or review_trades([])
    if analysis.get("trade_reviews"):
        review = {**review, "periods": analysis["trade_reviews"]}
    # Build data completeness
    positions_count = len(_items(account, "positions"))
    trades_count = len(_items(account, "trades"))
    grids_list = _items(grid_payload, "grids")
    grids_count = len(grids_list)
    grids_active = sum(1 for g in grids_list if _bool(_pick(g, "enabled", "启用", default=True)))
    snapshots = analysis.get("market_snapshots", [])
    sources = set()
    for s in snapshots:
        dq = s.get("data_quality", "") if isinstance(s, dict) else ""
        if dq:
            sources.add(dq)
    degraded = [s.get("data_quality", "") for s in snapshots if isinstance(s, dict) and "tencent" in s.get("data_quality", "")]
    data_completeness = {
        "items": [
            {"label": "同花顺持仓", "count": str(positions_count), "source": "THS 账户页", "note": "完整" if positions_count else "无数据"},
            {"label": "同花顺交易记录", "count": f"{trades_count} 笔", "source": "THS 账户页", "note": "完整" if trades_count else "无数据"},
            {"label": "Touker 网格", "count": f"{grids_count}（{grids_active} 监控中 + {grids_count - grids_active} 休眠）", "source": "Touker CDP", "note": "完整" if grids_count else "无数据"},
            {"label": "行情/K 线", "count": f"{len(snapshots)} 只", "source": "; ".join(sources) or "N/A", "note": "降级到腾讯" if degraded else "完整"},
        ]
    }
    out = write_report(root / "data/reports" / f"{run_date}-etf-review.md", run_date, recommendations, grid_advices, review, data_completeness)
    print(f"已生成报告: {out}")


def _read_first_json(*paths: Path, default: Any) -> Any:
    for path in paths:
        value = read_json(path, default=None)
        if value is not None:
            return value
    return default


def _items(payload: Any, key: str) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        value = payload.get(key, [])
        if isinstance(value, dict):
            value = list(value.values())
        return [item for item in value if isinstance(item, dict)]
    return []


def _position(raw: dict) -> Position:
    code = normalize_etf_code(str(_pick(raw, "code", "symbol", "证券代码", "代码")))
    return Position(
        code=code,
        name=str(_pick(raw, "name", "证券名称", "名称", default=code)),
        quantity=_num(_pick(raw, "quantity", "持仓数量", "持有数量", "股份余额", default=0)),
        available_quantity=_num(_pick(raw, "available_quantity", "可用数量", "可卖数量", default=0)),
        cost_price=_num(_pick(raw, "cost_price", "成本价", "成本", "持仓成本", default=0)),
        last_price=_num(_pick(raw, "last_price", "现价", "最新价", default=0)),
        market_value=_num(_pick(raw, "market_value", "市值", "持仓市值", default=0)),
        pnl=_num(_pick(raw, "pnl", "盈亏", "浮动盈亏", "持仓盈亏", default=0)),
        pnl_pct=_num(_pick(raw, "pnl_pct", "盈亏率", "收益率", "持仓收益率", default=0)),
        position_pct=_num(_pick(raw, "position_pct", "仓位占比", "仓位", default=0)),
    )


def _trade(raw: dict) -> Trade:
    code = normalize_etf_code(str(_pick(raw, "code", "symbol", "证券代码", "代码")))
    return Trade(
        trade_date=str(_pick(raw, "trade_date", "成交日期", "日期", default="")),
        trade_time=str(_pick(raw, "trade_time", "成交时间", "时间", default="")),
        code=code,
        name=str(_pick(raw, "name", "证券名称", "名称", default=code)),
        side=str(_pick(raw, "side", "买卖方向", "方向", default="")),
        price=_num(_pick(raw, "price", "成交价", "价格", default=0)),
        quantity=_num(_pick(raw, "quantity", "成交数量", "数量", default=0)),
        amount=_num(_pick(raw, "amount", "成交金额", "金额", default=0)),
        fee=_num(_pick(raw, "fee", "手续费", default=0)),
    )


def _grid(raw: dict) -> GridConfig:
    code = normalize_etf_code(str(_pick(raw, "code", "symbol", "证券代码", "代码")))
    return GridConfig(
        code=code,
        name=str(_pick(raw, "name", "证券名称", "名称", default=code)),
        enabled=_bool(_pick(raw, "enabled", "启用", "状态", default=True)),
        status=str(_pick(raw, "status", "状态", default="")),
        base_price=_maybe_num(_pick(raw, "base_price", "基准价", default=None)),
        last_price=_maybe_num(_pick(raw, "last_price", "现价", default=None)),
        distance_from_base_pct=_maybe_num(_pick(raw, "distance_from_base_pct", "距基准", default=None)),
        lower_price=_maybe_num(_pick(raw, "lower_price", "下边界", "下限", default=None)),
        upper_price=_maybe_num(_pick(raw, "upper_price", "上边界", "上限", default=None)),
        grid_step_pct=_maybe_num(_pick(raw, "grid_step_pct", "网格间距", "间距", default=None)),
        grid_step_amount=_maybe_num(_pick(raw, "grid_step_amount", "每格份额", default=None)),
        order_amount=_maybe_num(_pick(raw, "order_amount", "每格金额", default=None)),
        order_quantity=_maybe_num(_pick(raw, "order_quantity", "委托股数", default=None)),
        buy_quantity=_maybe_num(_pick(raw, "buy_quantity", "买入股数", default=None)),
        sell_quantity=_maybe_num(_pick(raw, "sell_quantity", "卖出股数", default=None)),
        sell_rise_pct=_maybe_num(_pick(raw, "sell_rise_pct", "卖出上升", default=None)),
        sell_pullback_pct=_maybe_num(_pick(raw, "sell_pullback_pct", "卖出回落", default=None)),
        buy_fall_pct=_maybe_num(_pick(raw, "buy_fall_pct", "买入下跌", default=None)),
        buy_rebound_pct=_maybe_num(_pick(raw, "buy_rebound_pct", "买入反弹", default=None)),
        min_base_quantity=_maybe_num(_pick(raw, "min_base_quantity", "最小底仓", default=None)),
        max_position_quantity=_maybe_num(_pick(raw, "max_position_quantity", "最大持仓", default=None)),
        last_trigger_time=str(_pick(raw, "last_trigger_time", "最近触发时间", default="")),
    )


def _pick(raw: dict, *names: str, default: Any = None) -> Any:
    for name in names:
        if name in raw and raw[name] not in (None, ""):
            return raw[name]
    return default


def _num(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).replace(",", "").replace("%", "").strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def _maybe_num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return _num(value)


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text not in {"false", "0", "否", "暂停", "停用", "disabled"}


if __name__ == "__main__":
    raise SystemExit(main())
