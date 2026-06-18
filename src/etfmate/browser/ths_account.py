from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .session import WebAccessSession, ensure_login, require_login


THS_URL = "https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/c60MoMO"


def ths_login_check(session: WebAccessSession) -> bool:
    text = str(session.eval("document.body ? document.body.innerText : ''") or "")
    negative = ["验证码", "手机号登录", "立即登录"]
    positive = ["持仓", "资产", "成交", "盈亏"]
    return any(word in text for word in positive) and not any(word in text for word in negative)


def login(root: Path) -> None:
    with WebAccessSession(root) as session:
        ensure_login(
            session,
            THS_URL,
            ths_login_check,
            "请在 Chrome 中完成同花顺投资账本登录和验证码验证。",
        )


def collect(root: Path, out_dir: Path) -> dict:
    with WebAccessSession(root) as session:
        require_login(session, THS_URL, ths_login_check, "同花顺投资账本未登录或登录验证未完成，请在 Chrome 中手动登录后重新运行。")
        out_dir.mkdir(parents=True, exist_ok=True)
        session.screenshot(out_dir / "account_preload.png")
        time.sleep(2)
        snapshot = _wait_for_positions_snapshot(session)
        if not _position_records_from_text(str(snapshot.get("text", ""))):
            time.sleep(2)
        snapshot = _as_dict(session.eval(_SNAPSHOT_JS))
        (out_dir / "account_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "account_text.txt").write_text(str(snapshot.get("text", "")), encoding="utf-8")
        session.screenshot(out_dir / "account.png")

    records = _position_records_from_text(str(snapshot.get("text", "")))
    records.extend(_records_from_snapshot(snapshot))
    positions = _dedupe(_extract_records(records, _looks_like_position), "code", "证券代码", "symbol", "名称")
    trades = _dedupe(
        _extract_records(records, _looks_like_trade),
        "trade_id",
        "成交编号",
        "entrust_no",
        "code",
        "证券代码",
        "trade_time",
        "成交时间",
        "price",
        "成交价",
        "quantity",
        "成交数量",
    )
    return {"positions": positions, "trades": trades, "closed_positions": [], "snapshot": snapshot}


def _wait_for_positions_snapshot(session: WebAccessSession, timeout_seconds: int = 30) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest = _as_dict(session.eval(_SNAPSHOT_JS))
        if _position_records_from_text(str(latest.get("text", ""))):
            return latest
        time.sleep(1)
    return latest


def _records_from_snapshot(snapshot: dict[str, Any]) -> list[dict]:
    records: list[dict] = []
    for table in snapshot.get("tables") or []:
        headers = [str(item).strip() for item in table.get("headers") or []]
        for row in table.get("rows") or []:
            if not isinstance(row, list):
                continue
            record = {headers[idx] if idx < len(headers) and headers[idx] else f"col_{idx}": value for idx, value in enumerate(row)}
            records.append(record)
    for row_text in snapshot.get("virtualRows") or []:
        records.extend(_position_records_from_text(str(row_text)))
    for value in (snapshot.get("localStorage") or {}).values():
        records.extend(_json_records(value))
    for value in (snapshot.get("sessionStorage") or {}).values():
        records.extend(_json_records(value))
    return records


def _position_records_from_text(text: str) -> list[dict]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    records: list[dict] = []
    for idx, line in enumerate(lines):
        if not _is_code(line):
            continue
        next_idx = next((pos for pos in range(idx + 1, len(lines)) if _is_code(lines[pos]) or lines[pos] == "汇总"), len(lines))
        window = lines[idx:next_idx]
        if len(window) < 19:
            continue
        day_unit_offset = 1 if len(window) > 15 and window[15] == "天" else 0
        latest_pct_idx = 15 + day_unit_offset
        note_idx = latest_pct_idx + 8
        note = window[note_idx] if len(window) > note_idx else ""
        if _is_empty_note(note):
            note = ""
        records.append(
            {
                "code": window[0],
                "name": window[1] if len(window) > 1 else window[0],
                "market_value": window[2] if len(window) > 2 else 0,
                "daily_pnl": window[3] if len(window) > 3 else 0,
                "daily_pnl_pct": window[4] if len(window) > 4 else 0,
                "pnl": window[5] if len(window) > 5 else 0,
                "pnl_pct": window[6] if len(window) > 6 else 0,
                "position_pct": window[12] if len(window) > 12 else 0,
                "quantity": window[13] if len(window) > 13 else 0,
                "holding_days": window[14] if len(window) > 14 else 0,
                "last_price": window[latest_pct_idx + 1] if len(window) > latest_pct_idx + 1 else 0,
                "cost_price": window[latest_pct_idx + 2] if len(window) > latest_pct_idx + 2 else 0,
                "note": note,
                "raw_text": "\n".join(window),
            }
        )
    return records


def _is_empty_note(value: str) -> bool:
    text = str(value or "").strip()
    return not text or text == "--" or bool(re.fullmatch(r"[+-]?\d+(?:\.\d+)?%?", text))


def _json_records(value: Any) -> list[dict]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return _walk_records(value, lambda item: True)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            return {"text": value}
    return {"value": value}


def _extract_records(records: list[dict], predicate) -> list[dict]:
    result: list[dict] = []
    for record in records:
        result.extend(_walk_records(record, predicate))
    return result


def _walk_records(value: Any, predicate) -> list[dict]:
    found: list[dict] = []
    if isinstance(value, dict):
        if predicate(value):
            found.append(value)
        for child in value.values():
            found.extend(_walk_records(child, predicate))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_records(child, predicate))
    return found


