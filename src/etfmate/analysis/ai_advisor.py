from __future__ import annotations

from pathlib import Path
from typing import Any

from etfmate.storage.repository import read_json


AI_REVIEW_INPUT_FILE = "ai_review_input.json"
AI_JUDGEMENTS_FILE = "ai_judgements.json"


def build_ai_review_input(recommendations: list[dict], grid_advices: list[dict]) -> dict[str, Any]:
    return {
        "role": "host_ai_review_input",
        "instructions": (
            "你是当前宿主 AI 工具的 ETF 组合风控和网格交易复核助手。只基于 items 中的结构化证据研判，"
            "不得编造行情、新闻、研报或公告；不得承诺收益；不得给满仓/梭哈建议。规则引擎的硬过滤、"
            "流动性约束、仓位约束和数据缺失降级必须优先。输出写入 ai_judgements.json。"
        ),
        "schema": {
            "items": [
                {
                    "code": "ETF代码",
                    "ai_action": "复核动作或倾向",
                    "confidence": "0-100整数",
                    "judgement": "综合研判，必须基于输入证据",
                    "conflicts": ["与规则建议或证据之间的冲突点"],
                    "guardrails": ["必须遵守的风控护栏"],
                    "final_bias": "保持规则建议/降级为保守/需要人工确认",
                }
            ]
        },
        "items": _compact_payload(recommendations, grid_advices),
    }


def load_host_ai_judgements(root: Path, run_id: str, recommendations: list[dict]) -> dict[str, dict[str, Any]]:
    path = root / "data/raw/market" / run_id / AI_JUDGEMENTS_FILE
    if not path.exists():
        return _pending(recommendations, f"宿主 AI 尚未回写 {path.as_posix()}，当前仅展示规则引擎建议")
    payload = read_json(path, default={})
    return normalize_host_ai_judgements(payload, recommendations)


def normalize_host_ai_judgements(payload: Any, recommendations: list[dict]) -> dict[str, dict[str, Any]]:
    rows: list[Any]
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
        rows = payload["items"]
    elif isinstance(payload, dict):
        rows = list(payload.values())
    else:
        rows = []

    valid_codes = {str(item.get("code") or "") for item in recommendations if item.get("code")}
    result = {
        str(item.get("code")): _normalize_item(item)
        for item in rows
        if isinstance(item, dict) and item.get("code") and str(item.get("code")) in valid_codes
    }
    for item in recommendations:
        code = str(item.get("code") or "")
        result.setdefault(code, _fallback_item(code, "宿主 AI 未返回该 ETF 的研判"))
    return result


def attach_ai_judgements(recommendations: list[dict], judgements: dict[str, dict[str, Any]]) -> list[dict]:
    for item in recommendations:
        code = str(item.get("code") or "")
        item["ai_judgement"] = judgements.get(code) or _fallback_item(code, "AI 综合研判未生成")
    return recommendations


