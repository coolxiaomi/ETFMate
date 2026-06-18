from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright


DESKTOP_VIEWPORT = {"width": 1280, "height": 900}
MOBILE_VIEWPORT = {"width": 390, "height": 844}
DEFAULT_CDP_URL = "http://127.0.0.1:9222"


class BrowserSession:
    def __init__(self, root: Path, mobile: bool = False, cdp_url: str | None = None, wait_seconds: int = 90):
        self.root = root
        self.profile_dir = root / "runtime/chrome-cdp-profile"
        self.mobile = mobile
        self.cdp_url = cdp_url or os.environ.get("ETFMATE_CDP_URL", DEFAULT_CDP_URL)
        self.wait_seconds = wait_seconds
        self._playwright = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self._page: Page | None = None

    def __enter__(self) -> "BrowserSession":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._wait_for_cdp()
        self.browser = self._playwright.chromium.connect_over_cdp(self.cdp_url)
        self.context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._playwright:
            self._playwright.stop()

    def page(self) -> Page:
        if not self.context:
            raise RuntimeError("BrowserSession 尚未启动")
        if self._page and not self._page.is_closed():
            return self._page
        self._page = self.context.new_page()
        self._page.set_viewport_size(MOBILE_VIEWPORT if self.mobile else DESKTOP_VIEWPORT)
        return self._page

    def _wait_for_cdp(self) -> None:
        deadline = time.monotonic() + self.wait_seconds
        printed = False
        while time.monotonic() < deadline:
            if _cdp_available(self.cdp_url):
                return
            if not printed:
                print(_remote_debugging_help(self.profile_dir, self.cdp_url))
                printed = True
            time.sleep(2)
        raise RuntimeError("无法连接 Chrome CDP。请按上方提示打开允许远程调试的 Chrome 后重试。")


def _cdp_available(cdp_url: str) -> bool:
    try:
        with urllib.request.urlopen(cdp_url.rstrip("/") + "/json/version", timeout=1):
            return True
    except (OSError, urllib.error.URLError):
        return False


def _remote_debugging_help(profile_dir: Path, cdp_url: str) -> str:
    return f"""未连接到 Chrome CDP：{cdp_url}
请打开一个独立调试用 Chrome，避免污染日常浏览器并减少“允许远程调试吗？”反复确认：

PowerShell:
& "$env:ProgramFiles\\Google\\Chrome\\Application\\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="{profile_dir}"

然后在该 Chrome 中打开 chrome://inspect/#remote-debugging，开启 Allow remote debugging for this browser instance。
完成后保持 Chrome 打开，本程序会继续等待连接。"""


def ensure_login(page: Page, url: str, login_check: Callable[[Page], bool], prompt: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if login_check(page):
        return
    print(prompt)
    input("完成后回到终端按 Enter 继续...")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if not login_check(page):
        raise RuntimeError("登录状态仍未通过检查，请确认网页已完成登录和验证")
