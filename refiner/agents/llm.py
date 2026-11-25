"""One function: call(model, system, user, schema, tools=None) -> dict.

The provider, output limit and reasoning setting come from models.yaml (see models.py); providers/ holds one module
per provider behind the same `complete` function. With `tools`, the model may call them (client tools): the provider
runs the Python function, sends the result back, and repeats until the model returns the final JSON.
"""

from __future__ import annotations

import json
import time

from . import models, providers, spend
from .providers.base import Files, LLMError, Tools

__all__ = ["Files", "LLMError", "Tools", "call", "HARD_CAP"]

HARD_CAP: dict[str, float | None] = {"usd": None}  # set by engine/run: budget × HARD_FACTOR; no call starts above it


def call(model: str, system: str, user: str, schema: dict, *, effort: str = "high",
         tools: Tools | None = None, tool_log: list | None = None, files: Files | None = None,
         tries: int = 4) -> dict:
    """Structured JSON from any supported model; retries transport errors and invalid JSON with backoff.
    Every tool call made is appended to `tool_log` as {tool, args, result}."""
    last: Exception | None = None
    for i in range(tries):
        if HARD_CAP["usd"] is not None and spend.total() >= HARD_CAP["usd"]:
            raise spend.BudgetExceeded(f"spent ${spend.total():.2f}, hard cap ${HARD_CAP['usd']:.2f}: no new model call "
                                       f"(rerun with a higher --budget to resume)")
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
