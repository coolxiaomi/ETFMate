from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


DEFAULT_PROXY_URL = "http://localhost:3456"
DEFAULT_LOGIN_WAIT_SECONDS = 600
URL_SAFE_CHARS = ":/?#[]@!$&'()*+,;=%"


class WebAccessNotReadyError(RuntimeError):
    pass


class LoginRequiredError(RuntimeError):
    pass


class WebAccessSession:
    """Small client for the web-access CDP Proxy HTTP API."""

    def __init__(self, root: Path, proxy_url: str | None = None, wait_seconds: int = 90):
        self.root = root
        self.proxy_url = (proxy_url or os.environ.get("ETFMATE_WEB_ACCESS_PROXY_URL") or DEFAULT_PROXY_URL).rstrip("/")
        self.wait_seconds = wait_seconds
        self.target_id: str | None = None

    def __enter__(self) -> "WebAccessSession":
        require_web_access_proxy(self.proxy_url, wait_seconds=self.wait_seconds)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.target_id:
            try:
                self.close()
            except WebAccessNotReadyError:
                pass

    def open(self, url: str) -> None:
        payload = self._request_json("GET", f"/new?url={urllib.parse.quote(url, safe=URL_SAFE_CHARS)}")
        target = _pick_target_id(payload)
        if not target:
            raise WebAccessNotReadyError(f"web-access /new 未返回 target id: {payload!r}")
        self.target_id = target

    def navigate(self, url: str) -> None:
        self._require_target()
        self._request_text("GET", f"/navigate?target={urllib.parse.quote(self.target_id or '')}&url={urllib.parse.quote(url, safe=URL_SAFE_CHARS)}")

    def eval(self, script: str) -> Any:
        self._require_target()
        raw = self._request_text("POST", f"/eval?target={urllib.parse.quote(self.target_id or '')}", data=script)
        return _unwrap_eval(raw)

    def info(self) -> Any:
        self._require_target()
        return self._request_json("GET", f"/info?target={urllib.parse.quote(self.target_id or '')}")

    def screenshot(self, path: Path) -> None:
        self._require_target()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._request_text(
            "GET",
            f"/screenshot?target={urllib.parse.quote(self.target_id or '')}&file={urllib.parse.quote(str(path))}",
        )

    def close(self) -> None:
        self._require_target()
        self._request_text("GET", f"/close?target={urllib.parse.quote(self.target_id or '')}")
        self.target_id = None

    def _request_json(self, method: str, path: str, data: str | None = None) -> Any:
        text = self._request_text(method, path, data=data)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def _request_text(self, method: str, path: str, data: str | None = None) -> str:
        body = data.encode("utf-8") if data is not None else None
        req = urllib.request.Request(self.proxy_url + path, data=body, method=method)
        if data is not None:
            req.add_header("Content-Type", "text/plain; charset=utf-8")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (OSError, urllib.error.URLError) as exc:
            raise WebAccessNotReadyError(_web_access_help(self.proxy_url)) from exc

    def _require_target(self) -> None:
        if not self.target_id:
            raise RuntimeError("web-access tab 尚未创建")


def require_web_access_proxy(proxy_url: str | None = None, wait_seconds: int = 0) -> str:
    proxy = (proxy_url or os.environ.get("ETFMATE_WEB_ACCESS_PROXY_URL") or DEFAULT_PROXY_URL).rstrip("/")
    deadline = time.monotonic() + max(wait_seconds, 0)
    while True:
        try:
            with urllib.request.urlopen(proxy + "/targets", timeout=2) as resp:
                resp.read()
            return proxy
        except (OSError, urllib.error.URLError):
            if time.monotonic() >= deadline:
                raise WebAccessNotReadyError(_web_access_help(proxy))
            time.sleep(2)


def ensure_login(session: WebAccessSession, url: str, login_check: Callable[[WebAccessSession], bool], prompt: str) -> None:
    session.open(url)
    time.sleep(1.5)
    if login_check(session):
        return
    print(prompt)
    if os.isatty(0):
        input("完成后回到终端按 Enter 继续...")
        session.navigate(url)
        time.sleep(1.5)
    else:
        wait_seconds = int(os.environ.get("ETFMATE_LOGIN_WAIT_SECONDS", str(DEFAULT_LOGIN_WAIT_SECONDS)))
        deadline = time.monotonic() + wait_seconds
        print(f"当前命令没有交互式 stdin，将在 {wait_seconds} 秒内每 5 秒自动检查登录状态。")
        while time.monotonic() < deadline:
            time.sleep(5)
            session.navigate(url)
            time.sleep(1.5)
            if login_check(session):
                return
    if not login_check(session):
        raise RuntimeError("登录状态仍未通过检查，请确认网页已完成登录和验证")


def require_login(session: WebAccessSession, url: str, login_check: Callable[[WebAccessSession], bool], prompt: str) -> None:
    session.open(url)
    time.sleep(1.5)
    if not login_check(session):
        raise LoginRequiredError(prompt)


def _web_access_help(proxy_url: str) -> str:
    return f"""未找到可用 web-access Proxy：{proxy_url}
请先加载 `$web-access` skill，并按其前置检查启动 CDP Proxy：

node "${{CLAUDE_SKILL_DIR}}/scripts/check-deps.mjs"

确认 Chrome 已在 chrome://inspect/#remote-debugging 授权，并已登录同花顺投资账本和 Touker。
未完成前不要继续分析。"""


def _pick_target_id(payload: Any) -> str | None:
    if isinstance(payload, str):
        return payload.strip() or None
    if isinstance(payload, dict):
        for key in ("id", "targetId", "target", "uuid"):
            value = payload.get(key)
            if value:
                return str(value)
        result = payload.get("result")
        if result is not None:
            return _pick_target_id(result)
    return None


def _unwrap_eval(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    for key in ("value", "result", "data"):
        if isinstance(payload, dict) and key in payload:
            value = payload[key]
            if isinstance(value, dict) and "value" in value:
                return value["value"]
            return value
    return payload
