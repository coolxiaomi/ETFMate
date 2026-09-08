from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from etfmate.storage.repository import read_json
from etfmate.analysis.sell_policy import NO_LOSS_RULE
from etfmate.analysis.account_strategy import ANALYSIS_CONTRACT, FUNDING_PRIORITY_NOTE


AI_REVIEW_INPUT_FILE = "ai_review_input.json"
AI_JUDGEMENTS_FILE = "ai_judgements.json"
AI_REVIEW_CONTRACT = ANALYSIS_CONTRACT


def build_ai_review_input(
    recommendations: list[dict], grid_advices: list[dict], *,
    run_id: str = "", review_id: str = "", source_context: dict | None = None,
) -> dict[str, Any]:
    items = _compact_payload(recommendations, grid_advices)
    context = source_context or {}
    fingerprint = _fingerprint({
        "review_contract": AI_REVIEW_CONTRACT, "run_id": run_id,
        "review_id": review_id, "context": context, "items": items,
    })
    return {
        "role": "host_ai_review_input",
        "run_id": run_id,
        "review_id": review_id,
        "input_fingerprint": fingerprint,
        "context": context,
        "instructions": (
            "你是当前宿主 AI 工具的 ETF 组合风控和网格交易复核助手。只基于 items 中的结构化证据研判，"
            "不得编造行情、新闻、研报或公告；不得承诺收益；不得给满仓/梭哈建议。规则引擎的硬过滤、"
            "流动性约束、仓位约束和数据缺失降级必须优先。账户资金不追加也不转出；现有待退出持仓仍需持续给出盈利改善、波动和分批退出计划，不得只说等清仓。目标组合须满足价格与可用资金条件，主要承接旧仓回款，也可在价格合适时使用已有可用现金。成长40%/价值60%仅是组内最终目标，建仓期不机械卖出高配侧；不得推荐新标的。输出写入 ai_judgements.json。" + NO_LOSS_RULE
        ),
        "funding_priority_instruction": FUNDING_PRIORITY_NOTE,
        "technical_review_instruction": "逐只复核technical_assessment中的均线、乖离、RSI、布林与量能及冲突；超卖不等于买点，缺少前序日线证据不能称企稳。区分价格条件和账户执行限制，不重复公共规则，不覆盖硬过滤。",
        "action_review_instruction": (
            "逐只对账当前价格、页面回本与完整周期回本口径、行动阶段、买卖触发方向、候选份额和执行限制。"
            "已经达到的退出条件不能继续要求等待反弹；单笔与连续卖出不得绕过最终清仓约束；不能把未成交回款当作买入资金。"
            "不要机械认同规则，也不要用一段清仓护栏替代逐只结论。发现建议与证据矛盾时写 review_status=REVISE，"
            "在 conflicts 中保留需要修改的问题；只有无需修改才写 PASS、conflicts=[]、final_bias=保持规则建议。"
            "技术信号之间可解释的分歧写入 judgement；conflicts 专门记录尚未解决的建议或证据矛盾。"
            "原样回写本次 run_id、review_id 和 input_fingerprint，不能复用其他批次或旧分析复核。"
        ),
        "decision_review_instruction": (
            "复核 context.decision_review 与逐只 action_plan.quantity_basis、contingency_plan 及 condition_plan.follow_up_policy。"
            "80%只限制新增买入，不是强制减仓或最大回撤保证；未设风险阈值、角色预算、现金缓冲和退出期限时，"
            "不得自行补成止损、资金分配或交易授权。最终清仓须回本可能长期无法完成，部分亏损卖出可能提高剩余回本线。"
            "沿用原单量或按约四分之一持仓起拟不等于按账户风险优化；布林上轨或过热不单独证明理想卖点。"
            "核对理论确认边界与首个满足条件的报价档位，买入反弹向上取档、卖出回落向下取档；二者都不是成交价。"
            "当前卖出情景只是假设，不能将未来反弹单合并为已成交回款；未触发、继续下跌、部分成交、失败或未成交时，"
            "按证据复评，不自动重试或绕过清仓约束。历史失败计数不是亏损率，费用按约定忽略不证明净收益有效。"
            "PASS仅证明本轮证据与条件计划一致；策略有效性尚未验证和已明确披露的待确认政策不等同于代码冲突。"
        ),
        "schema": {
            "review_contract": AI_REVIEW_CONTRACT,
            "run_id": run_id,
            "review_id": review_id,
            "input_fingerprint": fingerprint,
            "items": [{
                "code": "ETF代码",
                "review_status": "PASS/REVISE",
                "ai_action": "复核动作或倾向",
                "confidence": "0-100整数，不表示收益概率",
                "judgement": "基于该标的证据，说明当前动作、条件与限制是否一致",
                "conflicts": ["尚未解决的建议或证据矛盾；无矛盾时为空数组"],
                "guardrails": ["该标的必须遵守的风控护栏"],
                "final_bias": "保持规则建议/降级为保守/需要人工确认",
            }],
        },
        "items": items,
    }


