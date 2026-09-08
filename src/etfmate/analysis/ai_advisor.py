from __future__ import annotations

from pathlib import Path
from typing import Any

from etfmate.storage.repository import read_json
from etfmate.analysis.sell_policy import NO_LOSS_RULE
from etfmate.analysis.account_strategy import ANALYSIS_CONTRACT, FUNDING_PRIORITY_NOTE


AI_REVIEW_INPUT_FILE = "ai_review_input.json"
AI_JUDGEMENTS_FILE = "ai_judgements.json"
AI_REVIEW_CONTRACT = ANALYSIS_CONTRACT


def build_ai_review_input(recommendations: list[dict], grid_advices: list[dict]) -> dict[str, Any]:
    return {
        "role": "host_ai_review_input",
        "instructions": (
            "你是当前宿主 AI 工具的 ETF 组合风控和网格交易复核助手。只基于 items 中的结构化证据研判，"
            "不得编造行情、新闻、研报或公告；不得承诺收益；不得给满仓/梭哈建议。规则引擎的硬过滤、"
            "流动性约束、仓位约束和数据缺失降级必须优先。账户资金不追加也不转出；现有待退出持仓仍需持续给出盈利改善、波动和分批退出计划，不得只说等清仓。目标组合须满足价格与可用资金条件，主要承接旧仓回款，也可在价格合适时使用已有可用现金。成长40%/价值60%仅是组内最终目标，建仓期不机械卖出高配侧；不得推荐新标的。输出写入 ai_judgements.json。" + NO_LOSS_RULE
        ),
        "funding_priority_instruction": FUNDING_PRIORITY_NOTE,
        "technical_review_instruction": "逐只复核technical_assessment中的均线、乖离、RSI、布林与量能及冲突；超卖不等于买点，缺少前序日线证据不能称企稳。区分价格条件和账户执行限制，不重复公共规则，不覆盖硬过滤。",
        "schema": {
            "review_contract": AI_REVIEW_CONTRACT,
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
    if not isinstance(payload, dict) or payload.get("review_contract") != AI_REVIEW_CONTRACT:
        return _pending(recommendations, "AI 输入契约已更新，请读取本次 ai_review_input.json 后重新复核")
    rows: list[Any]
    if isinstance(payload.get("items"), list):
        rows = payload["items"]
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
        policy = (item.get("rule_decision") or {}).get("sell_policy") or item.get("sell_policy")
        if policy:
            # Free-form AI text cannot authorize a sale or contradict the gate.
            item["ai_judgement"] = {
                **item["ai_judgement"],
                "ai_action": "遵守账户角色与清仓约束",
                "judgement": policy["reason"],
                "conflicts": [],
                "guardrails": [NO_LOSS_RULE],
                "final_bias": "保持角色计划；部分卖出与最终清仓分别核验，交易费用忽略",
            }
            judgements[code] = item["ai_judgement"]
    return recommendations


def _compact_payload(recommendations: list[dict], grid_advices: list[dict]) -> list[dict[str, Any]]:
    from etfmate.analysis.action_plan import describe_action_plan
    grids = {str(item.get("code")): item for item in grid_advices}
    return [{
        "code": item.get("code"), "name": item.get("name"),
        "strategy_role": item.get("strategy_role"), "pair_progress": item.get("pair_progress"),
        "position": {key: item.get(key) for key in ("quantity", "market_value", "position_pct", "cost_price", "pnl_pct", "investor_note")},
        "market": {key: item.get(key) for key in ("last_price", "pct_chg", "ma20", "ma60", "atr14_pct", "rsi6", "amount_avg20", "kline_days", "data_quality")},
        "rule": item.get("rule_decision"), "grid": grids.get(str(item.get("code"))),
        "technical_assessment": item.get("technical_assessment"),
        "action_plan": describe_action_plan(item, grids.get(str(item.get("code")), {})),
    } for item in recommendations]


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
