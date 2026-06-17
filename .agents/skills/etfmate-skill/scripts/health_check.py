#!/usr/bin/env python
from __future__ import annotations

import importlib.util
import json
import os
import platform
import sys
from pathlib import Path


REQUIRED_MODULES = [
    "playwright",
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
    ]
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        paths.append(Path(codex_home) / "skills" / "a-stock-data" / "SKILL.md")
    return paths


def main() -> int:
    modules = [module_status(name) for name in REQUIRED_MODULES]
    a_stock_paths = [str(path) for path in candidate_skill_paths() if path.exists()]
    ok = all(item["ok"] for item in modules) and bool(a_stock_paths)

    payload = {
        "ok": ok,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "modules": modules,
        "a_stock_data_skill": {
            "ok": bool(a_stock_paths),
            "paths": a_stock_paths,
        },
        "next_steps": [],
    }

    missing = [item["name"] for item in modules if not item["ok"]]
    if missing:
        payload["next_steps"].append(
            "安装缺失依赖: python -m pip install " + " ".join(missing)
        )
    if not a_stock_paths:
        payload["next_steps"].append("确认 a-stock-data skill 已安装到 ~/.agents/skills 或 ~/.codex/skills")

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
