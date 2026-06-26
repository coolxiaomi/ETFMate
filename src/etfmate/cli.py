from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from etfmate.analysis.ai_advisor import (
    AI_JUDGEMENTS_FILE,
    AI_REVIEW_INPUT_FILE,
    attach_ai_judgements,
    build_ai_review_input,
    load_host_ai_judgements,
    normalize_host_ai_judgements,
)
from etfmate.analysis.data_quality import (
    build_analysis_data_quality_report,
    build_raw_data_quality_report,
    require_data_quality_pass,
)
from etfmate.analysis.grid_advisor import advise_grid
from etfmate.analysis.layered_context import build_layered_context, context_to_dict
from etfmate.analysis.recommendation import recommend
from etfmate.analysis.trade_reviewer import review_trade_periods, review_trades
from etfmate.browser import ths_account, touker_grid
from etfmate.browser.session import LoginRequiredError, WebAccessNotReadyError, require_web_access_proxy
from etfmate.market.providers import build_market_snapshot, normalize_etf_code
from etfmate.report.daily_report import write_report
from etfmate.storage.models import GridConfig, Position, Trade, WatchItem
from etfmate.storage.repository import read_json, run_id_str, write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="etfmate")
    parser.add_argument("--root", default=".", help="项目根目录")
    sub = parser.add_subparsers(dest="cmd", required=True)

    login = sub.add_parser("login")
    login.add_argument("site", choices=["ths", "touker"])

    collect = sub.add_parser("collect")
    collect.add_argument("--run-id", help="实时运行编号，默认使用当前时间")

    analyze = sub.add_parser("analyze")
    analyze.add_argument("--run-id", required=True, help="要分析的实时运行编号")

    report = sub.add_parser("report")
    report.add_argument("--run-id", help="调试/AI回写后复用的实时运行编号；不传则重新打开网页采集最新数据")

    ai_attach = sub.add_parser("ai-attach")
    ai_attach.add_argument("--run-id", required=True, help="要写入宿主 AI 综合研判的实时运行编号")
    ai_attach.add_argument("--input", required=True, help="宿主 AI 生成的 ai_judgements JSON 文件")

    run = sub.add_parser("run")
    run.add_argument("--run-id", help="实时运行编号，默认使用当前时间")

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    try:
        if args.cmd == "login":
            ths_account.login(root) if args.site == "ths" else touker_grid.login(root)
            return 0
        if args.cmd == "collect":
            run_collect(root, run_id_str(args.run_id))
            return 0
        if args.cmd == "analyze":
            run_analyze(root, args.run_id)
            return 0
        if args.cmd == "report":
            if args.run_id:
                run_report(root, args.run_id)
            else:
                run_id = run_id_str()
                require_web_access_proxy()
                run_collect(root, run_id)
                run_analyze(root, run_id)
                run_report(root, run_id)
            return 0
        if args.cmd == "ai-attach":
            run_ai_attach(root, args.run_id, Path(args.input))
            return 0
        if args.cmd == "run":
            run_id = run_id_str(args.run_id)
            require_web_access_proxy()
            run_collect(root, run_id)
            run_analyze(root, run_id)
            run_report(root, run_id)
            return 0
    except (WebAccessNotReadyError, LoginRequiredError, RuntimeError) as exc:
        print(str(exc))
        return 2
    return 1


def run_collect(root: Path, run_id: str) -> None:
    ths = ths_account.collect(root, root / "data/raw/ths" / run_id)
    _require_items(ths, "positions", "同花顺投资账本没有采集到持仓数据，已停止。请确认页面已登录且持仓表已加载。")
    touker = touker_grid.collect(root, root / "data/raw/touker" / run_id)
    _require_items(touker, "grids", "Touker 没有采集到网格数据，已停止。请确认监控中网格已加载完整。")
    write_json(root / "data/raw/ths" / run_id / "account.json", ths)
    write_json(root / "data/raw/touker" / run_id / "grids.json", touker)
    quality = build_raw_data_quality_report(ths, touker)
    write_json(root / "data/raw/market" / run_id / "data_quality.json", quality)
    require_data_quality_pass(quality, "采集")
    print(f"已采集实时数据: {run_id}")


