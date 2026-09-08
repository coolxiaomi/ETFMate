from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any

from etfmate.browser.touker_grid import is_grid_condition
from etfmate.analysis.account_strategy import ANALYSIS_CONTRACT, TARGETS, role_for


class DataQualityError(RuntimeError):
    pass


def build_raw_data_quality_report(account: dict[str, Any], grid_payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}
    _validate_ths_account(account, errors, warnings, metrics)
    _validate_touker_grids(grid_payload, errors, warnings, metrics)
    return {**_report(errors, warnings, metrics), "scope": "RAW_COLLECTION", "formal_report_ready": False}


def build_analysis_data_quality_report(
    account: dict[str, Any],
    grid_payload: dict[str, Any],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    raw = build_raw_data_quality_report(account, grid_payload)
    errors = list(raw.get("fatal_errors") or [])
    warnings = list(raw.get("warnings") or [])
    metrics = dict(raw.get("metrics") or {})
    _validate_analysis(account, grid_payload, analysis, errors, warnings, metrics)
    return {**_report(errors, warnings, metrics), "scope": "ANALYSIS_INPUTS_AND_RULES", "formal_report_ready": False}


def build_report_data_quality_report(
    account: dict[str, Any], grid_payload: dict[str, Any], analysis: dict[str, Any],
    ai_payload: Any, *, now: datetime | None = None,
) -> dict[str, Any]:
    from etfmate.analysis.ai_advisor import ai_review_validation_errors, review_input_for_analysis

    base = build_analysis_data_quality_report(account, grid_payload, analysis)
    errors = list(base["fatal_errors"])
    warnings = list(base["warnings"])
    metrics = dict(base["metrics"])
    _validate_formal_collection_evidence(account, errors)
    if isinstance(analysis, dict):
        _validate_report_times(analysis, errors, now)
    if not base["fatal_errors"]:
        expected_input = review_input_for_analysis(account, grid_payload, analysis)
        if not analysis.get("run_id") or not analysis.get("ai_review_id"):
            errors.append("分析缺少本次运行与复核标识，请重新 analyze。")
        if analysis.get("ai_review_input_fingerprint") != expected_input["input_fingerprint"]:
            errors.append("原始账户、行情或行动计划已变化，当前分析与复核输入不一致，请重新分析及复核。")
        errors.extend(ai_review_validation_errors(
            ai_payload, analysis.get("recommendations") or [], expected_input, require_pass=True,
        ))
    rows = ai_payload.get("items") if isinstance(ai_payload, dict) else []
    rows = rows if isinstance(rows, list) else []
    metrics["ai_review_count"] = len(rows)
    metrics["ai_review_pass_count"] = sum(
        1 for row in rows if isinstance(row, dict) and row.get("review_status") == "PASS"
        and not row.get("conflicts") and row.get("final_bias") == "保持规则建议"
    )
    result = _report(errors, warnings, metrics)
    return {**result, "scope": "FORMAL_REPORT", "formal_report_ready": result["status"] == "PASS"}


def _validate_formal_collection_evidence(account: dict, errors: list[str]) -> None:
    """Old captures remain useful for analysis, but cannot prove a formal report."""
    from etfmate.browser.ths_account import _collection_consistency

    trades = account.get("trade_snapshots") or {}
    scopes = [("已清仓", "全部", account.get("closed_snapshot"))]
    scopes.extend(("交易记录", label, trades.get(label) if isinstance(trades, dict) else None)
                  for label in ("本月", "近三月", "近半年", "今年", "自定义"))
    for tab, label, snapshot in scopes:
        selection = snapshot.get("range_filter") if isinstance(snapshot, dict) else None
        valid = (isinstance(selection, dict) and selection.get("contract") == "ths_date_range_v1"
                 and selection.get("requested") == label and selection.get("selected") == label
                 and selection.get("verified") is True and snapshot.get("tab_label") == tab
                 and snapshot.get("tab_clicked") is True)
        dates = selection.get("custom_dates") if isinstance(selection, dict) else None
        if valid and label == "自定义":
            try:
                parsed = [datetime.strptime(value, "%Y-%m-%d").date() for value in dates]
                valid = (isinstance(dates, list) and len(dates) == 2 and parsed[0] <= parsed[1]
                         and all(day.isoformat() == value for day, value in zip(parsed, dates))
                         and selection.get("query_submitted") is True)
            except (TypeError, ValueError):
                valid = False
        for boundary in ("before", "after"):
            state = selection.get(boundary) if isinstance(selection, dict) else None
            count = state.get("row_count") if isinstance(state, dict) else None
            has_rows = _positive_number(count) and int(count) == count
            valid = (valid and isinstance(state, dict) and state.get("selected") == label
                     and state.get("ready") is True and state.get("loading") is False
                     and (has_rows or state.get("empty") is True)
                     and (label != "自定义" or state.get("custom_dates") == dates))
        if not valid:
            errors.append(f"正式报告缺少同花顺{tab}「{label}」实际范围选中与列表就绪证据；请重新采集，旧批次仅用于开发分析。")

    start, end = account.get("snapshot"), account.get("end_snapshot")
    consistency = account.get("collection_consistency")
    if (not isinstance(start, dict) or not isinstance(end, dict)
            or start.get("scroll_complete") is not True or end.get("scroll_complete") is not True
            or not isinstance(consistency, dict)):
        errors.append("正式报告缺少完整持仓首尾快照或 collection_consistency 对账证据；请重新采集，不能仅重新分析旧批次。")
        return
    try:
        expected = _collection_consistency(start, end)
    except (AttributeError, KeyError, TypeError, ValueError):
        errors.append("正式报告无法从持仓首尾快照重算数量与现金一致性，请重新采集。")
        return
    if expected.get("status") != "PASS" or not _same_structure(consistency, expected):
        errors.append("正式报告采集首尾数量或现金不一致，或 collection_consistency 与原始快照重算不一致；请重新采集。")
        return
    quantities = {
        _code(_pick(row, "code", "symbol", "stockCode", "zqdm", "证券代码", "代码")):
        _num(_pick(row, "quantity", "amount", "holdAmount", "current_amount", "持仓数量", "持有数量", "股份余额"))
        for row in _items(account, "positions")
    }
    summary = account.get("account_summary") or {}
    cash = summary.get("cash") if isinstance(summary, dict) else None
    try:
        parsed_cash = float(str(cash).replace(",", ""))
    except (TypeError, ValueError):
        parsed_cash = None
    if (not _same_structure(quantities, expected["start"]["quantities"])
            or parsed_cash is None or not isfinite(parsed_cash) or isinstance(cash, bool)
            or parsed_cash != expected["start"]["cash"]):
        errors.append("正式报告账户持仓数量或现金与已对账的首尾采集快照不一致，请重新采集。")


def _validate_report_times(analysis: dict, errors: list[str], now: datetime | None) -> None:
    china = timezone(timedelta(hours=8))
    current = now or datetime.now(china)
    current = current.replace(tzinfo=china) if current.tzinfo is None else current.astimezone(china)

    def parse_time(value: Any) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed.replace(tzinfo=china) if parsed.tzinfo is None else parsed.astimezone(china)
        except (ValueError, TypeError):
            return None

    analyzed = parse_time(analysis.get("analysis_time"))
    if analyzed is None or analyzed.date() != current.date() or analyzed > current + timedelta(minutes=1):
        errors.append("分析时间缺失、不是报告当天或位于未来；历史分析不能生成当前正式报告。")
    for snapshot in _items(analysis, "market_snapshots"):
        code = snapshot.get("code")
        quote = parse_time(snapshot.get("quote_time"))
        signal = parse_time(snapshot.get("signal_date"))
        if quote is None:
            errors.append(f"行情快照 {code} 缺少真实 quote_time，不能确认数据时间。")
        elif (quote > current + timedelta(minutes=1)
              or (analyzed is not None and quote > analyzed + timedelta(minutes=1))
              or current - quote > timedelta(days=14)):
            errors.append(f"行情快照 {code} 报价时间位于未来或明显陈旧，需重新获取行情。")
        if snapshot.get("signal_is_complete") is not True or snapshot.get("signal_volume_basis") != "completed_daily":
            errors.append(f"行情快照 {code} 未证明技术指标来自已完成日线。")
        if signal is None or quote is None:
            errors.append(f"行情快照 {code} 缺少可核对的完整日线日期。")
        elif (signal.date() > quote.date() or (quote.date() - signal.date()).days > 14
              or (signal.date() == quote.date() and (quote.hour, quote.minute) < (15, 0))):
            errors.append(f"行情快照 {code} 指标日与报价时间不一致，不能使用未来、陈旧或未收盘日线。")


def require_data_quality_pass(report: dict[str, Any], stage: str) -> None:
    if str(report.get("status")) == "PASS":
        return
    errors = [str(item) for item in report.get("fatal_errors") or [] if item]
    detail = "\n".join(f"- {item}" for item in errors[:20])
    more = len(errors) - 20
    if more > 0:
        detail += f"\n- 另有 {more} 个数据质量问题，详见 data_quality.json"
    raise DataQualityError(f"{stage} 数据质量未通过，已停止生成最终分析/报告。\n{detail}")


def _validate_ths_account(account: dict[str, Any], errors: list[str], warnings: list[str], metrics: dict[str, Any]) -> None:
    if not isinstance(account, dict):
        errors.append("同花顺 account.json 不是有效 JSON 对象。")
        return
    positions = _items(account, "positions")
    current_positions = [item for item in positions if _num(_pick(item, "quantity", "amount", "holdAmount", "current_amount", "持仓数量", "持有数量", "股份余额")) > 0]
    trades = _items(account, "trades")
    closed_positions = _items(account, "closed_positions")
    summary_payload = account.get("account_summary") or account.get("summary")
    summary = summary_payload if isinstance(summary_payload, dict) else {}
    metrics.update(
        {
            "positions_count": len(current_positions),
            "trades_count": len(trades),
            "closed_positions_count": len(closed_positions),
        }
    )
    if not current_positions:
        errors.append("同花顺当前持仓为空或持仓数量均为 0，不能确认真实账户持仓。")
    if summary and _num(_pick(summary, "total_asset", "totalAsset", "总资产")) <= 0:
        errors.append("同花顺账户总资产缺失，资金仓位、组合上限和报告口径不能确认。")
    if not summary:
        errors.append("同花顺账户资产摘要缺失，不能确认资金仓位口径。")

    for idx, item in enumerate(current_positions, start=1):
        code = _code(_pick(item, "code", "symbol", "stockCode", "zqdm", "证券代码", "代码"))
        label = code or f"第 {idx} 条持仓"
        _require_code(item, errors, f"同花顺持仓 {label}")
        for field_label, names in (
            ("名称", ("name", "证券名称", "名称")),
            ("持仓数量", ("quantity", "amount", "holdAmount", "current_amount", "持仓数量", "持有数量", "股份余额")),
            ("持仓市值", ("market_value", "marketValue", "holding_amount", "参考市值", "市值", "持仓市值")),
            ("现价", ("last_price", "lastPrice", "currentPrice", "现价", "最新价")),
            ("成本价", ("cost_price", "costPrice", "成本价", "成本", "持仓成本")),
        ):
            if _missing_required(item, names):
                errors.append(f"同花顺持仓 {label} 缺少 {field_label} 字段。")
        if not _has_any_key(item, ("note", "remark", "remarks", "comment", "备注", "持仓备注", "看法")):
            warnings.append(f"同花顺持仓 {label} 未识别到备注/看法字段；如页面确有该列，本次采集可能不完整。")

    if not any(_has_any_key(item, ("note", "remark", "remarks", "comment", "备注", "持仓备注", "看法")) for item in current_positions):
        errors.append("同花顺持仓备注/看法列整体未识别，采集字段不完整。")

    _require_scroll_complete(account.get("snapshot"), "同花顺持仓列表", errors)
    _require_scroll_complete(account.get("closed_snapshot"), "同花顺已清仓列表", errors)
    trade_snapshots = account.get("trade_snapshots")
    expected_trade_tabs = ("本月", "近三月", "近半年", "今年", "自定义")
    if not isinstance(trade_snapshots, dict):
        errors.append("同花顺交易记录 tab 快照缺失。")
    else:
        for tab in expected_trade_tabs:
            if tab not in trade_snapshots:
                errors.append(f"同花顺交易记录缺少 {tab} tab 快照。")
            else:
                _require_scroll_complete(trade_snapshots.get(tab), f"同花顺交易记录 {tab}", errors)



def _validate_touker_grids(grid_payload: dict[str, Any], errors: list[str], warnings: list[str], metrics: dict[str, Any]) -> None:
    if not isinstance(grid_payload, dict):
        errors.append("Touker grids.json 不是有效 JSON 对象。")
        return
    conditions = _items(grid_payload, "grids")
    grids = [item for item in conditions if is_grid_condition(item)]
    expected = grid_payload.get("expected_count")
    metrics["touker_conditions_count"] = len(conditions)
    metrics["touker_ignored_conditions_count"] = len(conditions) - len(grids)
    metrics["touker_grids_count"] = len(grids)
    metrics["touker_expected_count"] = expected
    if not grids:
        errors.append("Touker 网格列表为空，不能生成网格分析。")
    if expected in (None, ""):
        errors.append("Touker 未识别到页面“监控中(N)”数量，无法确认网格是否采齐。")
    elif _num(expected) > len(conditions):
        errors.append(f"Touker 条件单未采齐：页面显示监控中 {int(_num(expected))} 条，当前只识别到 {len(conditions)} 条。")
    ignored_codes = [_code(_pick(item, "code", "symbol", "证券代码", "代码")) for item in conditions if not is_grid_condition(item)]
    if ignored_codes:
        warnings.append(f"按当前范围忽略 {len(ignored_codes)} 条非网格条件单：{', '.join(ignored_codes)}；仍保留原始采集记录并参与数量对账。")
    snapshot = grid_payload.get("snapshot")
    if isinstance(snapshot, dict):
        if "scroll_complete" not in snapshot:
            errors.append("Touker 网格快照缺少滚动完整性标记。")
        elif snapshot.get("scroll_complete") is False:
            errors.append(f"Touker 网格滚动列表未确认到底：{snapshot.get('scroll_stop_reason') or '未知原因'}。")

    for idx, item in enumerate(grids, start=1):
        code = _code(_pick(item, "code", "symbol", "stockCode", "securityCode", "证券代码", "代码"))
        label = code or f"第 {idx} 条网格"
        _require_code(item, errors, f"Touker 网格 {label}")
        grid_fields = (
            ("名称", ("name", "证券名称", "名称")),
            ("基准价", ("base_price", "basePrice", "基准价")),
            ("现价", ("last_price", "lastPrice", "currentPrice", "现价")),
            ("买入下跌", ("buy_fall_pct", "buyFallPct", "fallRate", "买入下跌")),
            ("买入反弹", ("buy_rebound_pct", "buyReboundPct", "reboundRate", "买入反弹")),
            ("卖出上升", ("sell_rise_pct", "sellRisePct", "riseRate", "卖出上升")),
            ("卖出回落", ("sell_pullback_pct", "sellPullbackPct", "pullbackRate", "卖出回落")),
        )
        for field_label, names in grid_fields:
            if _missing_required(item, names):
                errors.append(f"Touker 网格 {label} 缺少 {field_label} 字段。")
        if all(_missing_required(item, names) for names in (("order_quantity", "orderQuantity", "entrustAmount", "委托股数"), ("buy_quantity", "buyQuantity", "buyAmount", "买入股数"), ("sell_quantity", "sellQuantity", "sellAmount", "卖出股数"))):
            warnings.append(f"Touker 网格 {label} 未识别到单笔买卖数量；无法沿用现有数量生成建议。")
        # Inventory bounds are optional settings, not missing execution evidence.
        limits = {}
        for field, names in (
            ("最小底仓", ("min_base_quantity", "minBaseQuantity", "最小底仓")),
            ("最大持仓", ("max_position_quantity", "maxPositionQuantity", "最大持仓", "最大底仓")),
        ):
            value = _pick(item, *names)
            if value is None or str(value).strip() in {"", "--", "-", "未设置", "不限制", "不限"}:
                continue
            try:
                quantity = float(str(value).replace(",", ""))
                if not isfinite(quantity) or quantity < 0 or not quantity.is_integer():
                    raise ValueError
                limits[field] = quantity
            except (ValueError, TypeError):
                errors.append(f"Touker 网格 {label} 的{field}不是有效的非负整数。")
        if "最小底仓" in limits and "最大持仓" in limits and limits["最小底仓"] > limits["最大持仓"]:
            errors.append(f"Touker 网格 {label} 的最小底仓大于最大持仓。")


def _validate_analysis(account: dict[str, Any], grid_payload: dict[str, Any], analysis: dict[str, Any], errors: list[str], warnings: list[str], metrics: dict[str, Any]) -> None:
    if not isinstance(analysis, dict):
        errors.append("analysis.json 不是有效 JSON 对象。")
        return
    if analysis.get("analysis_contract") != ANALYSIS_CONTRACT:
        errors.append("分析契约已更新，旧分析未执行当前账户角色、清仓不亏规则及账本资金库存推导；请重新执行 analyze 和宿主 AI 复核后生成报告。")
    _validate_ledger_plans(account, grid_payload, analysis, errors)
    current_codes = {_code(_pick(item, "code", "symbol", "stockCode", "zqdm", "证券代码", "代码")) for item in _items(account, "positions") if _num(_pick(item, "quantity", "amount", "holdAmount", "current_amount", "持仓数量", "持有数量", "股份余额")) > 0}
    grid_codes = {_code(_pick(item, "code", "symbol", "stockCode", "securityCode", "证券代码", "代码")) for item in _items(grid_payload, "grids") if is_grid_condition(item)}
    universe_codes = {code for code in current_codes | grid_codes | set(TARGETS) if code}
    if any(key in analysis for key in ("watchlist", "t_grid_advices", "watchlist_count")):
        errors.append("当前分析不得包含已停用的自选池或T网格产物。")
    snapshots = _items(analysis, "market_snapshots")
    recommendations = _items(analysis, "recommendations")
    grid_advices = _items(analysis, "grid_advices")
    snapshot_codes = {_code(item.get("code")) for item in snapshots if isinstance(item, dict)}
    recommendation_codes = {_code(item.get("code")) for item in recommendations if isinstance(item, dict)}
    grid_advice_codes = {_code(item.get("code")) for item in grid_advices if isinstance(item, dict)}
    metrics.update(
        {
            "analysis_universe_count": len(universe_codes),
            "market_snapshots_count": len(snapshots),
            "recommendations_count": len(recommendations),
            "grid_advices_count": len(grid_advices),
        }
    )
    for label, rows, codes in (("行情", snapshots, snapshot_codes), ("建议", recommendations, recommendation_codes), ("网格", grid_advices, grid_advice_codes)):
        if codes - universe_codes:
            errors.append(f"{label}含非当前研究范围代码：{sorted(codes - universe_codes)}。")
        if len(rows) != len(codes):
            errors.append(f"{label}存在重复代码。")
    missing_snapshots = sorted(universe_codes - snapshot_codes)
    if missing_snapshots:
        errors.append(f"行情快照缺少 universe 代码：{', '.join(missing_snapshots)}。")
    missing_recommendations = sorted(universe_codes - recommendation_codes)
    if missing_recommendations:
        errors.append(f"规则建议缺少 universe 代码：{', '.join(missing_recommendations)}。")
    missing_grid_advices = sorted(universe_codes - grid_advice_codes)
    if missing_grid_advices:
        errors.append(f"网格建议缺少 universe 代码：{', '.join(missing_grid_advices)}。")
    for item in snapshots:
        if not isinstance(item, dict):
            continue
        code = _code(item.get("code")) or "未知代码"
        quality = str(item.get("data_quality") or "")
        if "missing" in quality or "error" in quality:
            errors.append(f"行情快照 {code} 数据源异常：{quality}。")
        for field_label, names in (
            ("最新价", ("last_price", "lastPrice", "最新价")),
            ("成交额", ("amount", "成交额")),
            ("MA20", ("ma20",)),
            ("MA60", ("ma60",)),
            ("BOLL 中轨", ("boll_mid",)),
            ("ATR14%", ("atr14_pct",)),
            ("RSI6", ("rsi6",)),
        ):
            if _missing_required(item, names):
                errors.append(f"行情快照 {code} 缺少 {field_label} 字段。")
        if _num(item.get("kline_days")) <= 0:
            errors.append(f"行情快照 {code} 缺少 K 线天数字段。")
    for item in recommendations:
        if isinstance(item, dict) and not isinstance(item.get("rule_decision"), dict):
            errors.append(f"规则建议 {_code(item.get('code')) or '未知代码'} 缺少 rule_decision。")
        elif isinstance(item, dict):
            rule = item["rule_decision"]
            code = _code(item.get("code"))
            snapshot = next((row for row in snapshots if row.get("code") == code), {})
            for field in ("last_price", "quote_time", "signal_date", "signal_close", "signal_is_complete", "signal_volume_basis"):
                if field in snapshot and not _same_value(item.get(field), snapshot[field]):
                    errors.append(f"规则建议 {code} 的 {field} 与本次行情快照不一致。")
            for field in ("action", "position_action", "target_position_pct", "sell_policy"):
                if field in rule and item.get(field) != rule[field]:
                    errors.append(f"规则建议 {code} 的 {field} 与结构化决策不一致。")
            if rule.get("strategy_role") != role_for(code)["role"] or item.get("strategy_role") != rule.get("strategy_role"):
                errors.append(f"规则建议 {code} 角色与当前目标不一致，需重新分析。")
            if (rule.get("sell_policy") or {}).get("rule") != "NO_LOSS_ON_LIQUIDATION":
                errors.append(f"规则建议 {code} 缺少当前清仓规则，需重新分析。")
            from etfmate.analysis.technical_assessment import TECHNICAL_CONTRACT
            technical = rule.get("technical_assessment")
            if (not isinstance(technical, dict) or technical.get("contract") != TECHNICAL_CONTRACT
                    or not all(key in technical for key in ("status", "summary", "evidence", "conflicts", "missing_fields", "buy_condition", "sell_condition"))
                    or technical.get("buy_gate") not in {"CONDITIONAL", "WAIT_CONFIRMATION"}
                    or item.get("technical_assessment") != technical):
                errors.append(f"规则建议 {code} 缺少一致的综合技术依据，需重新分析。")
            elif technical["buy_gate"] == "WAIT_CONFIRMATION" and not set(rule.get("blocked_actions") or []) & {"买入", "全部"}:
                errors.append(f"规则建议 {code} 技术条件未确认却未限制买入。")
    for item in grid_advices:
        code = item.get("code")
        rec = next((row for row in recommendations if row.get("code") == code), {})
        technical = rec.get("technical_assessment")
        _validate_price_and_partial_plan(item, rec, errors)
        if not isinstance(technical, dict) or item.get("technical_assessment") != technical:
            errors.append(f"网格建议 {code} 综合依据与规则不一致，需重新分析。")
        elif technical.get("buy_gate") == "WAIT_CONFIRMATION" and (item.get("candidate_buy_quantity") or item.get("conditional_buyback_quantity") or item.get("grid_execution_status") != "DO_NOT_ENABLE"):
            errors.append(f"网格建议 {code} 绕过未确认的技术买入条件。")
        if "parameter_plan" not in item or item.get("grid_execution_status") not in {"DO_NOT_ENABLE", "PENDING_VERIFICATION"}:
            errors.append(f"网格建议 {code} 缺少双向参数与整单状态，需重新分析。")
            continue
        plan = item.get("parameter_plan")
        if plan is None:
            if item.get("grid_execution_status") != "DO_NOT_ENABLE":
                errors.append(f"网格建议 {code} 参数不全，必须整单停用。")
            continue
        if not isinstance(plan, dict):
            errors.append(f"网格建议 {code} 双向参数格式错误。")
            continue
        if not isinstance(item.get("parameter_basis"), dict) or item["parameter_basis"].get("technical_status") != (technical or {}).get("status"):
            errors.append(f"网格建议 {code} 缺少综合参数依据，需重新分析。")
        for field in ("buy_quantity", "sell_quantity", "buy_fall_pct", "buy_rebound_pct", "sell_rise_pct", "sell_pullback_pct"):
            value = plan.get(field)
            valid = isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value > 0
            if field.endswith("quantity"):
                valid = valid and value >= 100 and value % 100 == 0
            elif field in {"buy_fall_pct", "sell_pullback_pct"}:
                valid = valid and value < 100
            if not valid:
                errors.append(f"网格建议 {code} 双向参数 {field} 无效。")
    _validate_decision_review(account, analysis, errors)
    if not analysis.get("ai_review_input_path"):
        warnings.append("analysis.json 未记录 ai_review_input_path。")


def _same_structure(left: Any, right: Any) -> bool:
    """Compare every derived field, without accepting a boolean as a quantity."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, dict) or isinstance(right, dict):
        return (isinstance(left, dict) and isinstance(right, dict) and left.keys() == right.keys()
                and all(_same_structure(left[key], right[key]) for key in left))
    if isinstance(left, list) or isinstance(right, list):
        return (isinstance(left, list) and isinstance(right, list) and len(left) == len(right)
                and all(_same_structure(a, b) for a, b in zip(left, right)))
    return _same_value(left, right)


def _validate_decision_review(account: dict, analysis: dict, errors: list[str]) -> None:
    required = ("decision_review", "action_plans")
    for field in required:
        if not isinstance(analysis.get(field), dict):
            errors.append(f"分析缺少有效的 v10 {field}，需重新分析并复核。")
    if any(not isinstance(analysis.get(field), dict) for field in required):
        return
    recommendations, grids = analysis.get("recommendations"), analysis.get("grid_advices")
    summary = account.get("account_summary") or account.get("summary") or {}
    funding = analysis.get("funding_plan")
    if (not isinstance(recommendations, list) or not isinstance(grids, list)
            or not all(isinstance(row, dict) for row in recommendations + grids)
            or not isinstance(summary, dict) or not isinstance(funding, dict)):
        errors.append("无法重算 decision_review 和 action_plans：账户或分析来源格式错误。")
        return
    from etfmate.analysis.action_plan import describe_action_plan
    from etfmate.analysis.decision_review import build_decision_review

    try:
        expected = build_decision_review(recommendations, grids, summary, funding)
        by_code = {row["code"]: row for row in grids}
        expected_actions = {row["code"]: describe_action_plan(row, by_code.get(row["code"], {}))
                            for row in recommendations}
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError):
        errors.append("无法重算 decision_review 和 action_plans：行动、数量或账户来源字段无效。")
        return
    if not _same_structure(analysis["decision_review"], expected):
        errors.append("分析 decision_review 与本批账户、数量和行动重算结果不一致，需重新分析并复核。")
    if not _same_structure(analysis["action_plans"], expected_actions):
        errors.append("分析 action_plans 与本批行动、份额和后续复评安排不一致，需重新分析并复核。")


def _validate_ledger_plans(account: dict, grid_payload: dict, analysis: dict, errors: list[str]) -> None:
    from etfmate.analysis.action_plan import describe_action_plan
    from etfmate.analysis.funding_plan import build_funding_plan
    from etfmate.analysis.inventory_plan import build_inventory_plan

    funding = analysis.get("funding_plan")
    inventory = analysis.get("inventory_plan")
    if not isinstance(funding, dict):
        errors.append("分析缺少 v9 funding_plan 资金推导，不能仅修改旧版本号；请重新分析。")
    if not isinstance(inventory, dict):
        errors.append("分析缺少 v9 inventory_plan 库存推导，不能仅修改旧版本号；请重新分析。")
    try:
        expected_funding = build_funding_plan(account, _items(grid_payload, "grids"))
    except (AttributeError, TypeError, ValueError):
        errors.append("原始账户或条件单字段无效，无法重算 funding_plan。")
        expected_funding = None
    if expected_funding is not None and isinstance(funding, dict) and not _same_structure(funding, expected_funding):
        errors.append("分析 funding_plan 与原始账本现金、资产和全部条件单重算不一致；监控金额不能冒充冻结资金。")
    try:
        as_of_date = datetime.fromisoformat(str(analysis.get("analysis_time")).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        errors.append("分析时间 analysis_time 缺失或无效，无法确定库存推导日期。")
        as_of_date = None
    expected_inventory = None
    if as_of_date is not None:
        try:
            expected_inventory = build_inventory_plan(account, as_of_date)
        except (AttributeError, TypeError, ValueError):
            errors.append("原始账本字段无效，无法重算 inventory_plan。")
        if (expected_inventory is not None and isinstance(inventory, dict)
                and not _same_structure(inventory, expected_inventory)):
            errors.append("分析 inventory_plan 与原始账本及分析时间日期重算不一致，需重新分析。")

    recommendations = {_code(row.get("code")): row for row in _items(analysis, "recommendations")}
    no_buy_capacity = expected_funding is not None and expected_funding.get("buy_capacity_under_cap") == 0
    for grid in _items(analysis, "grid_advices"):
        code = _code(grid.get("code"))
        expected = expected_inventory.get(code, {}) if expected_inventory is not None else None
        if expected is not None and not _same_structure(grid.get("inventory"), expected):
            errors.append(f"网格建议 {code} 的 inventory 与账本 inventory_plan 不一致。")
        if expected is not None:
            eligible = expected.get("sellable_quantity")
            partial = grid.get("partial_sell_plan")
            sell_quantities = {field: grid.get(field) for field in ("candidate_sell_quantity", "suggested_sell_quantity")}
            if isinstance(partial, dict):
                sell_quantities["partial_sell_plan.candidate_quantity"] = partial.get("candidate_quantity")
            for field, quantity in sell_quantities.items():
                if quantity is not None and (not _positive_number(quantity) or not _positive_number(eligible) or quantity > eligible):
                    errors.append(f"网格建议 {code} 的 {field} 超出账本可卖量或可卖量未确定。")
        if no_buy_capacity:
            # Parameter drafts describe possible future settings, not current purchases.
            for field in ("candidate_buy_quantity", "conditional_buyback_quantity", "suggested_buy_quantity"):
                if grid.get(field) is not None:
                    errors.append(f"网格建议 {code} 在组合可买额度为0时仍输出 {field} 当前买入数量。")
            rec = recommendations.get(code, {})
            if isinstance(rec.get("rule_decision"), dict) and isinstance(grid.get("parameter_plan"), (dict, type(None))):
                try:
                    action = describe_action_plan(rec, grid)
                except (AttributeError, KeyError, TypeError, ValueError):
                    errors.append(f"网格建议 {code} 无法生成一致的当前行动计划。")
                else:
                    if action.get("buy_quantity") is not None:
                        errors.append(f"网格建议 {code} 在组合可买额度为0时仍输出当前行动买入数量。")


def _same_value(left: Any, right: Any) -> bool:
    # Missing supplemental indicators may use NaN; they are never replaced with zero.
    if isinstance(left, float) and isinstance(right, float) and left != left and right != right:
        return True
    return left == right


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value > 0


def _validate_confirmation_prices(
    grid: dict, triggers: dict[str, float], percentages: dict[str, float], errors: list[str],
) -> dict[str, float]:
    from decimal import Decimal
    from etfmate.analysis.price_ticks import CONFIRMATION_PRICE_BASIS, PRICE_TICK, confirmation_price

    path, code = grid["price_plan"], grid.get("code")
    if path.get("confirmation_price_basis") != CONFIRMATION_PRICE_BASIS or path.get("price_tick") != float(PRICE_TICK):
        errors.append(f"网格建议 {code} 缺少确认价假设或0.001交易档位契约，需重新分析。")
    examples = {}
    for side in ("buy", "sell"):
        theoretical, tick = confirmation_price(triggers[side], percentages[side], side)
        field = f"{side}_confirmation_theoretical_price"
        if path.get(field) != format(theoretical, "f"):
            errors.append(f"网格建议 {code} 的 {field} 缺失或不等于精确理论边界，需重新分析。")
        examples[f"{side}_confirmation_example"] = float(tick)
        for field in (f"{side}_confirmation_tick_price", f"{side}_confirmation_example"):
            value = path.get(field)
            if not _positive_number(value):
                errors.append(f"网格建议 {code} 的 {field} 缺少有效确认档位，需重新分析。")
                continue
            price, extreme = Decimal(str(value)), Decimal(str(triggers[side]))
            movement = price - extreme if side == "buy" else extreme - price
            if price % PRICE_TICK != 0:
                errors.append(f"网格建议 {code} 的 {field} 不在0.001交易档位。")
            if movement * 100 < extreme * Decimal(str(percentages[side])):
                errors.append(f"网格建议 {code} 的 {field} 未满足确认比例，不能提前确认。")
            if price != tick:
                errors.append(f"网格建议 {code} 的 {field} 不是首个满足确认比例的交易档位。")
        reference = grid.get(f"first_{side}_reference_price")
        if not _positive_number(reference) or Decimal(str(reference)) != tick:
            errors.append(f"网格建议 {code} 的 first_{side}_reference_price 与确认档位不一致。")
    return examples


def _validate_price_and_partial_plan(grid: dict, recommendation: dict, errors: list[str]) -> None:
    code = grid.get("code")
    partial = grid.get("partial_sell_plan")
    path = grid.get("price_plan")
    settings = grid.get("parameter_plan")
    rule = recommendation.get("rule_decision") or {}
    if not isinstance(rule, dict):
        return  # The rule shape error is already recorded by analysis validation.
    if not isinstance(partial, dict) or partial.get("status") not in (
        "CURRENT_PARTIAL_REVIEW", "WAIT_REBOUND", "NO_PARTIAL_INVENTORY", "WAIT_DATA",
    ) or not all(key in partial for key in ("reference_price", "candidate_quantity", "reference_basis", "reason", "sell_policy")):
        errors.append(f"网格建议 {code} 缺少当前部分卖出阶段契约，需重新分析。")
        return
    if settings is None:
        if path is not None or partial["status"] not in {"WAIT_DATA", "NO_PARTIAL_INVENTORY"}:
            errors.append(f"网格建议 {code} 无有效参数却仍有价格或部分卖出动作。")
        return
    if not isinstance(settings, dict) or not isinstance(path, dict):
        errors.append(f"网格建议 {code} 缺少触发路径与价格计划，需重新分析。")
        return
    base, quote = path.get("base_price"), recommendation.get("last_price")
    percentages = [settings.get(field) for field in ("buy_fall_pct", "buy_rebound_pct", "sell_rise_pct", "sell_pullback_pct")]
    if not _positive_number(base) or not _positive_number(quote) or not all(_positive_number(value) for value in percentages):
        errors.append(f"网格建议 {code} 价格计划缺少有效基准、行情或百分比。")
        return
    fall, rebound, rise, pullback = percentages
    if fall >= 100 or pullback >= 100:
        errors.append(f"网格建议 {code} 的下跌或回落比例达到100%，不能生成有效价格计划。")
        return
    source = path.get("base_source")
    expected_base = grid.get("current_base_price") if source == "EXISTING_GRID_REFERENCE" else quote
    if source not in {"CURRENT_QUOTE_NEW_PLAN", "EXISTING_GRID_REFERENCE"} or base != expected_base:
        errors.append(f"网格建议 {code} 价格基准与声明来源不一致。")
    from etfmate.analysis.price_ticks import grid_trigger_price
    buy_trigger = grid_trigger_price(base, fall, "buy")
    sell_trigger = grid_trigger_price(base, rise, "sell")
    if buy_trigger <= 0:
        errors.append(f"网格建议 {code} 的下跌阈值不足一个有效交易档位。")
        return
    expected_prices = {
        "buy_trigger_price": round(buy_trigger, 6),
        "sell_trigger_price": round(sell_trigger, 6),
    }
    for field, expected in expected_prices.items():
        if not _positive_number(path.get(field)) or path[field] != expected:
            errors.append(f"网格建议 {code} 的 {field} 与基准及比例计算不一致。")
    expected_prices.update(_validate_confirmation_prices(
        grid, {"buy": buy_trigger, "sell": sell_trigger}, {"buy": rebound, "sell": pullback}, errors,
    ))
    for side, reached in (("buy", quote <= buy_trigger), ("sell", quote >= sell_trigger)):
        expected = "TRIGGER_ZONE_PATH_UNVERIFIED" if reached else "WAIT_TRIGGER_PATH_UNVERIFIED"
        if path.get(f"{side}_path_status") != expected:
            errors.append(f"网格建议 {code} 的 {side} 触发区间与现价不一致。")
    if path.get("path_evidence") != "SNAPSHOT_ONLY":
        errors.append(f"网格建议 {code} 未区分快照与实际触发路径证据。")

    status, quantity = partial["status"], partial.get("candidate_quantity")
    active = status in {"CURRENT_PARTIAL_REVIEW", "WAIT_REBOUND"}
    held = recommendation.get("quantity") or 0
    reserve = grid.get("suggested_min_base_quantity") or 0
    if active:
        policy = partial.get("sell_policy") or {}
        if (not _positive_number(quantity) or quantity < 100 or quantity % 100 != 0
                or quantity >= held or quantity > held - reserve
                or quantity != grid.get("candidate_sell_quantity") or quantity != settings.get("sell_quantity")):
            errors.append(f"网格建议 {code} 部分卖出份额与持仓、底仓或候选数量不一致。")
        if ("全部" in (rule.get("blocked_actions") or []) or policy.get("sell_allowed") is not True
                or policy.get("sale_scope") != "PARTIAL" or policy.get("rule") != "NO_LOSS_ON_LIQUIDATION"):
            errors.append(f"网格建议 {code} 部分卖出绕过卖出约束。")
        expected_price = quote if status == "CURRENT_PARTIAL_REVIEW" else expected_prices["sell_confirmation_example"]
        expected_basis = "CURRENT_QUOTE_REVIEW" if status == "CURRENT_PARTIAL_REVIEW" else "FUTURE_GRID_PATH_EXAMPLE"
        if not _positive_number(partial.get("reference_price")) or partial.get("reference_price") != expected_price or partial.get("reference_basis") != expected_basis:
            errors.append(f"网格建议 {code} 部分卖出参考价与行动阶段不一致。")
        current = ((rule.get("legacy_exit_assessment") or {}).get("status") == "CURRENT_PARTIAL_REVIEW"
                   or (recommendation.get("technical_assessment") or {}).get("status") == "OVERHEATED")
        if (status == "CURRENT_PARTIAL_REVIEW") != current:
            errors.append(f"网格建议 {code} 部分卖出阶段与当前回本及过热判断不一致。")
    elif quantity is not None or partial.get("reference_price") is not None or grid.get("candidate_sell_quantity") is not None:
        errors.append(f"网格建议 {code} 无部分卖出动作却仍输出份额或价格。")


def _report(errors: list[str], warnings: list[str], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "FAIL" if errors else "PASS",
        "fatal_errors": _dedupe_text(errors),
        "warnings": _dedupe_text(warnings),
        "metrics": metrics,
    }


def _items(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        value = payload.get(key, [])
        if isinstance(value, dict):
            value = list(value.values())
        return [item for item in value if isinstance(item, dict)]
    return []


def _clean_watchlist(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if not _is_position_cache_source_key(item.get("source_key"))]


def _is_position_cache_source_key(value: Any) -> bool:
    text = str(value or "").lower()
    return any(token in text for token in ("defaultpositioin", "defaultposition", "positionlist"))


def _require_code(item: dict[str, Any], errors: list[str], label: str) -> None:
    if not _code(_pick(item, "code", "symbol", "stockCode", "securityCode", "zqdm", "证券代码", "代码")):
        errors.append(f"{label} 缺少有效 6 位代码。")


def _require_scroll_complete(snapshot: Any, label: str, errors: list[str]) -> None:
    if not isinstance(snapshot, dict):
        errors.append(f"{label} 快照缺失。")
        return
    if "scroll_complete" not in snapshot:
        errors.append(f"{label} 快照缺少滚动完整性标记。")
    elif snapshot.get("scroll_complete") is False:
        errors.append(f"{label} 滚动列表未确认到底：{snapshot.get('scroll_stop_reason') or '未知原因'}。")


def _missing_required(item: dict[str, Any], names: tuple[str, ...]) -> bool:
    value = _pick(item, *names)
    if value in (None, ""):
        return True
    if isinstance(value, str) and value.strip() in {"", "--", "-", "N/A", "NaN", "nan"}:
        return True
    if len(names) == 1 and names[0] in {"name", "名称", "证券名称"}:
        return not str(value).strip()
    # If _pick found a non-empty non-placeholder value, it's present —
    # do NOT reject numeric fields just because they are negative
    # (e.g. sell_pullback_pct="-0.20" is a valid grid parameter).
    return False


def _has_any_key(item: dict[str, Any], names: tuple[str, ...]) -> bool:
    return any(name in item for name in names)


def _pick(raw: Any, *names: str) -> Any:
    if not isinstance(raw, dict):
        return None
    for name in names:
        if name in raw and raw[name] not in (None, ""):
            return raw[name]
    return None


def _num(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    text = str(value).replace(",", "").replace("%", "").strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def _code(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^(sh|sz)", "", text)
    text = re.sub(r"\.(sh|sz)$", "", text)
    return text if re.fullmatch(r"\d{6}", text) else ""


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
