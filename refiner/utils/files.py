"""Reading run files."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def read(path: Path, default: Any = None) -> Any:
    """A .json file parsed, any other file as text; `default` if it does not exist."""
    if not path.exists():
        return default
    return json.loads(path.read_text()) if path.suffix == ".json" else path.read_text()


def last_json_line(path: Path, size: int = 65536) -> dict | None:
    """The last complete JSON line of a JSONL file, read from its end."""
    if not path.exists():
        return None
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - size))
        lines = f.read().decode("utf-8", errors="ignore").splitlines()
    for ln in reversed(lines):
        try:
            return json.loads(ln)
        except json.JSONDecodeError:
            continue
    return None
