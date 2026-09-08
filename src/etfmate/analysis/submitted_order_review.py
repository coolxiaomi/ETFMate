"""Describe observed Touker submissions without inventing broker reservations."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import Any


AUDIT_CONTRACT = "touker_submitted_audit_v1"
REVIEW_CONTRACT = "touker_submitted_review_v1"
SHANGHAI = timezone(timedelta(hours=8))
TERMINAL = {"FILLED", "CANCELLED", "REJECTED"}
OPEN = {"SUBMITTED", "PARTIALLY_FILLED", "CANCEL_PENDING", "PENDING_SUBMISSION"}

_STATUSES = {
    "FILLED": {"已成交", "全部成交", "已全部成交", "全成", "成交成功"},
    "CANCELLED": {"已撤单", "已撤销", "已撤", "撤单成功", "全部撤单", "部撤", "部分撤单", "部成部撤", "部分成交已撤单"},
    "REJECTED": {"失败", "已失败", "拒单", "已拒绝", "废单", "委托失败", "申报失败", "报单失败", "交易失败"},
    "SUBMITTED": {"已申报", "已报", "已委托", "已提交", "待成交", "未成交"},
    "PARTIALLY_FILLED": {"部分成交", "已部分成交", "部成"},
    "CANCEL_PENDING": {"待撤", "已报待撤", "撤单中", "撤单已报", "正在撤单", "撤单已提交"},
    "PENDING_SUBMISSION": {"待申报", "待报", "正报", "提交中", "正在申报"},
}
_REJECTION_REASONS = (
    "可用资金不足", "资金不足", "可卖数量不足", "可卖余额不足", "可用股份不足",
    "股份余额不足", "证券余额不足", "库存不足", "数量不合法", "数量非法", "数量无效",
    "价格不合法", "价格非法", "价格无效", "申报价格不合法", "申报价格无效",
    "委托价格不合法", "委托价格无效", "参数错误", "参数不合法", "参数无效",
)
_STATUS_DELIMITERS = ("：", ":", "，", ",", "；", ";", "（", "(")
_FAILURE_LABELS = {
    "INSUFFICIENT_FUNDS": "资金不足",
    "INSUFFICIENT_SELLABLE": "可卖数量不足",
    "INVALID_PRICE_OR_PARAMETER": "价格或参数不合法",
    "UNCLASSIFIED": "未归类",
}
_FAILURE_PREFIX = re.compile(
    r"^(?:订单状态|委托状态|失败原因|错误信息|错误原因|拒单原因|申报失败|委托失败|报单失败|交易失败|失败|拒单|废单)[:：，,；;]\s*"
)
_FAILURE_PATTERNS = {
    "INSUFFICIENT_FUNDS": re.compile(r"^(?:可用)?资金不足(?:$|[:：，,；;（(])"),
    "INSUFFICIENT_SELLABLE": re.compile(
        r"^(?:(?:可卖数量|可卖余额|可用股份|股份余额|证券余额|库存)不足(?:$|[:：，,；;（(])"
        r"|委托数量超出该证券[:：]\d{6}的可用数量(?:$|[:：，,；;（(]))"
    ),
    "INVALID_PRICE_OR_PARAMETER": re.compile(
        r"^(?:(?:(?:申报|委托)?(?:价格|数量)|参数)(?:不合法|非法|无效|错误)(?:$|[:：，,；;（(])"
        r"|(?:申报|委托)数量(?:应该是|应是|必须是|不是|必须为)100的整数倍(?:$|[:：，,；;（(]))"
    ),
}


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _status(value: Any) -> str:
    text = re.sub(r"\s+", "", _text(value))
    text = re.sub(r"^(?:订单状态|委托状态)[:：]", "", text)
    for status, labels in _STATUSES.items():
        if text in labels:
            return status
    # A failed cancellation does not terminate the original securities order.
    if "撤单失败" in text or "撤销失败" in text:
        return "UNKNOWN"
    # A direct status/rejection result is evidence; a narrative mentioning a
    # possible error ("如资金不足...") is not an observed failed submission.
    if any(text == reason or any(text.startswith(reason + delimiter) for delimiter in _STATUS_DELIMITERS)
           for reason in _REJECTION_REASONS):
        return "REJECTED"
    if re.fullmatch(r"委托数量超出该证券[:：]\d{6}的可用数量", text):
        return "REJECTED"
    if re.fullmatch(r"委托数量(?:应该是|应是|必须是|不是)100的整数倍(?:[（(]卖出零股则剩余必须是整股[）)])?", text):
        return "REJECTED"
    matches = {status for status, labels in _STATUSES.items()
               if any(text.startswith(label + delimiter) for label in labels for delimiter in _STATUS_DELIMITERS)}
    return matches.pop() if len(matches) == 1 else "UNKNOWN"


def _resolved_status(record: dict) -> tuple[str, list[str]]:
    main, detail = _status(record.get("status")), _status(record.get("detail_status"))
    notes = []
    detail_text = _text(record.get("detail_status"))
    if "撤单失败" in detail_text or "撤销失败" in detail_text:
        notes.append("撤单失败不证明原委托已经结束。")
    if detail == "UNKNOWN":
        return main, notes
    if main == "UNKNOWN" or main == detail:
        return detail, notes
    # A generic list-stage label may precede a more specific detail result.
    if main in {"SUBMITTED", "PENDING_SUBMISSION"}:
        return detail, notes
    if main == "PARTIALLY_FILLED" and detail in {"FILLED", "CANCELLED", "CANCEL_PENDING"}:
        return detail, notes
    notes.append("列表状态与委托详情不一致，不能自行认定成交、撤单或仍在处理中。")
    return "UNKNOWN_CONFLICT", notes


def _timestamp(value: Any) -> datetime | None:
    text = _text(value)
    if not re.search(r"[T ]\d{2}:\d{2}", text):
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=SHANGHAI) if parsed.tzinfo is None else parsed.astimezone(SHANGHAI)


def _date(value: Any) -> date | None:
    text = _text(value).replace("/", "-").replace(".", "-")
    if not re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", text):
        return None
    try:
        year, month, day = map(int, text.split("-"))
        return date(year, month, day)
    except ValueError:
        return None


def _order_time(record: dict) -> tuple[date | None, datetime | None, list[str]]:
    timestamp = _timestamp(record.get("submitted_at"))
    day = _date(record.get("date"))
    combined = None
    issues = []
    if record.get("submitted_at") and timestamp is None:
        issues.append("委托 submitted_at 无法解析。")
    if record.get("date") and day is None:
        issues.append("委托日期不完整或无效，不能默认属于今天。")
    if record.get("time"):
        try:
            clock = time.fromisoformat(_text(record["time"]).replace("Z", "+00:00"))
            if day is not None:
                combined = datetime.combine(day, clock)
                combined = (combined.replace(tzinfo=SHANGHAI) if combined.tzinfo is None
                            else combined.astimezone(SHANGHAI))
        except ValueError:
            issues.append("委托时刻字段无效。")
    if timestamp is not None and combined is not None and timestamp != combined:
        issues.append("委托 submitted_at 与日期、时刻字段不一致。")
    elif timestamp is not None and day is not None and combined is None and timestamp.date() != day:
        issues.append("委托时间与日期字段不一致。")
    resolved = timestamp if timestamp is not None else combined
    return (resolved.date() if resolved is not None else day), resolved, issues


def _failure_reason(record: dict) -> dict:
    """Classify explicit failure results; prose mentioning a possible error is not a cause."""
    evidence = {key: record[key] for key in ("status", "detail_status")
                if _status(record.get(key)) == "REJECTED"}
    # These fields, when present, are explicit reason fields on an already rejected
    # order. Do not search arbitrary raw text, which may contain help or warnings.
    evidence.update({key: record[key] for key in ("failure_reason", "reject_reason", "error_message")
                     if isinstance(record.get(key), str) and record[key].strip()})
    categories = set()
    for value in evidence.values():
        text = re.sub(r"\s+", "", _text(value))
        while True:
            stripped = _FAILURE_PREFIX.sub("", text, count=1)
            if stripped == text:
                break
            text = stripped
        categories.update(code for code, pattern in _FAILURE_PATTERNS.items() if pattern.match(text))
    category = next(iter(categories)) if len(categories) == 1 else "UNCLASSIFIED"
    return {
        "category": category, "label": _FAILURE_LABELS[category], "evidence_fields": evidence,
        "note": ("原文出现不同失败原因，保留证据待核对。" if len(categories) > 1
                 else "原文未提供可明确归类的失败原因，不推断资金、库存或参数问题。" if not categories
                 else "按本笔委托的明确错误原文归类，不推断当前资金、库存或策略收益。"),
    }


def _review_record(raw: Any, index: int, captured: datetime | None, source_verified: bool) -> dict:
    record = raw if isinstance(raw, dict) else {}
    observed_on = captured.date() if captured is not None else None
    status, notes = _resolved_status(record)
    day, submitted_at, date_issues = _order_time(record)
    issues = list(date_issues)
    code = _text(record.get("code")).lower()
    code = re.sub(r"^(sh|sz)", "", code)
    code = re.sub(r"\.(sh|sz)$", "", code)
    if not re.fullmatch(r"\d{6}", code):
        issues.append("缺少有效证券代码。")
    if not isinstance(raw, dict):
        issues.append("委托记录不是有效对象。")
    if not source_verified:
        issues.append("来源未证明为已选中的「已委托」列表，不能把监控条件当成委托。")
    if observed_on is None:
        issues.append("缺少有效采集时间，无法判断是否为今日委托。")
    if day is None:
        issues.append("缺少完整委托日期，不从时刻或当前日期补造。")
    elif observed_on is not None and day > observed_on:
        issues.append("委托日期晚于采集日期。")
    if captured is not None and submitted_at is not None and submitted_at > captured:
        issues.append("委托时刻晚于采集时刻，不能确认为采集时已发生的委托。")
    elif day is not None and submitted_at is None:
        notes.append("仅有委托日期，未提供完整时刻；只能核对日期先后，不能证明同日委托发生在采集之前。")
    if status not in TERMINAL | OPEN:
        issues.append("委托状态未知或相互冲突。")
    classification = "UNKNOWN"
    if not issues:
        if status in TERMINAL:
            classification = "TERMINAL"
            notes.append("此笔记录显示终态；不计为当前未完成委托，也不据此重复增加账本回款。")
        elif day == observed_on:
            classification = "TODAY_OPEN"
            notes.append("今日仍显示非终态；调整重叠条件前核对剩余委托状态，不能据此计算冻结金额。")
        else:
            classification = "HISTORICAL_UNRESOLVED"
            notes.append("历史日期仍显示非终态，属于未更新状态；不能当作今日冻结或认定已自动撤单。")
    return {
        "index": index, "order_id": record.get("order_id"), "code": code or None,
        "submitted_at": record.get("submitted_at"), "date": record.get("date"), "time": record.get("time"),
        "order_date": day.isoformat() if day is not None else None,
        "order_timestamp": submitted_at.isoformat() if submitted_at is not None else None,
        "observed_time_basis": "TIMESTAMP" if submitted_at is not None else "DATE_ONLY" if day is not None else "UNKNOWN",
        "side": record.get("side"), "quantity": record.get("quantity"), "price": record.get("price"),
        "filled_quantity": record.get("filled_quantity"), "status": record.get("status"),
        "detail_status": record.get("detail_status"), "normalized_status": status,
        "observation_status": classification, "terminal": status in TERMINAL if not issues else None,
        "failure_reason": _failure_reason(record) if status == "REJECTED" and classification == "TERMINAL" else None,
        "note": "".join(notes + issues), "issues": issues, "source_record": deepcopy(raw),
    }


def _failure_summary(records: list[dict], source_verified: bool, complete: bool, read_range: dict) -> dict:
    rejected = [row for row in records if row.get("failure_reason") is not None]
    categories = []
    if source_verified:
        for code, label in _FAILURE_LABELS.items():
            matching = [row for row in rejected if row["failure_reason"]["category"] == code]
            examples = []
            for row in matching[:3]:
                raw = row["source_record"]
                evidence = deepcopy(row["failure_reason"]["evidence_fields"])
                examples.append({
                    "index": row["index"], "order_id": row["order_id"], "code": row["code"],
                    "order_date": row["order_date"], "evidence_fields": evidence,
                    "raw_text": raw.get("raw_text") or "\n".join(evidence.values()),
                    "note": row["failure_reason"]["note"],
                })
            categories.append({"code": code, "label": label, "count": len(matching), "examples": examples})
    return {
        "contract": "submission_failure_summary_v1", "scope": "OBSERVED_RECORDS_ONLY",
        "source_verified": source_verified, "complete": complete, "read_range": deepcopy(read_range),
        "observed_rejected_count": len(rejected) if source_verified else None,
        "categories": categories,
        "unclassified_count": sum(row["failure_reason"]["category"] == "UNCLASSIFIED" for row in rejected)
        if source_verified else None,
        "note": "仅汇总本次已读取且状态、日期和来源可核验的申报失败记录；未读到的历史与状态冲突记录不计入。"
                "失败笔数不是交易亏损笔数，历史失败占比不能当作亏损率或未来失败概率。"
                "重设条件前按原始回报核对原因，不因归类结果自动重试。",
    }


def build_submitted_order_review(snapshot: dict | None) -> dict[str, Any]:
    """Use Shanghai capture date; never infer today's state from historical labels."""
    payload = snapshot if isinstance(snapshot, dict) else {}
    captured = _timestamp(payload.get("captured_at"))
    observed_on = captured.date() if captured is not None else None
    source_verified = (payload.get("contract") == AUDIT_CONTRACT
                       and payload.get("selected_tab") == "已委托"
                       and payload.get("selection_verified") is True)
    raw_records = payload.get("records")
    records_present = isinstance(raw_records, list)
    records = [_review_record(row, index, captured, source_verified)
               for index, row in enumerate(raw_records if records_present else [], start=1)]
    capture_complete = source_verified and captured is not None and records_present and payload.get("complete") is True
    today = [row for row in records if row["observation_status"] == "TODAY_OPEN"]
    historical = [row for row in records if row["observation_status"] == "HISTORICAL_UNRESOLVED"]
    unknown = [row for row in records if row["observation_status"] == "UNKNOWN"]
    complete = capture_complete and not unknown
    known_dates = sorted(row["order_date"] for row in records if row["order_date"] is not None)
    read_range = {"earliest": known_dates[0] if known_dates else None, "latest": known_dates[-1] if known_dates else None}
    observed_failures = sum(row["normalized_status"] == "REJECTED" and row["observation_status"] == "TERMINAL"
                            and row["order_date"] < observed_on.isoformat() for row in records) if observed_on else None
    counts = dict(Counter(
        row["normalized_status"] if row["observation_status"] != "UNKNOWN"
        else "UNKNOWN_CONFLICT" if row["normalized_status"] == "UNKNOWN_CONFLICT" else "UNKNOWN"
        for row in records
    )) if source_verified and records_present else {}
    if not complete:
        label = "已委托记录 · 已读取范围复核" if source_verified and records_present else "已委托证据不足"
        note = f"仅代表已读取的{len(records)}笔记录" if source_verified and records_present else "来源未证明为已委托列表"
        if known_dates:
            note += f"（{read_range['earliest']}至{read_range['latest']}）"
        note += "；未证明完整覆盖全部委托历史。"
        if today:
            note += f"所见今日非终态{len(today)}笔，调整重叠条件前核对剩余委托状态。"
        if historical:
            note += f"所见历史未更新状态{len(historical)}笔，不当作今日冻结。"
        if unknown or captured is None:
            note += "部分日期、来源或状态证据不足，不能补造今日委托状态。"
        note += "此项只复核已读取委托，不改变账本现金与库存的独立推导，不计算冻结金额。"
    elif today:
        label = "今日有未完成委托"
        note = f"已观察到今日非终态{len(today)}笔；调整同标的条件前先核对剩余委托状态。"
    elif historical:
        label = "历史委托状态待更新"
        note = f"本次列表未观察到今日非终态委托；{len(historical)}笔历史记录仍显示非终态，不能当作今日冻结。"
    else:
        label = "未观察到今日非终态委托"
        note = "本次完整已委托列表仅见终态记录或为空；这是列表观测，不是券商可用资金或冻结额证明。"
    return {
        "contract": REVIEW_CONTRACT, "captured_at": payload.get("captured_at"),
        "observation_date": observed_on.isoformat() if observed_on else None,
        "label": label, "note": note, "complete": complete, "capture_complete": capture_complete,
        "observed_count": len(records) if source_verified and records_present else None,
        "status_counts": counts, "records": records, "read_range": read_range,
        "today_open_orders": today, "historical_unresolved_orders": historical, "unknown_orders": unknown,
        "historical_failure_count": observed_failures if complete else None,
        "observed_historical_failure_count": observed_failures if source_verified and records_present else None,
        "failure_summary": _failure_summary(records, source_verified and records_present, complete, read_range),
        "source_url": payload.get("source_url"), "evidence_paths": deepcopy(payload.get("evidence_paths")),
        "reservation_evidence": "NOT_DERIVED", "monitoring_is_submission": False,
    }
