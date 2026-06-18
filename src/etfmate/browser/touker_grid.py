from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .session import BrowserSession, ensure_login, require_login


TOUKER_URL = "https://m.touker.com/fd/conditions/monitoring"


def touker_login_check(page) -> bool:
    text = page.locator("body").inner_text(timeout=5000)
    negative = ["登录", "验证码", "手机号"]
    positive = ["监控", "网格", "条件", "触发"]
    return any(word in text for word in positive) and not any(word in text for word in negative)


def login(root: Path) -> None:
    with BrowserSession(root, mobile=True) as session:
        ensure_login(session.page(), TOUKER_URL, touker_login_check, "请在打开的移动端浏览器窗口中完成 Touker 登录。")


def collect(root: Path, out_dir: Path) -> dict:
    captures: list[dict] = []
    with BrowserSession(root, mobile=True) as session:
        page = session.page()
        page.on("response", lambda r: _capture_json_response(r, captures))
        require_login(page, TOUKER_URL, touker_login_check, "Touker 未登录或登录验证未完成，请在当前 Chrome 中手动登录后重新运行。")
        page.wait_for_timeout(3000)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "grids.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(out_dir / "grids.png"), full_page=True)
        (out_dir / "network.json").write_text(json.dumps(captures, ensure_ascii=False, indent=2), encoding="utf-8")
    grids = _dedupe(_extract_records(captures, _looks_like_grid), "id", "conditionId", "code", "证券代码", "symbol")
    return {"grids": grids, "network": captures}


def _capture_json_response(response, captures: list[dict]) -> None:
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type and "javascript" not in content_type:
        return
    item = {"url": response.url, "status": response.status}
    try:
        item["body"] = response.json()
    except Exception:
        try:
            text = response.text()
            item["text"] = text[:20000]
            item["body"] = json.loads(text)
        except Exception:
            pass
    captures.append(item)


def _extract_records(captures: list[dict], predicate) -> list[dict]:
    result: list[dict] = []
    for capture in captures:
        result.extend(_walk_records(capture.get("body"), predicate))
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
    has_code = any(_is_code(item.get(key)) for key in ("code", "symbol", "stockCode", "securityCode", "证券代码", "代码"))
    has_grid_text = any(word in " ".join(keys) for word in ("grid", "condition", "trigger", "rise", "fall", "rebound", "pullback", "buy", "sell", "网格", "条件", "触发", "买入", "卖出"))
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
