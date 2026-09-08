from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from etfmate.analysis.ai_advisor import (
    AI_JUDGEMENTS_FILE,
    AI_REVIEW_CONTRACT,
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
from etfmate.analysis.recommendation import recommend
from etfmate.analysis.account_strategy import ANALYSIS_CONTRACT, TARGETS, account_overview
from etfmate.analysis.trade_reviewer import review_trade_periods, review_trades
from etfmate.browser import ths_account, touker_grid
from etfmate.browser.session import LoginRequiredError, WebAccessNotReadyError, require_web_access_proxy
from etfmate.market.providers import build_market_snapshot, normalize_etf_code
from etfmate.report.daily_report import write_report
from etfmate.storage.models import GridConfig, Position, Trade
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
    grids = [_grid(item) for item in _items(grid_payload, "grids") if touker_grid.is_grid_condition(item)]
    _require_items({"positions": positions}, "positions", "缺少同花顺持仓数据，不能生成实时分析。")
    _require_items({"grids": grids}, "grids", "缺少 Touker 网格数据，不能生成实时分析。")

    universe_codes = {item.code for item in current_positions} | {item.code for item in grids} | set(TARGETS)
    codes = sorted(universe_codes)
    snapshots = [build_market_snapshot(code) for code in codes]
    for snapshot in snapshots:
        if snapshot.code in TARGETS:
            snapshot.name = _prefer_name(snapshot.name, TARGETS[snapshot.code]["name"], snapshot.code)
    positions_by_code = {item.code: item for item in current_positions}
    grids_by_code: dict[str, GridConfig] = {}
    for item in grids:
        existing = grids_by_code.get(item.code)
        if existing is None or (item.condition_type == "grid" and existing.condition_type != "grid"):
            grids_by_code[item.code] = item
    recommendations = [
        recommend(
            positions_by_code.get(item.code),
            grids_by_code.get(item.code),
            item,
            all_positions=current_positions,
            all_markets=snapshots,
        )
        for item in snapshots
    ]
    rule_decisions = {str(item.get("code")): item.get("rule_decision") for item in recommendations}
    grid_advices = [
        advise_grid(
            grids_by_code.get(item.code),
            item,
            positions_by_code.get(item.code),
            rule_decision=rule_decisions.get(item.code),
        )
        for item in snapshots
    ]
    ai_review_input = build_ai_review_input(recommendations, grid_advices)
    ai_judgements = load_host_ai_judgements(root, run_id, recommendations)
    recommendations = attach_ai_judgements(recommendations, ai_judgements)
    run_date = _run_date(run_id)
    payload = {
        "analysis_contract": ANALYSIS_CONTRACT,
        "run_id": run_id,
        "analysis_time": _analysis_time(run_id),
        "positions_count": len(current_positions),
        "grids_count": len(grids),
        "ignored_conditions_count": len(_items(grid_payload, "grids")) - len(grids),
        "account_overview": account_overview(recommendations, account_summary),
        "market_snapshots": [asdict(s) for s in snapshots],
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
    conditions_list = _items(grid_payload, "grids")
    grids_list = [item for item in conditions_list if touker_grid.is_grid_condition(item)]
    grids_count = len(grids_list)
    grids_active = sum(1 for g in grids_list if _bool(_pick(g, "enabled", "启用", default=True)))
    snapshots = analysis.get("market_snapshots", [])
    sources = {s.get("data_quality", "") for s in snapshots if isinstance(s, dict) and s.get("data_quality")}
    ai_enabled_count = sum(1 for item in ai_judgements.values() if isinstance(item, dict) and item.get("enabled"))
    data_completeness = {
        "account_summary": account_summary,
        "stats": {
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
            {"label": "Touker 网格", "count": f"{grids_count}（{grids_active} 监控中 + {grids_count - grids_active} 休眠）", "source": "Touker", "note": f"采集条件单 {len(conditions_list)} 条，忽略非网格 {len(conditions_list) - grids_count} 条；网格完整" if grids_count else "无网格数据"},
            {"label": "行情/K 线", "count": f"{len(snapshots)} 只", "source": "; ".join(sorted(sources)) or "N/A", "note": "由本地 ETF 行情适配器提供"},
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
    if analysis.get("analysis_contract") != ANALYSIS_CONTRACT:
        raise RuntimeError("分析契约已更新，请重新 analyze 后再复核。")
    source = input_path if input_path.is_absolute() else (root / input_path)
    payload = read_json(source, default={})
    if not isinstance(payload, dict) or payload.get("review_contract") != AI_REVIEW_CONTRACT:
        raise RuntimeError("AI 输入契约已更新，请按本次 ai_review_input.json 重新生成复核文件")
    recommendations = analysis.get("recommendations", [])
    ai_judgements = normalize_host_ai_judgements(payload, recommendations)
    write_json(root / "data/raw/market" / run_id / AI_JUDGEMENTS_FILE, payload)
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
    condition_type = str(_pick(raw, "condition_type", "类型", default="grid") or "grid").strip().lower()
    return GridConfig(
        code=code,
        name=str(_pick(raw, "name", "证券名称", "名称", default=code)),
        enabled=_bool(_pick(raw, "enabled", "启用", "状态", default=True)),
        condition_type="sell_only" if condition_type in {"sell_only", "sell-on", "单边卖出", "分批出货"} else "grid",
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
        min_base_quantity=_optional_grid_limit(_pick(raw, "min_base_quantity", "minBaseQuantity", "最小底仓", default=None)),
        max_position_quantity=_optional_grid_limit(_pick(raw, "max_position_quantity", "maxPositionQuantity", "最大持仓", "最大底仓", default=None)),
        last_trigger_time=str(_pick(raw, "last_trigger_time", "最近触发时间", default="")),
    )


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


def _optional_grid_limit(value: Any) -> float | None:
    if value is None or str(value).strip() in {"", "--", "-", "未设置", "不限制", "不限"}:
        return None
    from math import isfinite
    quantity = float(str(value).replace(",", "").strip())
    if not isfinite(quantity) or quantity < 0 or not quantity.is_integer():
        raise ValueError("网格底仓上下限必须是非负整数或未设置")
    return quantity


def _maybe_num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return _num(value)


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text not in {"false", "0", "否", "暂停", "停用", "disabled"}


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


if __name__ == "__main__":
    raise SystemExit(main())