def run_analyze(root: Path, run_id: str) -> None:
    account = read_json(root / "data/raw/ths" / run_id / "account.json", default={})
    grid_payload = read_json(root / "data/raw/touker" / run_id / "grids.json", default={})
    raw_quality = build_raw_data_quality_report(account, grid_payload)
    write_json(root / "data/raw/market" / run_id / "data_quality.json", raw_quality)
    require_data_quality_pass(raw_quality, "分析前采集")
    account_summary = (account.get("account_summary") or account.get("summary") or {}) if isinstance(account, dict) else {}
    positions = [_position(item, account_summary) for item in _items(account, "positions")]
    current_positions = [item for item in positions if (item.quantity or 0) > 0]
    trades = [_trade(item) for item in _items(account, "trades")]
    grids = [_grid(item) for item in _items(grid_payload, "grids")]
    watchlist, watchlist_filtered = _watchlist_from_account(account)
    _require_items({"positions": positions}, "positions", "缺少同花顺持仓数据，不能生成实时分析。")
    _require_items({"grids": grids}, "grids", "缺少 Touker 网格数据，不能生成实时分析。")

    universe_codes = {item.code for item in current_positions} | {item.code for item in watchlist}
    codes = sorted(universe_codes)
    snapshots = [build_market_snapshot(code) for code in codes]
    watch_by_code = {item.code: item for item in watchlist}
    for snapshot in snapshots:
        watch = watch_by_code.get(snapshot.code)
        if watch and _prefer_name(snapshot.name, watch.name, snapshot.code) == watch.name:
            snapshot.name = watch.name
    snapshots_by_code = {item.code: item for item in snapshots}
    positions_by_code = {item.code: item for item in current_positions}
    grids_by_code = {item.code: item for item in grids}
    layered_contexts = {
        item.code: build_layered_context(positions_by_code.get(item.code), grids_by_code.get(item.code), item, current_positions)
        for item in snapshots
    }
    recommendations = [
        recommend(
            positions_by_code.get(item.code),
            grids_by_code.get(item.code),
            item,
            all_positions=current_positions,
            all_markets=snapshots,
            layered_context=layered_contexts.get(item.code),
            watch_item=watch_by_code.get(item.code),
        )
        for item in snapshots
    ]
    rule_decisions = {str(item.get("code")): item.get("rule_decision") for item in recommendations}
    grid_advices = [
        advise_grid(
            grids_by_code.get(item.code),
            item,
            positions_by_code.get(item.code),
            layered_context=layered_contexts.get(item.code),
            rule_decision=rule_decisions.get(item.code),
        )
        for item in snapshots
    ]
    ai_review_input = build_ai_review_input(recommendations, grid_advices)
    ai_judgements = load_host_ai_judgements(root, run_id, recommendations)
    recommendations = attach_ai_judgements(recommendations, ai_judgements)
    run_date = _run_date(run_id)
    payload = {
        "run_id": run_id,
        "analysis_time": _analysis_time(run_id),
        "positions_count": len(current_positions),
        "grids_count": len(grids),
        "watchlist_count": len(watchlist),
        "watchlist_filtered_count": len(watchlist_filtered),
        "watchlist": watchlist,
        "watchlist_filtered_out": watchlist_filtered,
        "market_snapshots": [asdict(s) for s in snapshots],
        "layered_contexts": {code: context_to_dict(context) for code, context in layered_contexts.items()},
        "recommendations": recommendations,
        "grid_advices": grid_advices,
        "ai_review_input_path": f"data/raw/market/{run_id}/{AI_REVIEW_INPUT_FILE}",
        "ai_judgements": ai_judgements,
        "trade_review": review_trades(trades),
        "trade_reviews": review_trade_periods(trades, run_date),
    }
    quality = build_analysis_data_quality_report(account, grid_payload, payload)
    write_json(root / "data/raw/market" / run_id / "data_quality.json", quality)
    require_data_quality_pass(quality, "分析结果")
    write_json(root / "data/raw/market" / run_id / AI_REVIEW_INPUT_FILE, ai_review_input)
    write_json(root / "data/raw/market" / run_id / "snapshots.json", snapshots)
    write_json(root / "data/raw/market" / run_id / "analysis.json", payload)
    print(f"已生成实时分析结果: data/raw/market/{run_id}/analysis.json")
    print(f"已生成宿主 AI 复核输入: data/raw/market/{run_id}/{AI_REVIEW_INPUT_FILE}")


