from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import to_dict


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_id_str(value: str | None = None) -> str:
    return value or datetime.now().strftime("%Y%m%d-%H%M%S")


def write_json(path: Path, payload: Any) -> Path:
    ensure_dir(path.parent)
    path.write_text(json.dumps(to_dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))
