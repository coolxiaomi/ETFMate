from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .session import WebAccessSession, ensure_login, require_login


TOUKER_URL = "https://m.touker.com/fd/conditions/monitoring"


def touker_login_check(session: WebAccessSession) -> bool:
    text = str(session.eval("document.body ? document.body.innerText : ''") or "")
    negative = ["登录", "验证码", "手机号"]
    positive = ["监控", "网格", "条件", "触发"]
    return any(word in text for word in positive) and not any(word in text for word in negative)


def login(root: Path) -> None:
    with WebAccessSession(root) as session:
        ensure_login(session, TOUKER_URL, touker_login_check, "请在 Chrome 中完成 Touker 登录。")


def collect(root: Path, out_dir: Path) -> dict:
    with WebAccessSession(root) as session:
        require_login(session, TOUKER_URL, touker_login_check, "Touker 未登录或登录验证未完成，请在 Chrome 中手动登录后重新运行。")
        scroll_meta = _scroll_until_stable(session)
        snapshot = _as_dict(session.eval(_SNAPSHOT_JS))
        snapshot.update(scroll_meta)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "grids_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "grids_text.txt").write_text(str(snapshot.get("text", "")), encoding="utf-8")
        session.screenshot(out_dir / "grids.png")

    records = _records_from_snapshot(snapshot)
    records.extend(_grid_records_from_text(str(snapshot.get("text", ""))))
    grids = _dedupe(_extract_records(records, _looks_like_grid), "condition_identity", "id", "conditionId", "code", "证券代码", "symbol", "name", "名称")
    expected = _expected_grid_count(str(snapshot.get("text", "")))
    if expected and len(grids) < expected:
        raise RuntimeError(f"Touker 网格未采齐：页面显示监控中 {expected} 条，当前只识别到 {len(grids)} 条。请确认页面已完整加载后重新运行。")
    return {"grids": grids, "snapshot": snapshot, "expected_count": expected}


def _scroll_until_stable(session: WebAccessSession, max_steps: int = 60) -> dict[str, Any]:
    last_signature: str | None = None
    stable_steps = 0
    for step in range(max_steps):
        latest = _as_dict(session.eval(_SNAPSHOT_JS))
        text = str(latest.get("text") or "")
        signature = _snapshot_signature(latest)
        expected = _expected_grid_count(text)
        code_count = len(re.findall(r"(?<!\d)(?:sh|sz)?\d{6}(?!\d)", text, flags=re.I))
        if signature == last_signature:
            stable_steps += 1
        else:
            stable_steps = 0
            last_signature = signature
        scroll_result = _as_dict(session.eval(_SCROLL_JS))
        loading = bool(scroll_result.get("loading")) or "加载中" in text
        if expected and code_count >= expected and stable_steps >= 1 and not loading:
            return {
                "scroll_steps": step + 1,
                "scroll_complete": True,
                "scroll_stop_reason": f"已识别监控中 {expected} 条并确认列表稳定",
            }
        if not scroll_result.get("moved") and stable_steps >= 2 and not loading:
            return {
                "scroll_steps": step + 1,
                "scroll_complete": True,
                "scroll_stop_reason": "页面无新增内容且滚动容器已稳定",
            }
        time.sleep(0.5)
    return {
        "scroll_steps": max_steps,
        "scroll_complete": False,
        "scroll_stop_reason": "达到最大滚动次数，未确认列表到底",
    }


def _records_from_snapshot(snapshot: dict[str, Any]) -> list[dict]:
    records: list[dict] = []
    for block in snapshot.get("blocks") or []:
        if isinstance(block, dict):
            records.append(block)
    for value in (snapshot.get("localStorage") or {}).values():
        records.extend(_json_records(value))
    for value in (snapshot.get("sessionStorage") or {}).values():
        records.extend(_json_records(value))
    return records