def run_report(root: Path, run_id: str) -> None:
    analysis = read_json(root / "data/raw/market" / run_id / "analysis.json", default={})
    if not analysis:
        raise RuntimeError(f"未找到分析结果: data/raw/market/{run_id}/analysis.json")
    account = read_json(root / "data/raw/ths" / run_id / "account.json", default={})
    grid_payload = read_json(root / "data/raw/touker" / run_id / "grids.json", default={})
    quality = build_analysis_data_quality_report(account, grid_payload, analysis)
    write_json(root / "data/raw/market" / run_id / "data_quality.json", quality)
    require_data_quality_pass(quality, "报告前")
    recommendations = analysis.get("recommendations", [])
    grid_advices = analysis.get("grid_advices", [])
    ai_judgements = load_host_ai_judgements(root, run_id, recommendations)
    recommendations = attach_ai_judgements(recommendations, ai_judgements)
    review = analysis.get("trade_review") or review_trades([])
    if analysis.get("trade_reviews"):
        review = {**review, "periods": analysis["trade_reviews"]}

    account_summary = (account.get("account_summary") or account.get("summary") or {}) if isinstance(account, dict) else {}
    positions_count = sum(1 for item in (_position(raw, account_summary) for raw in _items(account, "positions")) if (item.quantity or 0) > 0)
    trades_count = len(_items(account, "trades"))
    closed_count = len(_items(account, "closed_positions"))
    watchlist, watchlist_filtered = _watchlist_from_account(account)
    grids_list = _items(grid_payload, "grids")
    grids_count = len(grids_list)
    grids_active = sum(1 for g in grids_list if _bool(_pick(g, "enabled", "启用", default=True)))
    snapshots = analysis.get("market_snapshots", [])
    sources = {s.get("data_quality", "") for s in snapshots if isinstance(s, dict) and s.get("data_quality")}
    layered_contexts = analysis.get("layered_contexts") or {}
    ai_enabled_count = sum(1 for item in ai_judgements.values() if isinstance(item, dict) and item.get("enabled"))
    layer_count = len(layered_contexts)
    avg_layer_confidence = _avg_number(item.get("confidence") for item in layered_contexts.values() if isinstance(item, dict))
    layer_sources = _layer_source_summary(layered_contexts)
    data_completeness = {
        "stats": {
            "watchlist_count": len(watchlist),
            "positions_count": positions_count,
            "grids_count": grids_count,
        },
        "items": [
            {"label": "同花顺持仓", "count": str(positions_count), "source": "同花顺投资账本", "note": "完整" if positions_count else "无数据"},
            {"label": "同花顺已清仓", "count": f"{closed_count} 条", "source": "同花顺投资账本已清仓 tab", "note": "滚动采集完整" if closed_count else "无数据"},
            {
                "label": "同花顺交易记录",
                "count": f"{trades_count} 笔",
                "source": "同花顺投资账本交易记录 tab",
                "note": "覆盖本月、近三月、近半年、今年、自定义并滚动采集" if trades_count else "无数据",
            },
            {
                "label": "同花顺账户资产",
                "count": _account_summary_count(account_summary),
                "source": "同花顺投资账本持仓页",
                "note": _account_summary_note(account_summary),
            },
            {
                "label": "同花顺自选ETF池",
                "count": f"{len(watchlist)} 只，过滤 {len(watchlist_filtered)} 条",
                "source": "同花顺投资账本自选页/缓存/DOM",
                "note": "保留 ETF/LOF/场内基金，含商品、黄金、跨境/QDII 等场内基金标的；仅过滤股票、可转债、港股股票和非场内基金",
            },
            {"label": "Touker 网格", "count": f"{grids_count}（{grids_active} 监控中 + {grids_count - grids_active} 休眠）", "source": "Touker", "note": "完整" if grids_count else "无数据"},
            {"label": "行情/K 线", "count": f"{len(snapshots)} 只", "source": "; ".join(sorted(sources)) or "N/A", "note": "由 a-stock-data/本地行情适配器决策"},
            {
                "label": "七层证据",
                "count": f"{layer_count} 只，平均置信度 {_fmt_pct(avg_layer_confidence)}",
                "source": layer_sources,
                "note": "缺失层不生成假结论，只降低建议强度",
            },
            {
                "label": "AI 综合研判",
                "count": f"{len(ai_judgements)} 只，已启用 {ai_enabled_count} 只",
                "source": "宿主 AI 工具当前会话模型",
                "note": f"读取 {AI_JUDGEMENTS_FILE}；不需要额外 API Key，AI 只做证据复核",
            },
        ]
    }
    label = analysis.get("analysis_time") or _analysis_time(run_id)
    out = write_report(root / "data/reports" / f"{run_id}-etf-realtime.html", label, recommendations, grid_advices, review, data_completeness)
    print(f"已生成实时报告: {out}")


