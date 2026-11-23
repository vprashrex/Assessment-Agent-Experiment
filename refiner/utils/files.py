"""Reading run files, and the media types of the files the refiner attaches."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


# the files a submission may attach, as the models receive them (PDF and images; anything else becomes text)
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
MIME = {".pdf": "application/pdf", **IMAGE_MIME}


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
