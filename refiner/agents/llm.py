"""One function: call(model, system, user, schema, tools=None) -> dict.

The provider, output limit and reasoning setting come from models.yaml (see models.py); providers/ holds one module
per provider behind the same `complete` function. With `tools`, the model may call them (client tools): the provider
runs the Python function, sends the result back, and repeats until the model returns the final JSON.
"""

from __future__ import annotations

import contextvars
import json
import time
from contextlib import contextmanager

from . import models, providers, spend
from .providers.base import Files, LLMError, Tools

__all__ = ["Files", "LLMError", "Tools", "call", "check_cap", "HARD_CAP", "uncapped"]

HARD_CAP: dict[str, float | None] = {"usd": None}  # set by engine/run: budget × HARD_FACTOR; no call starts above it
_UNCAPPED: contextvars.ContextVar[bool] = contextvars.ContextVar("uncapped", default=False)


@contextmanager
def uncapped():
    """Lifts the hard cap for the fixed-size work after the loops have stopped (the test pass, the composer, polish —
    which stops at its next round boundary anyway), so a run that reached its budget still ends with its outputs.
    Per thread: the metric loops still running in parallel stay capped. `scorer.score_all` carries the flag into
    its worker threads."""
    token = _UNCAPPED.set(True)
    try:
        yield
    finally:
        _UNCAPPED.reset(token)


def call(model: str, system: str, user: str, schema: dict, *, effort: str = "high",
         tools: Tools | None = None, tool_log: list | None = None, files: Files | None = None,
         tries: int = 4, role: str = "other") -> dict:
    """Structured JSON from any supported model; retries transport errors and invalid JSON with backoff.
    Every tool call made is appended to `tool_log` as {tool, args, result}. `role` (parser, scorer, judge,
    generator) is what the spend ledger charges the call to."""
    with spend.role(role):
        return _call(model, system, user, schema, effort, tools, tool_log, files, tries)


def check_cap() -> None:
    """Refuses to start a model call once the run's spend has passed the hard cap (outside `uncapped()`)."""
    if HARD_CAP["usd"] is not None and not _UNCAPPED.get() and spend.total() >= HARD_CAP["usd"]:
        raise spend.BudgetExceeded(f"spent ${spend.total():.2f}, hard cap ${HARD_CAP['usd']:.2f}: no new model call "
                                   f"(rerun with a higher --budget to resume)")


def _call(model, system, user, schema, effort, tools, tool_log, files, tries) -> dict:
    last: Exception | None = None
    for i in range(tries):
        check_cap()
        log: list = []
        try:
            text = providers.get(model)(model, system, user, schema, models.reasoning(model, effort), tools, log, files or [])
            out = json.loads(text)
            missing = [k for k in schema.get("required", []) if not isinstance(out, dict) or k not in out]
            if missing:  # e.g. the schema echoed back instead of an answer; retried like malformed JSON
                raise ValueError(f"answer lacks required keys: {', '.join(missing)}")
            if tool_log is not None:
                tool_log.extend(log)
            return out
        except (LLMError, spend.BudgetExceeded):
            raise
        except Exception as e:  # network, overload, 5xx, malformed JSON — all retried the same way
            if "invalid_request" in str(e) or "BadRequest" in type(e).__name__:
                raise
            last = e
            time.sleep(5 * (i + 1))
    raise LLMError(f"{model}: {type(last).__name__}: {str(last)[:200]}")
