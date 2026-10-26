"""What every provider shares: the error type, the tool and file types, schema cleaning, running a tool, and one
lazily created SDK client per provider. API keys come from .env (project root) or the environment."""

from __future__ import annotations

import base64
import json
import os
import threading
from typing import Any, Callable

from dotenv import load_dotenv

from ...paths import ROOT

load_dotenv(ROOT / ".env")
load_dotenv()  # and from the current directory

MAX_TOOL_TURNS = 10
_LOCK = threading.Lock()
_CLIENTS: dict[str, Any] = {}
_DROP = {"minimum", "maximum", "minLength", "maxLength", "pattern", "format", "default", "title", "minItems", "maxItems"}

# name -> (description, input_schema, function(**args) -> json-able)
Tools = dict[str, tuple[str, dict, Callable[..., Any]]]
Files = list[tuple[str, bytes]]  # (media_type, bytes): application/pdf or image/*


class LLMError(RuntimeError):
    pass


def clean_schema(schema: Any) -> Any:
    if isinstance(schema, dict):
        out = {k: clean_schema(v) for k, v in schema.items() if k not in _DROP}
        if isinstance(schema.get("properties"), dict):  # property names are data, never metadata to drop
            out["properties"] = {k: clean_schema(v) for k, v in schema["properties"].items()}
        if out.get("type") == "object":
            out.setdefault("additionalProperties", False)
        return out
    return [clean_schema(x) for x in schema] if isinstance(schema, list) else schema


def client(kind: str):
    with _LOCK:
        if kind not in _CLIENTS:
            if kind == "anthropic":
                import anthropic
                _CLIENTS[kind] = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY"),
                                                     max_retries=4, timeout=1800.0)
            elif kind == "google":
                from google import genai
                _CLIENTS[kind] = genai.Client(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
            else:
                import openai
                _CLIENTS[kind] = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"), max_retries=4, timeout=1800.0)
        return _CLIENTS[kind]


def run_tool(tools: Tools, name: str, args: dict, log: list) -> str:
    try:
        result = tools[name][2](**args)
    except Exception as e:  # the model sees the error and can correct its call
        result = {"error": f"{type(e).__name__}: {e}"}
    log.append({"tool": name, "args": args, "result": result})
    return json.dumps(result, ensure_ascii=False)


def b64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode()
