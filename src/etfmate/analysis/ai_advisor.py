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
            "可用数量、流动性约束和数据缺失降级必须优先。输出写入 ai_judgements.json。"
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

    result = {str(item.get("code")): _normalize_item(item) for item in rows if isinstance(item, dict) and item.get("code")}
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
                    "available_quantity": item.get("available_quantity"),
                    "position_pct": item.get("position_pct"),
                    "pnl_pct": item.get("pnl_pct"),
                    "note": item.get("investor_note"),
                },
                "market": {
                    "last_price": item.get("last_price"),
                    "pct_chg": item.get("pct_chg"),
                    "ma_status": item.get("ma_status"),
                    "rsi14": item.get("rsi14"),
                    "ret20": item.get("ret20"),
                    "ret60": item.get("ret60"),
                    "max_drawdown_60": item.get("max_drawdown_60"),
                    "atr14_pct": item.get("atr14_pct"),
                    "amount_ratio20": item.get("amount_ratio20"),
                },
                "rule": {
                    "action": item.get("action"),
                    "action_quantity": item.get("action_quantity"),
                    "score": rule.get("total_score"),
                    "trend": rule.get("trend_score"),
                    "momentum": rule.get("momentum_score"),
                    "risk": rule.get("risk_score"),
                    "filter_status": rule.get("filter_status"),
                    "target_position_pct": rule.get("target_position_pct") or item.get("target_position_pct"),
                    "entry_plan": item.get("entry_plan"),
                    "position_plan": item.get("position_plan"),
                    "blocked_actions": rule.get("blocked_actions"),
                    "reasons": item.get("reasons", [])[:4],
                    "risks": item.get("risks", [])[:4],
                },
                "grid": {
                    "action": grid.get("action"),
                    "current_buy_fall_pct": grid.get("current_buy_fall_pct"),
                    "suggested_buy_fall_pct": grid.get("suggested_buy_fall_pct"),
                    "suggested_buy_quantity": grid.get("suggested_buy_quantity"),
                    "suggested_sell_quantity": grid.get("suggested_sell_quantity"),
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
