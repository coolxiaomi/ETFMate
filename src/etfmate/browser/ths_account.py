from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .session import BrowserSession, ensure_login, require_login


THS_URL = "https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/c60MoMO"


def ths_login_check(page) -> bool:
    text = page.locator("body").inner_text(timeout=5000)
    negative = ["验证码", "手机号登录", "立即登录"]
    positive = ["持仓", "资产", "成交", "盈亏"]
    return any(word in text for word in positive) and not any(word in text for word in negative)


def login(root: Path) -> None:
    with BrowserSession(root) as session:
        ensure_login(
            session.page(),
            THS_URL,
            ths_login_check,
            "请在打开的浏览器窗口中完成同花顺登录和验证码验证。",
        )


def collect(root: Path, out_dir: Path) -> dict:
    captures: list[dict] = []
    with BrowserSession(root) as session:
        page = session.page()
        page.on("response", lambda r: _capture_json_response(r, captures))
        require_login(page, THS_URL, ths_login_check, "同花顺投资账本未登录或登录验证未完成，请在当前 Chrome 中手动登录后重新运行。")
        page.wait_for_timeout(3000)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "account.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(out_dir / "account.png"), full_page=True)
        (out_dir / "network.json").write_text(json.dumps(captures, ensure_ascii=False, indent=2), encoding="utf-8")
    positions = _dedupe(_extract_records(captures, _looks_like_position), "code", "证券代码", "symbol")
    trades = _dedupe(_extract_records(captures, _looks_like_trade), "trade_id", "成交编号", "entrust_no", "code", "证券代码", "trade_time", "成交时间", "price", "成交价", "quantity", "成交数量")
    return {"positions": positions, "trades": trades, "closed_positions": [], "network": captures}


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


def _looks_like_position(item: dict) -> bool:
    keys = set(item)
    text = " ".join(keys)
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
