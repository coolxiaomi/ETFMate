from __future__ import annotations

import json
from pathlib import Path

from .session import BrowserSession, ensure_login


THS_URL = "https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/c60MoMO"


def ths_login_check(page) -> bool:
    text = page.locator("body").inner_text(timeout=5000)
    negative = ["验证码", "手机号登录", "立即登录"]
    positive = ["持仓", "资产", "成交", "盈亏"]
    return any(word in text for word in positive) and not any(word in text for word in negative)


def login(root: Path) -> None:
    with BrowserSession(root / "runtime/playwright-profile/ths") as session:
        ensure_login(
            session.page(),
            THS_URL,
            ths_login_check,
            "请在打开的浏览器窗口中完成同花顺登录和验证码验证。",
        )


def collect(root: Path, out_dir: Path) -> dict:
    captures: list[dict] = []
    with BrowserSession(root / "runtime/playwright-profile/ths") as session:
        page = session.page()
        page.on("response", lambda r: captures.append({"url": r.url, "status": r.status}) if "json" in (r.headers.get("content-type", "")) else None)
        ensure_login(page, THS_URL, ths_login_check, "请在打开的浏览器窗口中完成同花顺登录。")
        page.wait_for_timeout(3000)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "account.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(out_dir / "account.png"), full_page=True)
        (out_dir / "network.json").write_text(json.dumps(captures, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"positions": [], "trades": [], "closed_positions": [], "network": captures}