def review_input_for_analysis(account: dict, grid_payload: dict, analysis: dict) -> dict:
    """Rebuild from current sources, not a possibly stale saved AI input file."""
    from etfmate.analysis.execution_review import build_execution_review
    conditions = grid_payload.get("grids") or []
    return build_ai_review_input(
        analysis.get("recommendations") or [], analysis.get("grid_advices") or [],
        run_id=str(analysis.get("run_id") or ""),
        review_id=str(analysis.get("ai_review_id") or ""),
        source_context={
            "account_overview": analysis.get("account_overview") or {},
            "funding_plan": analysis.get("funding_plan") or {},
            "inventory_plan": analysis.get("inventory_plan") or {},
            "decision_review": analysis.get("decision_review") or {},
            "original_conditions": conditions,
            "execution_review": build_execution_review(
                analysis.get("recommendations") or [], analysis.get("grid_advices") or [], conditions,
                analysis.get("funding_plan"),
                grid_payload.get("submitted_orders"),
            ),
            "source_fingerprint": _fingerprint({
                "account": account, "grid_payload": grid_payload,
                "market_snapshots": analysis.get("market_snapshots") or [],
            }),
        },
    )


def ai_review_validation_errors(
    payload: Any, recommendations: list[dict], expected_input: dict | None = None,
    *, require_pass: bool = False,
) -> list[str]:
    if not isinstance(payload, dict) or payload.get("review_contract") != AI_REVIEW_CONTRACT:
        return ["AI 输入契约已更新或本次复核未生成，请读取本次 ai_review_input.json 后重新复核。"]
    errors = []
    for field in ("run_id", "review_id", "input_fingerprint"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"AI 复核缺少本次绑定字段 {field}。")
        elif expected_input is not None and value != expected_input.get(field):
            errors.append(f"AI 复核 {field} 与本次分析不一致，需重新复核。")
    rows = payload.get("items")
    if not isinstance(rows, list):
        return errors + ["AI 复核 items 必须为逐只复核数组。"]
    expected_codes = {str(item.get("code") or "") for item in recommendations}
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            errors.append("AI 复核含非对象条目。")
            continue
        code = str(row.get("code") or "")
        if code not in expected_codes:
            errors.append(f"AI 复核含非本次研究范围代码：{code or '空代码'}。")
        if code in seen:
            errors.append(f"AI 复核存在重复代码：{code}。")
        seen.add(code)
        for field in ("ai_action", "judgement", "final_bias"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                errors.append(f"AI 复核 {code} 缺少有效 {field}，不能作为已完成复核。")
        confidence = row.get("confidence")
        if type(confidence) is not int or not 0 <= confidence <= 100:
            errors.append(f"AI 复核 {code} confidence 必须为 0-100 整数。")
        for field in ("conflicts", "guardrails"):
            values = row.get(field)
            if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                errors.append(f"AI 复核 {code} {field} 必须为有效文本数组。")
            elif field == "guardrails" and not values:
                errors.append(f"AI 复核 {code} 缺少具体风控护栏。")
        if row.get("review_status") not in ("PASS", "REVISE"):
            errors.append(f"AI 复核 {code} 缺少 PASS/REVISE 结论。")
        if row.get("final_bias") not in ("保持规则建议", "降级为保守", "需要人工确认"):
            errors.append(f"AI 复核 {code} final_bias 不符合当前契约。")
        if require_pass and (row.get("review_status") != "PASS" or row.get("conflicts") or row.get("final_bias") != "保持规则建议"):
            errors.append(f"AI 复核 {code} 仍有未解决的问题或需要调整动作，不能生成正式报告。")
    missing = expected_codes - seen
    if missing:
        errors.append(f"AI 复核缺少研究标的：{', '.join(sorted(missing))}。")
    return errors


def load_host_ai_judgements(
    root: Path, run_id: str, recommendations: list[dict], expected_input: dict | None = None,
) -> dict[str, dict[str, Any]]:
    path = root / "data/raw/market" / run_id / AI_JUDGEMENTS_FILE
    if not path.exists():
        return _pending(recommendations, "宿主 AI 尚未回写本次复核，规则分析仅供复核，不能生成正式报告")
    if expected_input is None:
        expected_input = read_json(path.parent / AI_REVIEW_INPUT_FILE, default={})
    return normalize_host_ai_judgements(read_json(path, default={}), recommendations, expected_input)


def normalize_host_ai_judgements(
    payload: Any, recommendations: list[dict], expected_input: dict | None = None,
) -> dict[str, dict[str, Any]]:
    errors = ai_review_validation_errors(payload, recommendations, expected_input)
    if errors:
        return _pending(recommendations, "；".join(errors))
    return {str(row["code"]): {
        **row, "code": str(row["code"]), "enabled": True, "execution_authority": False,
    } for row in payload["items"]}


def attach_ai_judgements(recommendations: list[dict], judgements: dict[str, dict[str, Any]]) -> list[dict]:
    for item in recommendations:
        code = str(item.get("code") or "")
        review = dict(judgements.get(code) or _fallback_item(code, "AI 综合研判未生成"))
        # Preserve review evidence, including objections. AI text is never an order.
        review["execution_authority"] = False
        policy = (item.get("rule_decision") or {}).get("sell_policy") or item.get("sell_policy")
        if policy:
            review["execution_guardrails"] = [NO_LOSS_RULE, policy["reason"]]
        item["ai_judgement"] = review
    return recommendations


def _compact_payload(recommendations: list[dict], grid_advices: list[dict]) -> list[dict[str, Any]]:
    from etfmate.analysis.action_plan import describe_action_plan
    grids = {str(item.get("code")): item for item in grid_advices}
    return [{
        "code": item.get("code"), "name": item.get("name"),
        "strategy_role": item.get("strategy_role"), "pair_progress": item.get("pair_progress"),
        "position": {key: item.get(key) for key in ("quantity", "market_value", "position_pct", "cost_price", "pnl_pct", "investor_note")},
        "market": {key: item.get(key) for key in ("last_price", "pct_chg", "quote_time", "signal_date", "signal_close",
                    "signal_is_complete", "signal_volume_basis", "ma20", "ma60", "atr14_pct", "rsi6", "amount_avg20", "kline_days", "data_quality")},
        "rule": item.get("rule_decision"), "grid": grids.get(str(item.get("code"))),
        "technical_assessment": item.get("technical_assessment"),
        "action_plan": describe_action_plan(item, grids.get(str(item.get("code")), {})),
    } for item in recommendations]


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pending(recommendations: list[dict], reason: str) -> dict[str, dict[str, Any]]:
    return {str(item.get("code") or ""): _fallback_item(str(item.get("code") or ""), reason) for item in recommendations}


def _fallback_item(code: str, reason: str) -> dict[str, Any]:
    return {
        "code": code, "enabled": False, "review_status": "PENDING", "execution_authority": False,
        "ai_action": "待宿主AI复核", "confidence": 0, "judgement": reason,
        "conflicts": [], "guardrails": ["复核完成前不得生成正式报告"], "final_bias": "需要人工确认",
    }
