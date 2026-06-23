from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .session import WebAccessSession, ensure_login, require_login


THS_POSITION_URL = "https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/c60MoMO"
THS_WATCHLIST_URL = "https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/ISUeEwK"
THS_URL = THS_POSITION_URL
THS_POSITION_TAB = "持仓列表"
THS_CLOSED_TAB = "已清仓"
THS_TRADES_TAB = "交易记录"
THS_TRADE_RANGE_TABS = ("本月", "近三月", "近半年", "今年", "自定义")


def ths_login_check(session: WebAccessSession) -> bool:
    text = str(session.eval("document.body ? document.body.innerText : ''") or "")
    negative = ["验证码", "手机号登录", "立即登录"]
    positive = ["持仓", "资产", "成交", "盈亏", "自选", "添加"]
    return any(word in text for word in positive) and not any(word in text for word in negative)


def login(root: Path) -> None:
    with WebAccessSession(root) as session:
        ensure_login(
            session,
            THS_POSITION_URL,
            ths_login_check,
            "请在 Chrome 中完成同花顺投资账本登录和验证码验证。",
        )


def collect(root: Path, out_dir: Path) -> dict:
    with WebAccessSession(root) as session:
        require_login(session, THS_POSITION_URL, ths_login_check, "同花顺投资账本未登录或登录验证未完成，请在 Chrome 中手动登录后重新运行。")
        out_dir.mkdir(parents=True, exist_ok=True)
        session.screenshot(out_dir / "account_preload.png")
        time.sleep(2)
        snapshot = _collect_tab_snapshot(session, THS_POSITION_TAB, out_dir / "positions")
        (out_dir / "account_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "account_text.txt").write_text(str(snapshot.get("text", "")), encoding="utf-8")
        session.screenshot(out_dir / "account.png")

        closed_snapshot = _collect_tab_snapshot(session, THS_CLOSED_TAB, out_dir / "closed_positions")

        trade_snapshots: dict[str, dict[str, Any]] = {}
        _click_tab(session, THS_TRADES_TAB)
        for range_tab in THS_TRADE_RANGE_TABS:
            trade_snapshots[range_tab] = _collect_tab_snapshot(session, range_tab, out_dir / f"trades_{_safe_name(range_tab)}")

        session.navigate(THS_WATCHLIST_URL)
        time.sleep(2)
        session.screenshot(out_dir / "watchlist_preload.png")
        watchlist_snapshot = _collect_scroll_loaded_snapshot(session, "自选ETF池")
        (out_dir / "watchlist_snapshot.json").write_text(json.dumps(watchlist_snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "watchlist_text.txt").write_text(str(watchlist_snapshot.get("text", "")), encoding="utf-8")
        session.screenshot(out_dir / "watchlist.png")
        (out_dir / "ths_tabs_snapshot.json").write_text(
            json.dumps(
                {
                    "positions": snapshot,
                    "closed_positions": closed_snapshot,
                    "trade_records": trade_snapshots,
                    "watchlist": watchlist_snapshot,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    records = _position_records_from_text(str(snapshot.get("text", "")))
    records.extend(_records_from_snapshot(snapshot))
    closed_records = _records_from_snapshot(closed_snapshot)
    trade_records: list[dict] = []
    for trade_snapshot in trade_snapshots.values():
        trade_records.extend(_records_from_snapshot(trade_snapshot))
    positions = _dedupe(_extract_records(records, _looks_like_position), "code", "证券代码", "symbol", "名称")
    trades = _dedupe(
        _extract_records(trade_records, _looks_like_trade),
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
    closed_positions = _dedupe(_extract_records(closed_records, _looks_like_closed_position), "code", "证券代码", "symbol", "名称")
    watchlist, filtered = extract_watchlist(watchlist_snapshot)
    watchlist_source_url = str(watchlist_snapshot.get("url") or THS_WATCHLIST_URL)
    return {
        "positions": positions,
        "trades": trades,
        "closed_positions": closed_positions,
        "watchlist": watchlist,
        "watchlist_filtered_out": filtered,
        "watchlist_stats": {
            "included": len(watchlist),
            "filtered": len(filtered),
            "source_url": watchlist_source_url,
            "canonical_url": THS_WATCHLIST_URL,
            "note": "仅从同花顺投资账本自选页提取 ETF 池；排除持仓缓存，按 ETF/LOF/场内基金规则过滤",
        },
        "snapshot": snapshot,
        "closed_snapshot": closed_snapshot,
        "trade_snapshots": trade_snapshots,
        "watchlist_snapshot": watchlist_snapshot,
    }


def extract_watchlist(snapshot: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    candidates = _watchlist_candidates_from_snapshot(snapshot)
    included: list[dict] = []
    filtered: list[dict] = []
    for item in _dedupe(candidates, "code", "name", "source_key"):
        normalized = _normalize_watch_candidate(item)
        if not normalized:
            continue
        keep, reason = _watch_item_filter(normalized)
        normalized["include_reason" if keep else "filter_reason"] = reason
        if keep:
            normalized["source"] = "ths_watchlist"
            included.append(normalized)
        else:
            filtered.append(normalized)
    return _dedupe(included, "code"), _dedupe(filtered, "code", "filter_reason")


def _collect_tab_snapshot(session: WebAccessSession, tab_label: str, evidence_dir: Path) -> dict[str, Any]:
    clicked = _click_tab(session, tab_label)
    snapshot = _collect_scroll_loaded_snapshot(session, tab_label)
    snapshot["tab_label"] = tab_label
    snapshot["tab_clicked"] = clicked
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    (evidence_dir / "text.txt").write_text(str(snapshot.get("text", "")), encoding="utf-8")
    session.screenshot(evidence_dir / "screen.png")
    return snapshot


def _click_tab(session: WebAccessSession, tab_label: str, timeout_seconds: int = 20) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = session.eval(_click_tab_js(tab_label))
        if str(result).lower() in {"true", "1"} or result is True:
            time.sleep(1)
            return True
        time.sleep(0.5)
    raise RuntimeError(f"同花顺页面未找到或无法点击 tab：{tab_label}")


def _collect_scroll_loaded_snapshot(session: WebAccessSession, label: str, max_steps: int = 36) -> dict[str, Any]:
    snapshots: list[dict[str, Any]] = []
    seen_signatures: set[str] = set()
    stable_steps = 0
    latest: dict[str, Any] = {}
    for step in range(max_steps):
        latest = _as_dict(session.eval(_SNAPSHOT_JS))
        latest["scroll_step"] = step
        signature = _snapshot_signature(latest)
        if signature in seen_signatures:
            stable_steps += 1
        else:
            stable_steps = 0
            seen_signatures.add(signature)
            snapshots.append(latest)
        scroll_result = _as_dict(session.eval(_SCROLL_JS))
        if not scroll_result.get("moved") and stable_steps >= 2:
            break
        time.sleep(0.35)
    if not snapshots:
        snapshots.append(latest)
    merged = _merge_snapshots(snapshots)
    merged["scroll_label"] = label
    merged["scroll_steps"] = len(snapshots)
    return merged


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
        records.extend(_trade_records_from_text(str(row_text)))
    records.extend(_trade_records_from_text(str(snapshot.get("text") or "")))
    for value in (snapshot.get("localStorage") or {}).values():
        records.extend(_json_records(value))
    for value in (snapshot.get("sessionStorage") or {}).values():
        records.extend(_json_records(value))
    return records


def _watchlist_candidates_from_snapshot(snapshot: dict[str, Any]) -> list[dict]:
    candidates: list[dict] = []
    candidates.extend(_watchlist_storage_records(snapshot.get("localStorage") or {}, "localStorage"))
    candidates.extend(_watchlist_storage_records(snapshot.get("sessionStorage") or {}, "sessionStorage"))
    candidates.extend(_watchlist_records_from_text(str(snapshot.get("text") or ""), "page_text"))
    for row_text in snapshot.get("virtualRows") or []:
        candidates.extend(_watchlist_records_from_text(str(row_text), "virtual_row"))
    for item in snapshot.get("watchNodes") or []:
        if isinstance(item, dict):
            candidates.extend(_watchlist_records_from_text(str(item.get("text") or ""), str(item.get("source") or "dom_node")))
    return candidates


def _watchlist_storage_records(storage: dict[str, Any], source: str) -> list[dict]:
    records: list[dict] = []
    for key, value in storage.items():
        source_key = f"{source}:{key}"
        key_text = str(key).lower()
        if is_position_cache_source_key(source_key):
            continue
        parsed = _json_value(value)
        key_suggests_watchlist = any(
            token in key_text
            for token in (
                "自选",
                "watch",
                "optional",
                "favorite",
                "fav",
                "self",
                "stock_item",
            )
        )
        for item in _walk_records(parsed, _looks_like_watch_candidate):
            enriched = dict(item)
            enriched.setdefault("source_key", source_key)
            if key_suggests_watchlist or _fund_like_code_or_name(enriched):
                records.append(enriched)
    return records


def is_position_cache_source_key(value: Any) -> bool:
    text = str(value or "").lower()
    return any(token in text for token in ("defaultpositioin", "defaultposition", "positionlist"))


def _watchlist_records_from_text(text: str, source_key: str) -> list[dict]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    records: list[dict] = []
    for idx, line in enumerate(lines):
        if not _is_code(line):
            continue
        name = ""
        if idx + 1 < len(lines) and not _is_code(lines[idx + 1]) and not _looks_like_number(lines[idx + 1]):
            name = lines[idx + 1]
        records.append({"code": line, "name": name or line, "source_key": source_key})
    return records


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _looks_like_watch_candidate(item: dict) -> bool:
    code = _pick_value(item, "code", "symbol", "stockCode", "securityCode", "stock_code", "zqdm", "证券代码", "代码")
    name = _pick_value(item, "name", "stock_name", "securityName", "stockName", "证券名称", "名称")
    return _is_code(code) and bool(str(name or "").strip())


def _normalize_watch_candidate(item: dict) -> dict | None:
    code = _normalize_code(_pick_value(item, "code", "symbol", "stockCode", "securityCode", "stock_code", "zqdm", "证券代码", "代码"))
    if not code:
        return None
    name = str(_pick_value(item, "name", "stock_name", "securityName", "stockName", "证券名称", "名称", default=code)).strip() or code
    return {
        "code": code,
        "name": name,
        "raw_type": str(_pick_value(item, "type", "market", "securityType", "assetType", default="") or ""),
        "source_key": str(item.get("source_key") or ""),
    }


def _watch_item_filter(item: dict) -> tuple[bool, str]:
    code = str(item.get("code") or "")
    name = str(item.get("name") or "")
    text = f"{name} {item.get('raw_type') or ''}"
    if not code:
        return False, "缺少代码"
    if _is_convertible_bond(code, text):
        return False, "过滤可转债"
    if _looks_like_hk_stock(code, text):
        return False, "过滤港股股票；跨境 ETF 需使用 A 股场内基金代码"
    if _looks_like_otc_fund(code):
        return False, "过滤场外基金/ETF-FOF；仅保留交易所场内基金代码段"
    if _is_fund_code(code):
        return True, "场内基金代码段，保留 ETF/LOF/场内基金"
    if any(word in text.upper() for word in ("ETF", "LOF", "REIT")) or any(word in text for word in ("基金", "场内基金")):
        if _is_a_share_stock_code(code):
            return False, "名称像基金但代码是 A 股股票段，需人工确认后再纳入"
        return True, "名称包含 ETF/LOF/基金"
    if _is_a_share_stock_code(code):
        return False, "过滤 A 股股票"
    return False, "非 ETF/LOF/场内基金代码段"


def _fund_like_code_or_name(item: dict) -> bool:
    code = _normalize_code(_pick_value(item, "code", "symbol", "stockCode", "securityCode", "stock_code", "zqdm", "证券代码", "代码"))
    name = str(_pick_value(item, "name", "stock_name", "securityName", "stockName", "证券名称", "名称", default=""))
    return bool(code and (_is_fund_code(code) or any(word in name.upper() for word in ("ETF", "LOF", "REIT")) or "基金" in name))


def _is_fund_code(code: str) -> bool:
    return bool(re.fullmatch(r"\d{6}", code)) and code[:2] in {"15", "16", "50", "51", "52", "56", "58"}


def _is_a_share_stock_code(code: str) -> bool:
    return bool(re.fullmatch(r"\d{6}", code)) and code[:3] in {"000", "001", "002", "003", "300", "301", "600", "601", "603", "605", "688", "689"}


def _looks_like_otc_fund(code: str) -> bool:
    return bool(re.fullmatch(r"\d{6}", code)) and code[:2] in {"00", "01", "02"}


def _is_convertible_bond(code: str, text: str) -> bool:
    return code[:2] in {"11", "12"} or code[:3] in {"123", "127", "128"} or any(word in text for word in ("转债", "可转债"))


def _looks_like_hk_stock(code: str, text: str) -> bool:
    raw = str(code or "").lower()
    if raw.startswith("hk") or re.fullmatch(r"\d{5}", raw):
        return True
    return bool(not _is_fund_code(code) and any(word in text for word in ("港股", "港交所", "HK")))


def _normalize_code(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^(sh|sz)", "", text)
    text = re.sub(r"\.(sh|sz)$", "", text)
    return text if re.fullmatch(r"\d{6}", text) else ""


def _pick_value(raw: dict, *names: str, default: Any = None) -> Any:
    for name in names:
        if name in raw and raw[name] not in (None, ""):
            return raw[name]
    return default


def _looks_like_number(value: str) -> bool:
    return bool(re.fullmatch(r"[+-]?\d+(?:\.\d+)?%?", str(value or "").replace(",", "")))


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


def _looks_like_closed_position(item: dict) -> bool:
    text = json.dumps(item, ensure_ascii=False)
    has_code = any(_is_code(item.get(key)) for key in ("code", "symbol", "stockCode", "zqdm", "证券代码", "代码"))
    has_closed_text = any(word in text for word in ("清仓", "已清仓", "累计盈亏", "清仓收益", "卖出", "收益率"))
    return has_code and has_closed_text


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


def _trade_records_from_text(text: str) -> list[dict]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    records: list[dict] = []
    for idx, line in enumerate(lines):
        if not _is_code(line):
            continue
        next_idx = next((pos for pos in range(idx + 1, len(lines)) if _is_code(lines[pos])), min(len(lines), idx + 16))
        window = lines[idx:next_idx]
        block = "\n".join(window)
        side_idx = next((pos for pos, item in enumerate(window) if item in {"买入", "卖出", "申购", "赎回"}), -1)
        if side_idx < 0:
            continue
        numeric_fields = [
            item.replace(",", "").replace("%", "")
            for item in window[side_idx + 1 :]
            if _looks_like_number(item)
        ]
        if len(numeric_fields) < 3:
            continue
        side = window[side_idx]
        date_match = re.search(r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}", block)
        if not date_match:
            continue
        time_match = re.search(r"\d{1,2}:\d{2}(?::\d{2})?", block)
        records.append(
            {
                "code": _normalize_code(line),
                "name": window[1] if len(window) > 1 and not _looks_like_number(window[1]) else line,
                "side": side,
                "trade_date": date_match.group(0).replace("/", "-").replace(".", "-") if date_match else "",
                "trade_time": time_match.group(0) if time_match else "",
                "price": numeric_fields[0],
                "quantity": numeric_fields[1],
                "amount": numeric_fields[2],
                "fee": numeric_fields[3] if len(numeric_fields) > 3 else "",
                "raw_text": block,
            }
        )
    return records


def _snapshot_signature(snapshot: dict[str, Any]) -> str:
    text = str(snapshot.get("text") or "")
    code_count = len(re.findall(r"(?<!\d)(?:sh|sz)?\d{6}(?!\d)", text, flags=re.I))
    table_rows = sum(len(table.get("rows") or []) for table in snapshot.get("tables") or [] if isinstance(table, dict))
    return f"{code_count}:{table_rows}:{len(snapshot.get('virtualRows') or [])}:{len(snapshot.get('watchNodes') or [])}:{len(text)}"


def _merge_snapshots(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    latest = snapshots[-1]
    text_parts = _dedupe_text([str(item.get("text") or "") for item in snapshots])
    tables: list[dict] = []
    virtual_rows: list[str] = []
    watch_nodes: list[dict] = []
    for item in snapshots:
        tables.extend(item.get("tables") or [])
        virtual_rows.extend(str(row) for row in item.get("virtualRows") or [])
        watch_nodes.extend(node for node in item.get("watchNodes") or [] if isinstance(node, dict))
    return {
        **latest,
        "text": "\n".join(text_parts),
        "tables": _dedupe(tables, "headers", "rows"),
        "virtualRows": _dedupe_text(virtual_rows),
        "watchNodes": _dedupe(watch_nodes, "source", "text"),
        "scroll_snapshots": snapshots,
    }


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _safe_name(value: str) -> str:
    mapping = {"本月": "this_month", "近三月": "last_3_months", "近半年": "last_6_months", "今年": "this_year", "自定义": "custom"}
    return mapping.get(value, re.sub(r"\W+", "_", value))


def _click_tab_js(label: str) -> str:
    label_json = json.dumps(label, ensure_ascii=False)
    return f"""
(() => {{
  const label = {label_json};
  const visible = (el) => {{
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  }};
  const candidates = Array.from(document.querySelectorAll("button,[role='tab'],a,li,span,div"))
    .filter((el) => visible(el))
    .map((el) => ({{ el, text: (el.innerText || el.textContent || "").trim().replace(/\\s+/g, "") }}))
    .filter((item) => item.text && (item.text === label || item.text.includes(label)))
    .sort((a, b) => a.text.length - b.text.length);
  const target = candidates[0] && candidates[0].el;
  if (!target) return false;
  target.scrollIntoView({{ block: "center", inline: "center" }});
  target.click();
  return true;
}})()
"""


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
  const watchNodes = Array.from(document.querySelectorAll("[class*='optional'],[class*='watch'],[class*='self'],[class*='stock'],[class*='fund'],div,li"))
    .map((el) => ({ source: el.className ? String(el.className).slice(0, 120) : el.tagName, text: el.innerText ? el.innerText.trim() : "" }))
    .filter((item) => item.text && /(?:自选|ETF|LOF|基金|(?:^|\n)(?:sh|sz)?\d{6}(?:\n|$))/i.test(item.text))
    .slice(0, 500);
  return JSON.stringify({
    url: location.href,
    title: document.title,
    text,
    tables,
    virtualRows,
    watchNodes,
    localStorage: storage(localStorage),
    sessionStorage: storage(sessionStorage),
  });
})()
"""

_SCROLL_JS = r"""
(() => {
  const beforeY = window.scrollY || document.documentElement.scrollTop || 0;
  const candidates = Array.from(document.querySelectorAll("*"))
    .filter((el) => {
      const style = getComputedStyle(el);
      return style.display !== "none" && style.visibility !== "hidden" && el.scrollHeight > el.clientHeight + 40;
    })
    .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
  let moved = false;
  const details = [];
  for (const el of candidates.slice(0, 8)) {
    const before = el.scrollTop;
    const delta = Math.max(360, Math.floor(el.clientHeight * 0.85));
    el.scrollTop = Math.min(el.scrollHeight - el.clientHeight, el.scrollTop + delta);
    el.dispatchEvent(new Event("scroll", { bubbles: true }));
    el.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: delta }));
    if (el.scrollTop !== before) moved = true;
    details.push({ tag: el.tagName, className: String(el.className || "").slice(0, 80), before, after: el.scrollTop, max: el.scrollHeight - el.clientHeight });
  }
  window.scrollBy(0, Math.max(360, Math.floor(window.innerHeight * 0.85)));
  const afterY = window.scrollY || document.documentElement.scrollTop || 0;
  if (afterY !== beforeY) moved = true;
  return JSON.stringify({ moved, windowY: afterY, containers: details });
})()
"""