def run_ai_attach(root: Path, run_id: str, input_path: Path) -> None:
    analysis_path = root / "data/raw/market" / run_id / "analysis.json"
    analysis = read_json(analysis_path, default={})
    if not analysis:
        raise RuntimeError(f"未找到分析结果: data/raw/market/{run_id}/analysis.json")
    source = input_path if input_path.is_absolute() else (root / input_path)
    payload = read_json(source, default={})
    recommendations = analysis.get("recommendations", [])
    ai_judgements = normalize_host_ai_judgements(payload, recommendations)
    write_json(root / "data/raw/market" / run_id / AI_JUDGEMENTS_FILE, ai_judgements)
    analysis["ai_judgements"] = ai_judgements
    analysis["recommendations"] = attach_ai_judgements(recommendations, ai_judgements)
    write_json(analysis_path, analysis)
    print(f"已写入宿主 AI 综合研判: data/raw/market/{run_id}/{AI_JUDGEMENTS_FILE}")


def _require_items(payload: Any, key: str, message: str) -> None:
    if not _items(payload, key):
        raise RuntimeError(message)


def _run_date(run_id: str) -> str:
    digits = "".join(ch for ch in run_id if ch.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return datetime.now().date().isoformat()


def _analysis_time(run_id: str) -> str:
    digits = "".join(ch for ch in run_id if ch.isdigit())
    if len(digits) >= 14:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]} {digits[8:10]}:{digits[10:12]}:{digits[12:14]}"
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _items(payload: Any, key: str) -> list:
    if isinstance(payload, list):
        return [item for item in payload if item]
    if isinstance(payload, dict):
        value = payload.get(key, [])
        if isinstance(value, dict):
            value = list(value.values())
        return [item for item in value if item]
    return []


def _position(raw: dict, account_summary: dict | None = None) -> Position:
    code = normalize_etf_code(str(_pick(raw, "code", "symbol", "stockCode", "zqdm", "证券代码", "代码")))
    quantity = _num(_pick(raw, "quantity", "amount", "holdAmount", "current_amount", "持仓数量", "持有数量", "股份余额", default=0))
    market_value = _num(_pick(raw, "market_value", "marketValue", "holding_amount", "参考市值", "市值", "持仓市值", default=0))
    summary = account_summary if isinstance(account_summary, dict) else {}
    total_asset = _maybe_num(_pick(summary, "total_asset", "totalAsset", "总资产", default=None))
    total_market_value = _maybe_num(_pick(summary, "total_market_value", "totalMarketValue", "持仓市值", default=None))
    raw_account_position_pct = _maybe_num(
        _pick(
            raw,
            "fund_position_pct",
            "capital_position_pct",
            "account_position_pct",
            "asset_position_pct",
            "position_pct",
            "holding_pct",
            "hold_pct",
            "holdingPct",
            "资金仓位占比",
            "总资产占比",
            "仓位占比",
            "仓位",
            default=None,
        )
    )
    if total_asset and total_asset > 0 and market_value > 0:
        position_pct = market_value / total_asset * 100
        position_pct_source = "ths_account_total_asset"
    elif raw_account_position_pct is not None:
        position_pct = raw_account_position_pct
        position_pct_source = "ths_position_fund_pct"
    elif total_market_value and total_market_value > 0 and market_value > 0:
        position_pct = market_value / total_market_value * 100
        position_pct_source = "positions_market_value_fallback"
    else:
        position_pct = None
        position_pct_source = "missing"
    holding_pct = None
    if total_market_value and total_market_value > 0 and market_value > 0:
        holding_pct = market_value / total_market_value * 100
    return Position(
        code=code,
        name=str(_pick(raw, "name", "证券名称", "名称", default=code)),
        quantity=quantity,
        cost_price=_num(_pick(raw, "cost_price", "costPrice", "成本价", "成本", "持仓成本", default=0)),
        last_price=_num(_pick(raw, "last_price", "lastPrice", "currentPrice", "现价", "最新价", default=0)),
        market_value=market_value,
        pnl=_num(_pick(raw, "pnl", "profit", "floatProfit", "盈亏", "浮动盈亏", "持仓盈亏", default=0)),
        pnl_pct=_num(_pick(raw, "pnl_pct", "total_pnl_pct", "profitRate", "incomeRate", "盈亏率", "收益率", "持仓收益率", default=0)),
        position_pct=position_pct,
        holding_pct=holding_pct,
        position_pct_source=position_pct_source,
        account_total_asset=total_asset,
        note=_text(_pick(raw, "note", "remark", "remarks", "comment", "备注", "持仓备注", "看法", default="")),
    )