def _looks_like_position(item: dict) -> bool:
    keys = set(item)
    has_code = any(_is_code(item.get(key)) for key in ("code", "symbol", "stockCode", "zqdm", "证券代码", "代码"))
    has_quantity = any(key in keys for key in ("quantity", "amount", "holdAmount", "current_amount", "持仓数量", "持有数量", "股份余额"))
    has_value = any(key in keys for key in ("market_value", "marketValue", "市值", "持仓市值", "参考市值"))
    return has_code and has_quantity and has_value and "基金" not in str(item.get("type", ""))


def _looks_like_trade(item: dict) -> bool:
    keys = set(item)
    has_code = any(_is_code(item.get(key)) for key in ("code", "symbol", "stockCode", "zqdm", "证券代码", "代码"))
    has_side = any(key in keys for key in ("side", "bsFlag", "business_name", "买卖方向", "方向"))
    has_price = any(key in keys for key in ("price", "dealPrice", "成交价", "成交价格"))
    return has_code and has_side and has_price


def _is_code(value: Any) -> bool:
    return bool(re.fullmatch(r"(sh|sz)?\d{6}", str(value or "").strip().lower()))


def _dedupe(items: list[dict], *keys: str) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for item in items:
        identity = "|".join(str(item.get(key, "")) for key in keys if item.get(key) not in (None, ""))
        if not identity:
            identity = json.dumps(item, ensure_ascii=False, sort_keys=True)[:500]
        if identity in seen:
            continue
        seen.add(identity)
        result.append(item)
    return result


_SNAPSHOT_JS = r"""
(() => {
  const text = document.body ? document.body.innerText : "";
  const tables = Array.from(document.querySelectorAll("table,[role='table']")).map((table) => {
    const rows = Array.from(table.querySelectorAll("tr,[role='row']")).map((row) =>
      Array.from(row.querySelectorAll("th,td,[role='columnheader'],[role='cell']")).map((cell) => cell.innerText.trim())
    ).filter((row) => row.length);
    return { headers: rows[0] || [], rows: rows.slice(1) };
  }).filter((table) => table.rows.length);
  const storage = (source) => Object.fromEntries(Array.from({ length: source.length }, (_, i) => {
    const key = source.key(i);
    return [key, source.getItem(key)];
  }).filter(([key]) => key));
  const virtualRows = Array.from(document.querySelectorAll("div,section,li,[role='row']"))
    .map((el) => el.innerText ? el.innerText.trim() : "")
    .filter((value) => /(^|\n)(?:sh|sz)?\d{6}(\n|$)/i.test(value))
    .slice(0, 500);
  return JSON.stringify({
    url: location.href,
    title: document.title,
    text,
    tables,
    virtualRows,
    localStorage: storage(localStorage),
    sessionStorage: storage(sessionStorage),
  });
})()
"""
