from __future__ import annotations

import json
import math
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

        _click_tab(session, THS_CLOSED_TAB)
        closed_snapshot = _collect_range_snapshot(session, THS_CLOSED_TAB, "全部", out_dir / "closed_positions")

        trade_snapshots: dict[str, dict[str, Any]] = {}
        _click_tab(session, THS_TRADES_TAB)
        for range_tab in THS_TRADE_RANGE_TABS:
            trade_snapshots[range_tab] = _collect_range_snapshot(
                session, THS_TRADES_TAB, range_tab, out_dir / f"trades_{_safe_name(range_tab)}")

        end_snapshot = _collect_tab_snapshot(session, THS_POSITION_TAB, out_dir / "positions_end")
        consistency = _collection_consistency(snapshot, end_snapshot)
        (out_dir / "collection_consistency.json").write_text(
            json.dumps(consistency, ensure_ascii=False, indent=2), encoding="utf-8")
        if consistency["status"] != "PASS":
            raise RuntimeError(f"同花顺采集前后持仓/现金不一致，不能混用交易与持仓，请重新采集：{consistency['reason']}")

        (out_dir / "ths_tabs_snapshot.json").write_text(
            json.dumps(
                {
                    "positions": snapshot,
                    "closed_positions": closed_snapshot,
                    "trade_records": trade_snapshots,
                    "positions_end": end_snapshot,
                    "collection_consistency": consistency,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    positions = _positions_from_snapshot(snapshot)
    account_summary = _account_summary_from_snapshot(snapshot, positions)
    trades, trade_collection_quality = _merge_trade_snapshots(trade_snapshots)
    closed_positions = _closed_positions_from_snapshot(closed_snapshot)
    return {
        "positions": positions,
        "account_summary": account_summary,
        "trades": trades,
        "trade_collection_quality": trade_collection_quality,
        "closed_positions": closed_positions,
        "snapshot": snapshot,
        "closed_snapshot": closed_snapshot,
        "trade_snapshots": trade_snapshots,
        "end_snapshot": end_snapshot,
        "collection_consistency": consistency,
    }


def _positions_from_snapshot(snapshot: dict) -> list[dict]:
    records = _position_records_from_text(str(snapshot.get("text", "")))
    records.extend(_records_from_snapshot(snapshot))
    return _dedupe(_extract_records(records, _looks_like_position), "code", "证券代码", "symbol", "名称")


def _collection_consistency(start: dict, end: dict) -> dict:
    """Prices may move while collecting; quantity and ledger cash must stay fixed."""
    def fingerprint(snapshot: dict) -> dict:
        positions = _positions_from_snapshot(snapshot)
        quantities = {
            _normalize_code(_pick_value(p, "code", "证券代码", "symbol")):
            _to_number(_pick_value(p, "quantity", "持仓数量", "持有数量", default=None))
            for p in positions
        }
        match = re.search(r"现金余额\s*[:：]?\s*([+-]?\d[\d,]*(?:\.\d+)?)", str(snapshot.get("text", "")))
        cash = _to_number(match[1]) if match else None
        return {"quantities": quantities, "cash": cash}
    before, after = fingerprint(start), fingerprint(end)
    valid = all(item["quantities"] and item["cash"] is not None and math.isfinite(item["cash"])
                and all(math.isfinite(q) and q > 0 for q in item["quantities"].values())
                for item in (before, after))
    equal = before == after
    return {"status": "PASS" if valid and equal else "FAIL", "start": before, "end": after,
            "reason": "数量与现金余额一致；不要求盘中市值相同" if valid and equal else
                      "缺少前后有效持仓/现金证据" if not valid else "采集期间数量或现金余额发生变化"}


def _closed_positions_from_snapshot(snapshot: dict) -> list[dict]:
    """Keep separate closed cycles of the same instrument, including virtual rows."""
    texts = [str(snapshot.get("text") or "")]
    texts.extend("\n".join(map(str, row)) for table in snapshot.get("tables") or []
                 for row in table.get("rows") or [] if isinstance(row, list))
    records = []
    date_pattern = re.compile(r"20\d{2}-\d{2}-\d{2}")
    for text in texts:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for idx, value in enumerate(lines):
            if not _is_code(value) or idx == 0 or not date_pattern.fullmatch(lines[idx - 1]):
                continue
            window = lines[idx:idx + 13]
            if len(window) < 12 or not _looks_like_number(window[2]) or not date_pattern.fullmatch(window[11]):
                continue
            records.append({"code": value, "name": window[1], "close_date": lines[idx - 1],
                            "open_date": window[11], "total_pnl": window[2], "pnl_pct": window[3],
                            "buy_average_price": window[6], "sell_average_price": window[7],
                            "holding_days": window[9], "fee": window[10],
                            "note": window[12] if len(window) > 12 and window[12] != "--" else "",
                            "source": "ths_closed_cycle", "raw_text": "\n".join([lines[idx - 1], *window])})
    return _dedupe(records, "code", "open_date", "close_date", "total_pnl", "fee")


def _trade_identity(item: dict) -> tuple[str, bool]:
    trade_id = _pick_value(item, "trade_id", "成交编号", default=None)
    code = _normalize_code(_pick_value(item, "code", "symbol", "stockCode", "zqdm", "证券代码", "代码"))
    if trade_id not in (None, ""):
        return f"trade_id:{code}:{trade_id}", True
    date = str(_pick_value(item, "trade_date", "成交日期", default="")).replace("/", "-").replace(".", "-")
    side = str(_pick_value(item, "side", "bsFlag", "business_name", "买卖方向", "方向", "类型", default=""))
    stamp = str(_pick_value(item, "trade_time", "成交时间", default=""))
    price = _to_number(_pick_value(item, "price", "dealPrice", "成交价", "成交价格"))
    quantity = _to_number(_pick_value(item, "quantity", "dealAmount", "成交数量"))
    return f"fields:{code}:{date}:{side}:{stamp}:{price:.12g}:{quantity:.12g}", False


def _screen_trade_groups(snapshot: dict) -> list[tuple[str, list[dict]]]:
    """Prefer table rows, which preserve within-screen transaction multiplicity."""
    groups: list[tuple[str, list[dict]]] = []
    for table_index, table in enumerate(snapshot.get("tables") or []):
        headers = [str(value).strip() for value in table.get("headers") or []]
        parsed = []
        for row_index, row in enumerate(table.get("rows") or []):
            if not isinstance(row, list):
                continue
            structured = {headers[index]: value for index, value in enumerate(row) if index < len(headers)}
            if _looks_like_trade(structured):
                rows = [{**structured,
                         "code": _normalize_code(_pick_value(structured, "code", "symbol", "stockCode", "zqdm", "证券代码", "代码")),
                         "name": _pick_value(structured, "name", "证券名称", "名称", default=""),
                         "trade_date": _pick_value(structured, "trade_date", "成交日期", default=""),
                         "trade_time": _pick_value(structured, "trade_time", "成交时间", default=""),
                         "side": _pick_value(structured, "side", "bsFlag", "business_name", "买卖方向", "方向", "类型", default=""),
                         "price": _pick_value(structured, "price", "dealPrice", "成交价", "成交价格", default=None),
                         "quantity": _pick_value(structured, "quantity", "dealAmount", "成交数量", default=None),
                         "amount": _pick_value(structured, "amount", "dealBalance", "成交金额", default=None),
                         "fee": _pick_value(structured, "fee", "交易费用", "手续费", default=None)}]
            else:
                rows = _trade_records_from_text("\n".join(str(value) for value in row))
            parsed.extend({**item, "source_row_index": row_index} for item in rows)
        if parsed:
            groups.append((f"table:{table_index}", parsed))
    if groups:
        return groups
    return [("text", [{**item, "source_row_index": index}
                       for index, item in enumerate(_trade_records_from_text(str(snapshot.get("text") or "")))])]


def _merge_trade_snapshots(snapshots: dict[str, dict]) -> tuple[list[dict], dict]:
    """Take observed multiplicity, never globally set-dedupe identical fills.

    Without execution IDs, a repeated key across scrolling screens cannot prove
    whether the rows are different fills. Keep the maximum observed count as a
    lower bound and expose that ambiguity; do not infer extra trades.
    """
    merged: dict[str, list[dict]] = {}
    sources: dict[str, list[dict]] = {}
    ambiguities: dict[str, set[str]] = {}
    for view, snapshot in snapshots.items():
        screens = snapshot.get("scroll_snapshots") or [snapshot]
        seen_screens: dict[str, set[int]] = {}
        for screen_index, screen in enumerate(screens):
            for representation, rows in _screen_trade_groups(screen):
                grouped: dict[str, list[dict]] = {}
                for item in rows:
                    key, verified_id = _trade_identity(item)
                    grouped.setdefault(key, []).append(item)
                    source = {"view": view, "screen": screen_index,
                              "representation": representation, "row_index": item["source_row_index"]}
                    sources.setdefault(key, []).append(source)
                    if not verified_id:
                        seen_screens.setdefault(key, set()).add(screen_index)
                        if representation == "text" and not snapshot.get("scroll_snapshots") and (snapshot.get("scroll_steps") or 0) > 1:
                            ambiguities.setdefault(key, set()).add(f"{view}:只有合并文本，无法区分真实重复与滚动重叠")
                for key, items in grouped.items():
                    if key.startswith("trade_id:"):
                        items = items[:1]
                    elif representation == "text" and len(items) > 1:
                        ambiguities.setdefault(key, set()).add(f"{view}:仅页面文本存在同键重复，缺少独立表格行归属")
                        items = items[:1]
                    elif representation == "text" and key in ambiguities and not snapshot.get("scroll_snapshots"):
                        # A merged text can duplicate the same row arbitrarily.
                        items = items[:1]
                    if len(items) > len(merged.get(key, [])):
                        merged[key] = items
        for key, indexes in seen_screens.items():
            if len(indexes) > 1:
                ambiguities.setdefault(key, set()).add(f"{view}:同键出现在多个滚动屏，实际笔数仅有已观察下限")
    # An execution with an ID may also appear in another view without its ID.
    # Count the maximum observed multiplicity, not identified + anonymous rows.
    identified: dict[str, list[str]] = {}
    for key, rows in merged.items():
        if key.startswith("trade_id:"):
            anonymous = {name: value for name, value in rows[0].items() if name not in {"trade_id", "成交编号"}}
            economic_key, _ = _trade_identity(anonymous)
            identified.setdefault(economic_key, []).append(key)
    for key, execution_keys in identified.items():
        if key not in merged:
            continue
        for execution_key in execution_keys:
            sources[execution_key].extend(sources[key])
        remaining = max(0, len(merged[key]) - len(execution_keys))
        merged[key] = merged[key][:remaining]
    trades = []
    for key, rows in merged.items():
        for ordinal, item in enumerate(rows, start=1):
            trades.append({**item, "source_occurrence_key": key, "source_occurrence_ordinal": ordinal,
                           "source_evidence": sources[key], "occurrence_ambiguous": key in ambiguities})
    return trades, {
        "merge_contract": "trade_view_occurrences_v1", "cycle_complete": False,
        "count_basis": "max_observed_occurrences_per_key_across_views",
        "ambiguities": [{"key": key, "reasons": sorted(reasons)} for key, reasons in ambiguities.items()],
        "note": "列表采集与持仓完整周期分别核验；无成交编号的跨屏同键记录只保留已观察笔数下限。",
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
    evidence_dir.mkdir(parents=True, exist_ok=True)
    # Background virtual lists can defer painting until a browser capture.
    session.screenshot(evidence_dir / "selected.png")
    snapshot = _collect_scroll_loaded_snapshot(session, tab_label)
    snapshot["tab_label"] = tab_label
    snapshot["tab_clicked"] = clicked
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    (evidence_dir / "text.txt").write_text(str(snapshot.get("text", "")), encoding="utf-8")
    session.screenshot(evidence_dir / "screen.png")
    return snapshot


def _collect_range_snapshot(session: WebAccessSession, tab_label: str, range_label: str,
                            evidence_dir: Path, timeout_seconds: float = 15) -> dict[str, Any]:
    scope = ".position_clear_list" if tab_label == THS_CLOSED_TAB else ".trade_history_list_top_tool_box"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    clicked = session.eval(_click_date_range_js(scope, range_label))
    if clicked is not True:
        raise RuntimeError(f"同花顺{tab_label}未找到可点击的时间范围：{range_label}")
    custom_dates = None
    if range_label == "自定义":
        # Opening the date controls does not submit a query. Keep and disclose
        # the real UI dates, instead of pretending an unsubmitted edit applied.
        state = _wait_range_state(session, scope, range_label, timeout_seconds, require_ready=False)
        custom_dates = state.get("custom_dates")
        if not isinstance(custom_dates, list) or len(custom_dates) != 2 or not all(
                re.fullmatch(r"(?:19|20)\d{2}-\d{2}-\d{2}", str(value)) for value in custom_dates):
            raise RuntimeError("同花顺自定义交易区间缺少两个真实日期")
        if custom_dates[0] > custom_dates[1]:
            raise RuntimeError("同花顺自定义交易区间起止日期倒置")
        query_clicked = session.eval(f"""(() => {{
          const root = document.querySelector({json.dumps(scope)});
          const query = root && root.querySelector('.buttons_find_custom_button');
          if (!query || query.textContent.trim() !== '查询') return false;
          query.click(); return true;
        }})()""")
        if query_clicked is not True:
            raise RuntimeError("同花顺自定义区间未实际提交查询")
    session.screenshot(evidence_dir / "filter_selected.png")
    before = _wait_range_state(session, scope, range_label, timeout_seconds, custom_dates=custom_dates)
    snapshot = _collect_scroll_loaded_snapshot(session, f"{tab_label}:{range_label}")
    after = _as_dict(session.eval(_date_range_state_js(scope)))
    if not _range_state_matches(after, range_label, custom_dates, require_ready=True):
        raise RuntimeError(f"同花顺{tab_label}采集期间时间范围改变或数据未就绪：{range_label}")
    snapshot.update({"tab_label": tab_label, "tab_clicked": True, "range_filter": {
        "contract": "ths_date_range_v1", "requested": range_label, "selected": after["selected"],
        "verified": True, "query_submitted": range_label == "自定义",
        "custom_dates": custom_dates, "before": before, "after": after,
        "note": "已验证实际选中态；列表范围不等于完整持仓周期。",
    }})
    (evidence_dir / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    (evidence_dir / "text.txt").write_text(str(snapshot.get("text", "")), encoding="utf-8")
    session.screenshot(evidence_dir / "screen.png")
    return snapshot


def _range_state_matches(state: dict, label: str, custom_dates: list | None,
                         require_ready: bool) -> bool:
    return (state.get("selected") == label and
            (custom_dates is None or state.get("custom_dates") == custom_dates) and
            (not require_ready or state.get("ready") is True))


def _wait_range_state(session: WebAccessSession, scope: str, label: str, timeout_seconds: float,
                      custom_dates: list | None = None, require_ready: bool = True) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while True:
        state = _as_dict(session.eval(_date_range_state_js(scope)))
        if _range_state_matches(state, label, custom_dates, require_ready):
            return state
        if time.monotonic() >= deadline:
            raise RuntimeError(f"同花顺时间筛选未生效或列表未就绪：请求{label}，实际{state.get('selected')}，状态{state}")
        time.sleep(0.25)


def _click_date_range_js(scope: str, label: str) -> str:
    return f"""(() => {{
      const root = document.querySelector({json.dumps(scope)});
      const item = root && Array.from(root.querySelectorAll('.buttons_date_picker_box_button_item'))
        .find(el => el.textContent.trim() === {json.dumps(label, ensure_ascii=False)});
      if (!item) return false;
      item.scrollIntoView({{block:'center'}}); item.click(); return true;
    }})()"""


def _date_range_state_js(scope: str) -> str:
    return f"""(() => {{
      const root = document.querySelector({json.dumps(scope)});
      if (!root) return {{selected:null,ready:false}};
      const content = root.matches('.position_clear_list') ? root : root.parentElement;
      const text = content.innerText || '';
      const selected = root.querySelector('.buttons_date_picker_box_button_item.selected_item');
      const customDates = Array.from(root.querySelectorAll('#buttons_date_picker_dates input')).map(el=>el.value);
      const loading = Array.from(content.querySelectorAll('[aria-busy="true"],.ant-spin-spinning'))
        .some(el=>el.getBoundingClientRect().height>0);
      const rowCount = Array.from(content.querySelectorAll('tbody tr'))
        .filter(el=>/(^|\\n)\\d{{6}}(\\n|$)/.test(el.innerText || '')).length;
      const empty = /当前.*记录为空|暂无.*(?:数据|记录)|暂无成交/.test(text);
      return {{selected:selected ? selected.textContent.trim() : null,custom_dates:customDates,
               row_count:rowCount,empty,loading,ready:!loading && (rowCount>0 || empty)}};
    }})()"""


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
    scroll_complete = False
    stop_reason = "达到最大滚动次数，未确认列表到底"
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
            scroll_complete = True
            stop_reason = "页面无新增内容且滚动容器已稳定"
            break
        time.sleep(0.35)
    if not snapshots:
        snapshots.append(latest)
    merged = _merge_snapshots(snapshots)
    merged["scroll_label"] = label
    merged["scroll_steps"] = len(snapshots)
    merged["scroll_complete"] = scroll_complete
    merged["scroll_stop_reason"] = stop_reason
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
        upper_text = text.upper()
        if any(word in upper_text for word in ("QDII", "NASDAQ", "S&P")) or any(word in text for word in ("纳指", "标普", "恒生", "港股", "中概")):
            return True, "跨境/QDII 场内基金代码段，纳入分析"
        if any(word in text for word in ("黄金", "商品", "豆粕", "能源化工", "有色")):
            return True, "商品/黄金场内基金代码段，纳入分析"
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
                "holding_pct": window[12] if len(window) > 12 else 0,
                "quantity": window[13] if len(window) > 13 else 0,
                "holding_days": window[14] if len(window) > 14 else 0,
                "last_price": window[latest_pct_idx + 1] if len(window) > latest_pct_idx + 1 else 0,
                "cost_price": window[latest_pct_idx + 2] if len(window) > latest_pct_idx + 2 else 0,
                "note": note,
                "raw_text": "\n".join(window),
            }
        )
    return records


def _account_summary_from_snapshot(snapshot: dict[str, Any], positions: list[dict]) -> dict[str, Any]:
    text = str(snapshot.get("text") or "")
    storage_records: list[dict] = []
    for value in (snapshot.get("localStorage") or {}).values():
        storage_records.extend(_json_records(value))
    for value in (snapshot.get("sessionStorage") or {}).values():
        storage_records.extend(_json_records(value))
    total_asset = _first_number_from_records(
        storage_records,
        "total_asset",
        "totalAsset",
        "totalAssets",
        "asset",
        "assets",
        "总资产",
        "资产总额",
        "账户资产",
    ) or _extract_labeled_number(text, ("总资产", "资产总额", "账户资产"))
    cash = _first_number_from_records(
        storage_records,
        "cash",
        "available",
        "available_cash",
        "availableCash",
        "可用资金",
        "可用余额",
        "现金",
    ) or _extract_labeled_number(text, ("可用资金", "可用余额", "现金余额", "现金"))
    total_market_value = sum(_to_number(_pick_value(item, "market_value", "marketValue", "参考市值", "市值", "持仓市值", default=0)) for item in positions)
    if not total_asset and cash and total_market_value:
        total_asset = cash + total_market_value
    source = "ths_account_summary" if total_asset else "positions_market_value_fallback"
    return {
        "total_asset": total_asset or None,
        "cash": cash or None,
        "total_market_value": total_market_value or None,
        "position_pct_source": source,
        "note": "资金仓位使用账户总资产计算；如总资产缺失则按持仓市值合计估算",
    }


def _first_number_from_records(records: list[dict], *keys: str) -> float | None:
    for record in records:
        if not isinstance(record, dict):
            continue
        value = _pick_value(record, *keys, default=None)
        number = _to_number(value)
        if number > 0:
            return number
    return None


def _extract_labeled_number(text: str, labels: tuple[str, ...]) -> float | None:
    flat = re.sub(r"\s+", " ", str(text or ""))
    for label in labels:
        pattern = re.compile(rf"{re.escape(label)}\s*[:：]?\s*([+-]?\d[\d,]*(?:\.\d+)?)")
        match = pattern.search(flat)
        if match:
            number = _to_number(match.group(1))
            if number > 0:
                return number
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        if line not in labels:
            continue
        for candidate in lines[idx + 1 : idx + 4]:
            number = _to_number(candidate)
            if number > 0:
                return number
    return None


def _to_number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    text = str(value).replace(",", "").replace("%", "").strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


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
    has_side = any(key in keys for key in ("side", "bsFlag", "business_name", "买卖方向", "方向", "类型"))
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
    date_pattern = re.compile(r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?")
    sides = {"买入", "卖出", "申购", "赎回"}
    for idx, line in enumerate(lines):
        if not _is_code(line) or idx + 2 >= len(lines) or lines[idx + 2] not in sides:
            continue
        # The displayed date precedes the code. A block ending at the next code
        # contains the next trade's date, shifting records and losing the last
        # row. Keep dates with their own row, including date-only final rows.
        row_date = lines[idx - 1] if idx > 0 and date_pattern.fullmatch(lines[idx - 1]) else ""
        row_time = ""
        if not row_date and idx > 1 and re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", lines[idx - 1]) and date_pattern.fullmatch(lines[idx - 2]):
            row_date, row_time = lines[idx - 2], lines[idx - 1]
        if not row_date:
            continue
        next_idx = next((pos for pos in range(idx + 3, len(lines))
                         if date_pattern.fullmatch(lines[pos])
                         or (_is_code(lines[pos]) and pos + 2 < len(lines) and lines[pos + 2] in sides)),
                        min(len(lines), idx + 16))
        window = lines[idx:next_idx]
        block = "\n".join([row_date, *([row_time] if row_time else []), *window])
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
        date_match = re.search(r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}", row_date)
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
