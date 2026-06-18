#!/usr/bin/env python
from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path


REQUIRED_MODULES = [
    "pandas",
    "stockstats",
    "mootdx",
    "requests",
]


def module_status(name: str) -> dict[str, object]:
    spec = importlib.util.find_spec(name)
    return {"name": name, "ok": spec is not None}


def candidate_skill_paths() -> list[Path]:
    home = Path.home()
    paths = [
        home / ".agents" / "skills" / "a-stock-data" / "SKILL.md",
        home / ".codex" / "skills" / "a-stock-data" / "SKILL.md",
        home / ".agents" / "skills" / "web-access" / "SKILL.md",
        home / ".codex" / "skills" / "web-access" / "SKILL.md",
    ]
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        paths.extend(
            [
                Path(codex_home) / "skills" / "a-stock-data" / "SKILL.md",
                Path(codex_home) / "skills" / "web-access" / "SKILL.md",
            ]
        )
    return paths


def web_access_proxy_status() -> dict[str, object]:
    proxy_url = os.environ.get("ETFMATE_WEB_ACCESS_PROXY_URL", "http://localhost:3456").rstrip("/")
    try:
        with urllib.request.urlopen(proxy_url + "/targets", timeout=2) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        return {"ok": True, "url": proxy_url, "targets_preview": body[:500]}
    except (OSError, urllib.error.URLError) as exc:
        return {"ok": False, "url": proxy_url, "error": str(exc)}


def main() -> int:
    modules = [module_status(name) for name in REQUIRED_MODULES]
    paths = candidate_skill_paths()
    a_stock_paths = [str(path) for path in paths if path.exists() and path.parent.name == "a-stock-data"]
    web_access_paths = [str(path) for path in paths if path.exists() and path.parent.name == "web-access"]
    proxy = web_access_proxy_status()
    ok = all(item["ok"] for item in modules) and bool(a_stock_paths) and bool(web_access_paths) and proxy["ok"]

    payload = {
        "ok": ok,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "node": {"ok": shutil.which("node") is not None, "path": shutil.which("node")},
        "modules": modules,
        "a_stock_data_skill": {"ok": bool(a_stock_paths), "paths": a_stock_paths},
        "web_access_skill": {"ok": bool(web_access_paths), "paths": web_access_paths},
        "web_access_proxy": proxy,
        "next_steps": [],
    }

    missing = [item["name"] for item in modules if not item["ok"]]
    if missing:
        payload["next_steps"].append("安装缺失依赖: python -m pip install " + " ".join(missing))
    if not a_stock_paths:
        payload["next_steps"].append("确认 a-stock-data skill 已安装到 ~/.agents/skills 或 ~/.codex/skills")
    if not web_access_paths:
        payload["next_steps"].append("确认 web-access skill 已安装到 ~/.agents/skills 或 ~/.codex/skills")
    if not proxy["ok"]:
        payload["next_steps"].append('加载 $web-access 后运行: node "${CLAUDE_SKILL_DIR}/scripts/check-deps.mjs"')

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
