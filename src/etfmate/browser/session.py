from __future__ import annotations

from pathlib import Path
from typing import Callable

from playwright.sync_api import BrowserContext, Page, sync_playwright


DESKTOP_VIEWPORT = {"width": 1280, "height": 900}
MOBILE_VIEWPORT = {"width": 390, "height": 844}
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


class BrowserSession:
    def __init__(self, profile_dir: Path, mobile: bool = False, headless: bool = False):
        self.profile_dir = profile_dir
        self.mobile = mobile
        self.headless = headless
        self._playwright = None
        self.context: BrowserContext | None = None

    def __enter__(self) -> "BrowserSession":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        kwargs = {
            "user_data_dir": str(self.profile_dir),
            "headless": self.headless,
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "viewport": MOBILE_VIEWPORT if self.mobile else DESKTOP_VIEWPORT,
        }
        if self.mobile:
            kwargs.update({"user_agent": MOBILE_UA, "device_scale_factor": 2, "is_mobile": True})
        self.context = self._playwright.chromium.launch_persistent_context(**kwargs)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.context:
            self.context.close()
        if self._playwright:
            self._playwright.stop()

    def page(self) -> Page:
        if not self.context:
            raise RuntimeError("BrowserSession 尚未启动")
        return self.context.pages[0] if self.context.pages else self.context.new_page()


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