def _grid_records_from_text(text: str) -> list[dict]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    records: list[dict] = []
    for idx, line in enumerate(lines):
        match = re.search(r"(?<!\d)(?:sh|sz)?(\d{6})(?!\d)", line, flags=re.I)
        if not match:
            continue
        start = max(0, idx - 1)
        end = next((pos for pos in range(idx + 1, len(lines)) if lines[pos].startswith("截止日期")), len(lines))
        window = lines[start:end]
        block = "\n".join(window)
        name = _previous_name(lines, idx) or match.group(1)
        condition_type = _condition_type_from_block(block)
        record = {
            "code": match.group(1),
            "name": name,
            "condition_type": condition_type,
            "enabled": "休眠模式" not in block,
            "status": "休眠" if "休眠模式" in block else "监控中",
            "raw_text": block,
        }
        base_match = re.search(r"最新基准价([0-9.]+)现价([0-9.]+)现价距基准([+-]?[0-9.]+)%", block)
        if base_match:
            record["base_price"] = base_match.group(1)
            record["last_price"] = base_match.group(2)
            record["distance_from_base_pct"] = base_match.group(3)
        range_match = re.search(r"价格区间[:：]([0-9.]+)元[～~-]([0-9.]+)元", block)
        if range_match:
            record["lower_price"] = range_match.group(1)
            record["upper_price"] = range_match.group(2)
        sell_match = re.search(r"上升([+-]?[0-9.]+)%[，,]\s*回落([+-]?[0-9.]+)%[，,]\s*卖出", block)
        if sell_match:
            record["sell_rise_pct"] = sell_match.group(1)
            record["sell_pullback_pct"] = sell_match.group(2)
        buy_match = re.search(r"下跌([+-]?[0-9.]+)%[，,]\s*反弹([+-]?[0-9.]+)%[，,]\s*买入", block)
        if buy_match:
            record["buy_fall_pct"] = abs(float(buy_match.group(1)))
            record["buy_rebound_pct"] = buy_match.group(2)
        quantity_match = re.search(r"委托股数[:：]\s*(\d+)股", block)
        if quantity_match:
            record["order_quantity"] = quantity_match.group(1)
            record["buy_quantity"] = quantity_match.group(1)
            record["sell_quantity"] = quantity_match.group(1)
        quantity_line = re.search(r"委托股数[:：]([^\n]*)", block)
        if quantity_line:
            for side, field in (("买入", "buy_quantity"), ("卖出", "sell_quantity")):
                side_match = re.search(rf"{side}\s*[:：]\s*(\d+)\s*股", quantity_line.group(1))
                if side_match:
                    record[field] = side_match.group(1)
        for label, field in (("最小底仓", "min_base_quantity"), (r"最大(?:持仓|底仓)", "max_position_quantity")):
            limit_match = re.search(rf"{label}[^\S\n]*[:：]?[^\S\n]*([^\s股份]+)", block)
            if limit_match:
                value = limit_match.group(1).replace(",", "")
                if value not in {"--", "-", "未设置", "不限制", "不限"}:
                    # Keep malformed values for the quality gate; do not call them unset.
                    record[field] = value
        if condition_type == "sell_only":
            price_match = re.search(r"当前价格\s*([0-9.]+)", block)
            if price_match and "last_price" not in record:
                record["last_price"] = price_match.group(1)
            plan_match = re.search(r"股价高于\(含\)([0-9.]+)元后[，,]\s*每次[^，,，。]*涨跌幅达到\s*([+-]?[0-9.]+)%\s*卖出[，,]\s*最大卖出数量\s*(\d+)股", block)
            if plan_match:
                record["sell_plan_trigger_price"] = plan_match.group(1)
                record["sell_rise_pct"] = plan_match.group(2)
                record["sell_plan_max_quantity"] = plan_match.group(3)
        record["condition_identity"] = _condition_identity(record, block)
        records.append(record)
    return records


def _condition_type_from_block(block: str) -> str:
    if "网格交易" in block or "最新基准价" in block:
        return "grid"
    if "分批出货" in block or "股价高于" in block:
        return "sell_only"
    if "分批建仓" in block or "股价低于" in block:
        return "buy_only"
    return "grid"


def is_grid_condition(record: dict[str, Any]) -> bool:
    """Exclude identified non-grid orders, including legacy misclassified snapshots."""
    block = str(record.get("raw_text") or "")
    if block and _condition_type_from_block(block) != "grid":
        return False
    condition_type = str(record.get("condition_type") or record.get("类型") or "grid").strip().lower()
    return condition_type in {"grid", "网格", "网格交易"}


def _condition_identity(record: dict, block: str) -> str:
    code = str(record.get("code") or "")
    ctype = str(record.get("condition_type") or "grid")
    if ctype == "sell_only":
        signature = "|".join(
            str(record.get(key) or "")
            for key in ("sell_plan_trigger_price", "sell_rise_pct", "sell_plan_max_quantity", "order_quantity")
        )
    elif ctype != "grid":
        signature = block
    else:
        signature = "|".join(
            str(record.get(key) or "")
            for key in ("base_price", "buy_fall_pct", "buy_rebound_pct", "sell_rise_pct", "sell_pullback_pct", "order_quantity", "buy_quantity", "sell_quantity")
        )
    return f"{code}|{ctype}|{signature}"


