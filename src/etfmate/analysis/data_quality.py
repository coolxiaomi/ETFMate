from __future__ import annotations

import re
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
    return _report(errors, warnings, metrics)


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
    return _report(errors, warnings, metrics)


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
        errors.append("分析契约已更新，旧分析未执行账户角色与清仓不亏规则；请重新执行 analyze 和宿主 AI 复核后生成报告。")
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
    if not analysis.get("ai_review_input_path"):
        warnings.append("analysis.json 未记录 ai_review_input_path。")


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