def _trade(raw: dict) -> Trade:
    code = normalize_etf_code(str(_pick(raw, "code", "symbol", "stockCode", "zqdm", "证券代码", "代码")))
    return Trade(
        trade_date=str(_pick(raw, "trade_date", "成交日期", "日期", default="")),
        trade_time=str(_pick(raw, "trade_time", "成交时间", "时间", default="")),
        code=code,
        name=str(_pick(raw, "name", "证券名称", "名称", default=code)),
        side=str(_pick(raw, "side", "买卖方向", "方向", default="")),
        price=_num(_pick(raw, "price", "dealPrice", "成交价", "价格", default=0)),
        quantity=_num(_pick(raw, "quantity", "dealAmount", "成交数量", "数量", default=0)),
        amount=_num(_pick(raw, "amount", "dealBalance", "成交金额", "金额", default=0)),
        fee=_num(_pick(raw, "fee", "手续费", default=0)),
    )


def _grid(raw: dict) -> GridConfig:
    code = normalize_etf_code(str(_pick(raw, "code", "symbol", "stockCode", "securityCode", "证券代码", "代码")))
    return GridConfig(
        code=code,
        name=str(_pick(raw, "name", "证券名称", "名称", default=code)),
        enabled=_bool(_pick(raw, "enabled", "启用", "状态", default=True)),
        status=str(_pick(raw, "status", "状态", default="")),
        base_price=_maybe_num(_pick(raw, "base_price", "basePrice", "基准价", default=None)),
        last_price=_maybe_num(_pick(raw, "last_price", "lastPrice", "currentPrice", "现价", default=None)),
        distance_from_base_pct=_maybe_num(_pick(raw, "distance_from_base_pct", "distanceFromBasePct", "距基准", default=None)),
        lower_price=_maybe_num(_pick(raw, "lower_price", "lowerPrice", "下边界", "下限", default=None)),
        upper_price=_maybe_num(_pick(raw, "upper_price", "upperPrice", "上边界", "上限", default=None)),
        grid_step_pct=_maybe_num(_pick(raw, "grid_step_pct", "gridStepPct", "stepPct", "网格间距", "间距", default=None)),
        grid_step_amount=_maybe_num(_pick(raw, "grid_step_amount", "gridStepAmount", "每格份额", default=None)),
        order_amount=_maybe_num(_pick(raw, "order_amount", "orderAmount", "每格金额", default=None)),
        order_quantity=_maybe_num(_pick(raw, "order_quantity", "orderQuantity", "entrustAmount", "委托股数", default=None)),
        buy_quantity=_maybe_num(_pick(raw, "buy_quantity", "buyQuantity", "buyAmount", "买入股数", default=None)),
        sell_quantity=_maybe_num(_pick(raw, "sell_quantity", "sellQuantity", "sellAmount", "卖出股数", default=None)),
        sell_rise_pct=_maybe_num(_pick(raw, "sell_rise_pct", "sellRisePct", "riseRate", "卖出上升", default=None)),
        sell_pullback_pct=_maybe_num(_pick(raw, "sell_pullback_pct", "sellPullbackPct", "pullbackRate", "卖出回落", default=None)),
        buy_fall_pct=_maybe_num(_pick(raw, "buy_fall_pct", "buyFallPct", "fallRate", "买入下跌", default=None)),
        buy_rebound_pct=_maybe_num(_pick(raw, "buy_rebound_pct", "buyReboundPct", "reboundRate", "买入反弹", default=None)),
        min_base_quantity=_maybe_num(_pick(raw, "min_base_quantity", "minBaseQuantity", "最小底仓", default=None)),
        max_position_quantity=_maybe_num(_pick(raw, "max_position_quantity", "maxPositionQuantity", "最大持仓", default=None)),
        last_trigger_time=str(_pick(raw, "last_trigger_time", "最近触发时间", default="")),
    )


