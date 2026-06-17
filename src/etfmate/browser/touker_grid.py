from __future__ import annotations

import json
from pathlib import Path

from .session import BrowserSession, ensure_login


TOUKER_URL = "https://m.touker.com/fd/conditions/monitoring"


def touker_login_check(page) -> bool:
    text = page.locator("body").inner_text(timeout=5000)
    negative = ["登录", "验证码", "手机号"]
    positive = ["监控", "网格", "条件", "触发"]
    return any(word in text for word in positive) and not any(word in text for word in negative)


def login(root: Path) -> None:
    with BrowserSession(root / "runtime/playwright-profile/touker", mobile=True) as session:
        ensure_login(session.page(), TOUKER_URL, touker_login_check, "请在打开的移动端浏览器窗口中完成 Touker 登录。")


def collect(root: Path, out_dir: Path) -> dict:
    captures: list[dict] = []
    with BrowserSession(root / "runtime/playwright-profile/touker", mobile=True) as session:
        page = session.page()
        page.on("response", lambda r: captures.append({"url": r.url, "status": r.status}) if "json" in (r.headers.get("content-type", "")) else None)
        ensure_login(page, TOUKER_URL, touker_login_check, "请在打开的移动端浏览器窗口中完成 Touker 登录。")
        page.wait_for_timeout(3000)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "grids.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(out_dir / "grids.png"), full_page=True)
        (out_dir / "network.json").write_text(json.dumps(captures, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"grids": [], "network": captures}