def _compact_payload(recommendations: list[dict], grid_advices: list[dict]) -> list[dict[str, Any]]:
    grids = {str(item.get("code")): item for item in grid_advices}
    rows = []
    for item in recommendations:
        rule = item.get("rule_decision") or {}
        context = item.get("layered_context") or {}
        grid = grids.get(str(item.get("code"))) or {}
        rows.append(
            {
                "code": item.get("code"),
                "name": item.get("name"),
                "source": {
                    "candidate_source": item.get("candidate_source"),
                    "is_watchlist_candidate": item.get("is_watchlist_candidate"),
                    "watchlist_include_reason": item.get("watchlist_include_reason"),
                },
                "position": {
                    "quantity": item.get("quantity"),
                    "position_pct": item.get("position_pct"),
                    "holding_pct": item.get("holding_pct"),
                    "position_pct_source": item.get("position_pct_source"),
                    "account_total_asset": item.get("account_total_asset"),
                    "pnl_pct": item.get("pnl_pct"),
                    "note": item.get("investor_note"),
                },
                "market": {
                    "last_price": item.get("last_price"),
                    "pct_chg": item.get("pct_chg"),
                    "ma_status": item.get("ma_status"),
                    "ma5_slope_3": item.get("ma5_slope_3"),
                    "boll_position": item.get("boll_position"),
                    "bias5_ratio": item.get("bias5_ratio"),
                    "rsi6": item.get("rsi6"),
                    "rsi14": item.get("rsi14"),
                    "macd_dif": item.get("macd_dif"),
                    "macd_dea": item.get("macd_dea"),
                    "macd_hist": item.get("macd_hist"),
                    "ret20": item.get("ret20"),
                    "ret60": item.get("ret60"),
                    "max_drawdown_60": item.get("max_drawdown_60"),
                    "atr14_pct": item.get("atr14_pct"),
                    "atr_expansion_ratio": item.get("atr_expansion_ratio"),
                    "amount_ratio20": item.get("amount_ratio20"),
                },
                "rule": {
                    "account_mode": rule.get("account_mode") or item.get("account_mode"),
                    "action": item.get("action"),
                    "position_action": rule.get("position_action") or item.get("position_action"),
                    "trend_trade_mode": rule.get("trend_trade_mode") or item.get("trend_trade_mode"),
                    "trend_overheat_level": rule.get("trend_overheat_level") or item.get("trend_overheat_level"),
                    "execution_mode": rule.get("execution_mode") or item.get("execution_mode"),
                    "action_quantity": item.get("action_quantity"),
                    "short_trend_score": rule.get("trend_score"),
                    "trend_level": rule.get("trend_level"),
                    "trend_tags": rule.get("trend_tags"),
                    "trend_scores": rule.get("trend_scores"),
                    "filter_status": rule.get("filter_status"),
                    "target_position_pct": rule.get("target_position_pct") or item.get("target_position_pct"),
                    "new_position_pct": rule.get("new_position_pct") or item.get("new_position_pct"),
                    "adjust_pct": rule.get("adjust_pct") or item.get("adjust_pct"),
                    "position_risk_level": rule.get("risk_level") or item.get("position_risk_level"),
                    "entry_plan": item.get("entry_plan"),
                    "position_plan": item.get("position_plan"),
                    "blocked_actions": rule.get("blocked_actions"),
                    "reasons": item.get("reasons", [])[:4],
                    "risks": item.get("risks", [])[:4],
                },
                "grid": {
                    "action": grid.get("action"),
                    "grid_mode": grid.get("grid_mode"),
                    "grid_mode_label": grid.get("grid_mode_label"),
                    "execution_checks": grid.get("execution_checks"),
                    "cash_constraint_status": grid.get("cash_constraint_status"),
                    "grid_applicable": grid.get("grid_applicable"),
                    "grid_purpose": grid.get("grid_purpose"),
                    "strategy_profile": grid.get("strategy_profile"),
                    "strategy_guardrails": grid.get("strategy_guardrails"),
                    "base_price_status": grid.get("base_price_status"),
                    "current_base_price": grid.get("current_base_price"),
                    "suggested_base_price": grid.get("suggested_base_price"),
                    "current_buy_fall_pct": grid.get("current_buy_fall_pct"),
                    "suggested_buy_fall_pct": grid.get("suggested_buy_fall_pct"),
                    "current_buy_rebound_pct": grid.get("current_buy_rebound_pct"),
                    "suggested_buy_rebound_pct": grid.get("suggested_buy_rebound_pct"),
                    "current_sell_rise_pct": grid.get("current_sell_rise_pct"),
                    "suggested_sell_rise_pct": grid.get("suggested_sell_rise_pct"),
                    "current_sell_pullback_pct": grid.get("current_sell_pullback_pct"),
                    "suggested_sell_pullback_pct": grid.get("suggested_sell_pullback_pct"),
                    "suggested_buy_quantity": grid.get("suggested_buy_quantity"),
                    "suggested_sell_quantity": grid.get("suggested_sell_quantity"),
                    "suggested_min_base_quantity": grid.get("suggested_min_base_quantity"),
                    "suggested_max_position_quantity": grid.get("suggested_max_position_quantity"),
                },
                "evidence": {
                    "confidence": context.get("confidence"),
                    "score": context.get("total_score"),
                    "summary": context.get("summary"),
                    "missing_layers": context.get("missing_layers"),
                },
            }
        )
    return rows


def _pending(recommendations: list[dict], reason: str) -> dict[str, dict[str, Any]]:
    return {str(item.get("code") or ""): _fallback_item(str(item.get("code") or ""), reason) for item in recommendations}


def _fallback_item(code: str, reason: str) -> dict[str, Any]:
    return {
        "code": code,
        "enabled": False,
        "ai_action": "待宿主AI复核",
        "confidence": 0,
        "judgement": reason,
        "conflicts": [],
        "guardrails": ["宿主 AI 未回写时，最终动作完全按规则引擎和风险约束执行"],
        "final_bias": "保持规则建议",
    }


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    if _contains_stale_sellable_assumption(item):
        code = str(item.get("code") or "")
        return _fallback_item(code, "宿主 AI 研判基于旧规则，需按最新规则重新复核")
    return {
        "code": str(item.get("code") or ""),
        "enabled": True,
        "ai_action": str(item.get("ai_action") or "复核"),
        "confidence": _int_between(item.get("confidence"), 0, 100),
        "judgement": str(item.get("judgement") or ""),
        "conflicts": _list_text(item.get("conflicts")),
        "guardrails": _list_text(item.get("guardrails")),
        "final_bias": str(item.get("final_bias") or "需要人工确认"),
    }


def _int_between(value: Any, low: int, high: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = 0
    return max(low, min(high, number))


def _list_text(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value in (None, ""):
        return []
    return [str(value)]


def _contains_stale_sellable_assumption(item: dict[str, Any]) -> bool:
    text = " ".join(
        str(item.get(key) or "")
        for key in ("ai_action", "judgement", "final_bias", "conflicts", "guardrails")
    )
    return any(token in text for token in ("可用数量", "可卖数量", "今日不可卖", "今日不应", "今日可立即"))
