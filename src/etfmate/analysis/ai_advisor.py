from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


DEFAULT_MODEL = "gpt-5-mini"
DEFAULT_RESPONSES_URL = "https://api.openai.com/v1/responses"


def build_ai_judgements(recommendations: list[dict], grid_advices: list[dict]) -> dict[str, dict[str, Any]]:
    enabled = os.environ.get("ETFMATE_AI_ENABLED", "auto").strip().lower()
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("ETFMATE_OPENAI_API_KEY")
    if enabled in {"0", "false", "off", "disabled", "否"}:
        return _disabled(recommendations, "AI 综合研判已通过 ETFMATE_AI_ENABLED 关闭")
    if not api_key:
        return _disabled(recommendations, "未配置 OPENAI_API_KEY/ETFMATE_OPENAI_API_KEY，AI 综合研判未启用")

    compact = _compact_payload(recommendations, grid_advices)
    try:
        rows = _call_openai(api_key, compact)
    except Exception as exc:
        return _disabled(recommendations, f"AI 综合研判调用失败：{type(exc).__name__}: {exc}")
    result = {str(item.get("code")): _normalize_item(item) for item in rows if item.get("code")}
    for item in recommendations:
        code = str(item.get("code") or "")
        result.setdefault(code, _fallback_item(code, "AI 未返回该 ETF 的研判"))
    return result


def attach_ai_judgements(recommendations: list[dict], judgements: dict[str, dict[str, Any]]) -> list[dict]:
    for item in recommendations:
        code = str(item.get("code") or "")
        item["ai_judgement"] = judgements.get(code) or _fallback_item(code, "AI 综合研判未生成")
    return recommendations


def _call_openai(api_key: str, payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    model = os.environ.get("ETFMATE_AI_MODEL", DEFAULT_MODEL)
    url = os.environ.get("ETFMATE_OPENAI_RESPONSES_URL", DEFAULT_RESPONSES_URL)
    body = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": (
                    "你是ETF组合风控和网格交易复核助手。只基于用户给出的结构化证据研判，"
                    "不得编造行情、新闻、研报或公告。不得承诺收益，不得给满仓/梭哈建议。"
                    "规则引擎的硬过滤、禁止交易、流动性约束和数据缺失降级必须优先。"
                    "输出必须是JSON数组。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请复核以下ETF规则建议。每项输出字段：code, ai_action, confidence, judgement, "
                    "conflicts, guardrails, final_bias。confidence为0-100整数；final_bias只能是"
                    "保持规则建议、降级为保守、需要人工确认。数据不足时应降级或人工确认。\n"
                    + json.dumps(payload, ensure_ascii=False)
                ),
            },
        ],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:300]
        raise RuntimeError(f"HTTP {exc.code} {detail}") from exc
    text = _response_text(data)
    parsed = json.loads(_strip_code_fence(text))
    if not isinstance(parsed, list):
        raise RuntimeError("AI 返回不是 JSON 数组")
    return parsed


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
                "position": {
                    "quantity": item.get("quantity"),
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


def _response_text(data: dict[str, Any]) -> str:
    if data.get("output_text"):
        return str(data["output_text"])
    parts: list[str] = []
    for output in data.get("output") or []:
        for content in output.get("content") or []:
            if content.get("type") in {"output_text", "text"}:
                parts.append(str(content.get("text") or ""))
    text = "\n".join(part for part in parts if part)
    if not text:
        raise RuntimeError("AI 响应没有文本内容")
    return text


def _strip_code_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1] if "\n" in value else value
        if value.endswith("```"):
            value = value[:-3]
    return value.strip()


def _disabled(recommendations: list[dict], reason: str) -> dict[str, dict[str, Any]]:
    return {str(item.get("code") or ""): _fallback_item(str(item.get("code") or ""), reason) for item in recommendations}


def _fallback_item(code: str, reason: str) -> dict[str, Any]:
    return {
        "code": code,
        "enabled": False,
        "ai_action": "未启用",
        "confidence": 0,
        "judgement": reason,
        "conflicts": [],
        "guardrails": ["AI 未生成时，最终动作完全按规则引擎和风险约束执行"],
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
