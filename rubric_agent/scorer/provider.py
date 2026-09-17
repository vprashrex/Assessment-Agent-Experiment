"""Provider-agnostic scorer call: `provider:model` via LangChain; Anthropic goes through core.llm."""

from __future__ import annotations

import os
import threading
from typing import Any

from ..core import llm
from ..core.config import SCORER, SCORER_PARAMS

KEYS = {"google_genai": ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "openai": ("OPENAI_API_KEY",), "anthropic": ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY")}
_MODELS: dict[str, Any] = {}
_LOCK = threading.Lock()


def _base():
    from langchain.chat_models import init_chat_model

    provider = SCORER.split(":", 1)[0]
    key = next((os.getenv(k) for k in KEYS.get(provider, ()) if os.getenv(k)), None)
    params = {"timeout": 120, "max_retries": 3, **({"api_key": key} if key else {}), **SCORER_PARAMS}
    return init_chat_model(SCORER, **params)


def _structured(schema: dict[str, Any], method: str):
    key = (method, repr(sorted(schema.get("properties", {}))))
    with _LOCK:
        if key not in _MODELS:
            _MODELS[key] = _base().with_structured_output(schema, method=method)
        return _MODELS[key]


def score_one(rubric: str, submission: str, schema: dict[str, Any]) -> dict[str, Any]:
    user = submission + "\n\nReturn the JSON object exactly as specified."
    if SCORER.startswith("anthropic:"):
        out, _ = llm.call(SCORER.split(":", 1)[1], rubric, user, schema, role="scorer",
                          effort=SCORER_PARAMS.get("effort", "medium"), retries=0)
        return out
    messages = [("system", rubric), ("human", user)]
    try:
        result = _structured(schema, "json_schema").invoke(messages)
    except Exception:
        result = _structured(schema, "function_calling").invoke(messages)
    return result if isinstance(result, dict) else result.model_dump()
