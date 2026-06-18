from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright


DESKTOP_VIEWPORT = {"width": 1280, "height": 900}
MOBILE_VIEWPORT = {"width": 390, "height": 844}
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
DEFAULT_LOGIN_WAIT_SECONDS = 600


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
        self.cdp_url = require_cdp_url(self.profile_dir, self.cdp_url, wait_seconds=self.wait_seconds)
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


class LoginRequiredError(RuntimeError):
    pass


class ChromeNotReadyError(RuntimeError):
    pass


def require_cdp_url(profile_dir: Path, preferred_url: str | None = None, wait_seconds: int = 0) -> str:
    preferred = preferred_url or os.environ.get("ETFMATE_CDP_URL", DEFAULT_CDP_URL)
    deadline = time.monotonic() + max(wait_seconds, 0)
    checked: list[str] = []
    while True:
        candidates = [preferred, *discover_cdp_urls()]
        for url in dict.fromkeys(candidates):
            checked.append(url)
            if _cdp_available(url):
                return url
        if time.monotonic() >= deadline:
            raise ChromeNotReadyError(_remote_debugging_help(profile_dir, preferred, checked))
        time.sleep(2)


def discover_cdp_urls() -> list[str]:
    ports = {"9222", "9444", "9333"}
    if os.name == "nt":
        script = r"""
$chromePids = Get-CimInstance Win32_Process -Filter "name='chrome.exe'" | Select-Object -ExpandProperty ProcessId
if ($chromePids) {
  Get-NetTCPConnection -State Listen |
    Where-Object { $chromePids -contains $_.OwningProcess } |
    Select-Object -ExpandProperty LocalPort
}
"""
        try:
            output = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", script],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            ports.update(line.strip() for line in output.splitlines() if line.strip().isdigit())
        except (OSError, subprocess.SubprocessError):
            pass
    return [f"http://127.0.0.1:{port}" for port in sorted(ports, key=lambda item: int(item))]


def _cdp_available(cdp_url: str) -> bool:
    try:
        with urllib.request.urlopen(cdp_url.rstrip("/") + "/json/version", timeout=1) as resp:
            return "webSocketDebuggerUrl" in resp.read().decode("utf-8", errors="ignore")
    except (OSError, urllib.error.URLError):
        return False


def _remote_debugging_help(profile_dir: Path, cdp_url: str, checked: list[str] | None = None) -> str:
    checked_text = ""
    if checked:
        checked_text = "\n已检查端点：" + "、".join(dict.fromkeys(checked))
    return f"""未找到可用 Chrome CDP：{cdp_url}{checked_text}
请先打开一个允许远程调试的 Chrome，并在同一个浏览器中登录同花顺投资账本和 Touker。未完成前不要继续分析。

PowerShell:
& "$env:ProgramFiles\\Google\\Chrome\\Application\\chrome.exe" `
  --remote-debugging-port=9222 `
  --remote-debugging-address=127.0.0.1 `
  --user-data-dir="{profile_dir}"

然后在该 Chrome 中打开 chrome://inspect/#remote-debugging，开启 Allow remote debugging for this browser instance。
完成后保持 Chrome 打开，再重新运行 ETFMate。"""


def ensure_login(page: Page, url: str, login_check: Callable[[Page], bool], prompt: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if login_check(page):
        return
    print(prompt)
    if sys.stdin.isatty():
        input("完成后回到终端按 Enter 继续...")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
    else:
        wait_seconds = int(os.environ.get("ETFMATE_LOGIN_WAIT_SECONDS", str(DEFAULT_LOGIN_WAIT_SECONDS)))
        deadline = time.monotonic() + wait_seconds
        print(f"当前命令没有交互式 stdin，将在 {wait_seconds} 秒内每 5 秒自动检查登录状态。")
        while time.monotonic() < deadline:
            page.wait_for_timeout(5000)
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            if login_check(page):
                return
    if not login_check(page):
        raise RuntimeError("登录状态仍未通过检查，请确认网页已完成登录和验证")


def require_login(page: Page, url: str, login_check: Callable[[Page], bool], prompt: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if not login_check(page):
        raise LoginRequiredError(prompt)
