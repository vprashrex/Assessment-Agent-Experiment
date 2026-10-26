"""Run events: one JSON object per line in <run>/events.jsonl, appended the moment something happens.

Envelope: {"seq": 1, 2, 3 … per run, "ts": ISO-8601 UTC, "type": str, "metric": str | null, "data": {...}}.
The event types and their data are listed in plan.md (section 10.4). The file is the source of truth: the server
streams it, resumes from any seq, and reads its last line to know how a run ended.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..utils.files import last_json_line

FILE = "events.jsonl"
TERMINAL = ("run.done", "run.failed")
_LOCK = threading.Lock()  # the metric loops of one run write from parallel threads


def emit(run_dir: Path, type: str, metric: str | None = None, **data: Any) -> dict:
    """Append one event; seq continues from the last event in the file (also across processes, which run one at a
    time per run)."""
    path = Path(run_dir) / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        last = last_json_line(path)
        event = {"seq": (last or {}).get("seq", 0) + 1, "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                 "type": type, "metric": metric or None, "data": data}
        with path.open("a") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
            f.flush()
    return event


def read(run_dir: Path, after: int = 0) -> list[dict]:
    """Every complete event with seq > after, in order."""
    path = Path(run_dir) / FILE
    if not path.exists():
        return []
    out = []
    with path.open() as f:
        for ln in f:
            if not ln.endswith("\n"):
                break  # a line still being written
            try:
                e = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if e.get("seq", 0) > after:
                out.append(e)
    return out


def last(run_dir: Path) -> dict | None:
    return last_json_line(Path(run_dir) / FILE)