def _previous_name(lines: list[str], idx: int) -> str | None:
    for pos in range(idx - 1, max(-1, idx - 5), -1):
        line = lines[pos].strip()
        if not line or _is_code(line) or re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", line, flags=re.I):
            continue
        if line.startswith("截止日期") or line in {"监控中", "已委托", "历史记录", "网格交易", "双向"}:
            continue
        if any(word in line for word in ("委托", "价格区间", "现价", "上升", "下跌", "改单", "暂停", "删除", "详情", "延期")):
            continue
        return line
    return None


def _expected_grid_count(text: str) -> int | None:
    match = re.search(r"监控中\s*\(?\s*(\d+)\s*\)?", text)
    return int(match.group(1)) if match else None


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


def _looks_like_grid(item: dict) -> bool:
    keys = set(item)
    text = json.dumps(item, ensure_ascii=False)
    has_code = any(_is_code(item.get(key)) for key in ("code", "symbol", "stockCode", "securityCode", "证券代码", "代码"))
    has_grid_text = any(word in text for word in ("grid", "condition", "trigger", "rise", "fall", "rebound", "pullback", "buy", "sell", "网格", "条件", "触发", "买入", "卖出", "基准"))
    has_param = any(key in keys for key in ("buy_fall_pct", "sell_rise_pct", "buyFallPct", "sellRisePct", "fallRate", "riseRate", "order_quantity", "buy_quantity", "sell_quantity"))
    return has_code and (has_grid_text or has_param)


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


def _snapshot_signature(snapshot: dict[str, Any]) -> str:
    text = str(snapshot.get("text") or "")
    code_count = len(re.findall(r"(?<!\d)(?:sh|sz)?\d{6}(?!\d)", text, flags=re.I))
    return f"{code_count}:{len(snapshot.get('blocks') or [])}:{len(text)}"


_SCROLL_JS = r"""
(() => {
  const candidates = Array.from(document.querySelectorAll("*"))
    .filter((el) => el.scrollHeight > el.clientHeight + 50)
    .sort((a, b) => b.scrollHeight - a.scrollHeight);
  let moved = false;
  let movedCount = 0;
  let maxRemaining = 0;
  for (const el of candidates) {
    const before = el.scrollTop;
    const maxTop = Math.max(0, el.scrollHeight - el.clientHeight);
    el.scrollTop = Math.min(maxTop, el.scrollTop + Math.max(900, el.clientHeight || 0));
    el.dispatchEvent(new Event("scroll", { bubbles: true }));
    if (el.scrollTop !== before) {
      moved = true;
      movedCount += 1;
    }
    maxRemaining = Math.max(maxRemaining, maxTop - el.scrollTop);
  }
  const beforeY = window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;
  window.scrollBy(0, 900);
  const afterY = window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;
  if (afterY !== beforeY) {
    moved = true;
    movedCount += 1;
  }
  const text = document.body ? document.body.innerText : "";
  return JSON.stringify({
    moved,
    movedCount,
    maxRemaining,
    loading: text.includes("加载中"),
    itemCount: document.querySelectorAll(".monitor-item").length,
    codeCount: (text.match(/(?<!\d)(?:sh|sz)?\d{6}(?!\d)/gi) || []).length,
  });
})()
"""

_SNAPSHOT_JS = r"""
(() => {
  const text = document.body ? document.body.innerText : "";
  const blocks = Array.from(document.querySelectorAll("div,section,article,li"))
    .map((el) => ({ text: el.innerText ? el.innerText.trim() : "", className: el.className || "", id: el.id || "" }))
    .filter((item) => /(\d{6}|网格|条件|触发|基准|买入|卖出)/.test(item.text))
    .slice(0, 1000);
  const storage = (source) => Object.fromEntries(Array.from({ length: source.length }, (_, i) => {
    const key = source.key(i);
    return [key, source.getItem(key)];
  }).filter(([key]) => key));
  return JSON.stringify({
    url: location.href,
    title: document.title,
    text,
    blocks,
    localStorage: storage(localStorage),
    sessionStorage: storage(sessionStorage),
  });
})()
"""