def _watch_item(raw: dict) -> WatchItem:
    code = normalize_etf_code(str(_pick(raw, "code", "symbol", "stockCode", "securityCode", "证券代码", "代码")))
    return WatchItem(
        code=code,
        name=str(_pick(raw, "name", "stock_name", "securityName", "stockName", "证券名称", "名称", default=code)),
        source=str(_pick(raw, "source", default="ths_watchlist")),
        raw_type=_text(_pick(raw, "raw_type", "type", "securityType", default="")),
        include_reason=_text(_pick(raw, "include_reason", default="")),
        source_key=_text(_pick(raw, "source_key", default="")),
    )


def _watchlist_from_account(account: dict) -> tuple[list[WatchItem], list[dict]]:
    watch_items = _items(account, "watchlist")
    filtered = _items(account, "watchlist_filtered_out")
    clean_watch_items = [
        item
        for item in watch_items
        if isinstance(item, dict) and not ths_account.is_position_cache_source_key(item.get("source_key"))
    ]
    dirty_watch_items = [
        {**item, "filter_reason": "排除同花顺持仓缓存，不作为自选ETF池"}
        for item in watch_items
        if isinstance(item, dict) and ths_account.is_position_cache_source_key(item.get("source_key"))
    ]
    clean_filtered = [item for item in filtered if isinstance(item, dict)]
    return [_watch_item(item) for item in clean_watch_items], clean_filtered + dirty_watch_items


def _prefer_name(current: str, candidate: str, code: str) -> str:
    current_text = str(current or "").strip()
    candidate_text = str(candidate or "").strip()
    if _human_name(current_text, code):
        return current_text
    if _human_name(candidate_text, code):
        return candidate_text
    return current_text or candidate_text or code


def _human_name(value: str, code: str) -> bool:
    text = str(value or "").strip()
    if not text or text == code:
        return False
    if text.lower() in {code.lower(), f"{code}.sh", f"{code}.sz", f"sh{code}", f"sz{code}"}:
        return False
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _pick(raw: dict, *names: str, default: Any = None) -> Any:
    for name in names:
        if name in raw and raw[name] not in (None, ""):
            return raw[name]
    return default


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


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


def _avg_number(values: Any) -> float | None:
    nums = []
    for value in values:
        try:
            nums.append(float(value))
        except (TypeError, ValueError):
            continue
    return sum(nums) / len(nums) if nums else None


def _fmt_pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f}%"


def _account_summary_count(summary: dict | None) -> str:
    if not isinstance(summary, dict):
        return "未采集"
    total_asset = _maybe_num(_pick(summary, "total_asset", "totalAsset", "总资产", default=None))
    cash = _maybe_num(_pick(summary, "cash", "available_cash", "availableCash", "可用资金", default=None))
    market_value = _maybe_num(_pick(summary, "total_market_value", "totalMarketValue", "持仓市值", default=None))
    parts = []
    if total_asset is not None:
        parts.append(f"总资产 {_fmt_money(total_asset)}")
    if cash is not None:
        parts.append(f"现金 {_fmt_money(cash)}")
    if market_value is not None:
        parts.append(f"持仓市值 {_fmt_money(market_value)}")
    return "；".join(parts) if parts else "未采集到账户总资产"


def _account_summary_note(summary: dict | None) -> str:
    if not isinstance(summary, dict):
        return "缺少账户资产摘要，资金仓位口径会降级"
    source = str(summary.get("position_pct_source") or "")
    if source == "ths_account_summary" and summary.get("total_asset"):
        return "资金仓位使用单只市值 / 账户总资产计算"
    return "未拿到账户总资产时，仅能按持仓市值合计 fallback，组合仓位上限置信度下降"


def _fmt_money(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.2f}"


def _layer_source_summary(layered_contexts: dict) -> str:
    if not layered_contexts:
        return "N/A"
    statuses: dict[str, int] = {}
    for context in layered_contexts.values():
        if not isinstance(context, dict):
            continue
        for layer in context.get("layers") or []:
            status = str(layer.get("status") or "未知")
            statuses[status] = statuses.get(status, 0) + 1
    if not statuses:
        return "N/A"
    return "；".join(f"{key} {value} 层次项" for key, value in sorted(statuses.items()))


if __name__ == "__main__":
    raise SystemExit(main())
