#!/usr/bin/env python
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    parser = argparse.ArgumentParser(description="生成或补齐 web-access 版 ETFMate 项目骨架")
    parser.add_argument("target", nargs="?", default=".", help="目标项目目录")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    _copy_file(ROOT / "pyproject.toml", target / "pyproject.toml")
    _copy_tree(ROOT / "src", target / "src")
    _copy_tree(ROOT / ".agents" / "skills" / "etfmate-skill" / "references", target / ".agents" / "skills" / "etfmate-skill" / "references")
    _ensure_runtime_dirs(target)
    print(f"已生成 web-access 版 ETFMate 骨架: {target}")
    return 0


def _copy_file(src: Path, dst: Path) -> None:
    if src.resolve() == dst.resolve():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_tree(src: Path, dst: Path) -> None:
    if src.resolve() == dst.resolve():
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _ensure_runtime_dirs(target: Path) -> None:
    for rel in (
        "data/raw/ths",
        "data/raw/touker",
        "data/raw/market",
        "data/reports",
        "runtime",
    ):
        (target / rel).mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
