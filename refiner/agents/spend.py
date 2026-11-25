"""What a run has spent: every provider response adds its tokens here, priced from models.yaml (USD per million
tokens, `pricing.response`). Cache writes cost 1.25× the input price and cache reads 0.1× (Anthropic and OpenAI
prompt caching). A model without a price in the catalog is counted in tokens but costs 0, and is listed in
`unpriced` so the run can say so once. One ledger per process (the fan-out's threads and sub-runs share it),
behind a lock; `attach(run_dir)` mirrors every change to <run>/spend.json, and `start` restores it on a resume.
Totals are kept per model and per role (parser, scorer, judge, generator): `llm.call` names the role of each
call with `role(...)`, a context variable, so the providers need not know it."""

from __future__ import annotations

import contextvars
import json
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import models

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"usd": 0.0, "by_model": {}, "by_role": {}, "file": None}
_ROLE: contextvars.ContextVar[str] = contextvars.ContextVar("spend_role", default="other")
CACHE_WRITE, CACHE_READ = 1.25, 0.1
FILE = "spend.json"
ROLES = ("parser", "scorer", "judge", "generator")


class BudgetExceeded(Exception):
    pass


@contextmanager
def role(name: str):
    """Every response recorded inside is charged to this role (per thread)."""
    token = _ROLE.set(name)
    try:
        yield
    finally:
        _ROLE.reset(token)


def attach(run_dir: Path | None) -> None:
    """Mirror the ledger to <run_dir>/spend.json after every call (None stops mirroring)."""
    with _LOCK:
        _STATE["file"] = (Path(run_dir) / FILE) if run_dir else None


def start(spent: dict | None) -> None:
    """Continue from a saved snapshot (resume) or from zero."""
    with _LOCK:
        _STATE["usd"] = float((spent or {}).get("usd", 0.0))
        _STATE["by_model"] = {k: dict(v) for k, v in ((spent or {}).get("by_model") or {}).items()}
        _STATE["by_role"] = {k: dict(v) for k, v in ((spent or {}).get("by_role") or {}).items()}


def price(model: str) -> dict:
    return ((models.entry(model).get("pricing") or {}).get("response")) or {}


def _add(table: dict, key: str, inp: int, out: int, cache_write: int, cache_read: int, usd: float, priced: bool) -> None:
    m = table.setdefault(key, {"calls": 0, "input": 0, "output": 0, "cache_write": 0, "cache_read": 0, "usd": 0.0, "priced": priced})
    m["calls"] += 1
    m["input"] += inp; m["output"] += out; m["cache_write"] += cache_write; m["cache_read"] += cache_read
    m["usd"] = round(m["usd"] + usd, 6)
    m["priced"] = m["priced"] and priced


def record(model: str, inp: int = 0, out: int = 0, cache_write: int = 0, cache_read: int = 0) -> float:
    """Add one response's tokens, to its model and to the current role; returns its USD. Called by the providers
    for every response, retries and tool turns included — each one was paid for."""
    p = price(model)
    i, o = float(p.get("input_token_cost") or 0), float(p.get("output_token_cost") or 0)
    usd = (inp * i + cache_write * i * CACHE_WRITE + cache_read * i * CACHE_READ + out * o) / 1e6
    with _LOCK:
        _add(_STATE["by_model"], model, inp, out, cache_write, cache_read, usd, bool(p))
        _add(_STATE["by_role"], _ROLE.get(), inp, out, cache_write, cache_read, usd, bool(p))
        _STATE["usd"] = round(_STATE["usd"] + usd, 6)
        if _STATE["file"]:
            _STATE["file"].parent.mkdir(parents=True, exist_ok=True)
            _STATE["file"].write_text(json.dumps(_snapshot(), indent=1))
    return usd


def total() -> float:
    with _LOCK:
        return _STATE["usd"]


def _snapshot() -> dict:
    return {"usd": round(_STATE["usd"], 4), "by_model": {k: dict(v) for k, v in _STATE["by_model"].items()},
            "by_role": {k: dict(v) for k, v in _STATE["by_role"].items()}}


def snapshot() -> dict:
    with _LOCK:
        return _snapshot()


def unpriced() -> list[str]:
    """Models that were called but have no price in models.yaml (their tokens are counted, their cost is 0)."""
    with _LOCK:
        return sorted(k for k, v in _STATE["by_model"].items() if not v.get("priced"))


def read(run_dir: Path) -> dict | None:
    p = Path(run_dir) / FILE
    return json.loads(p.read_text()) if p.exists() else None
