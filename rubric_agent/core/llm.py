"""Anthropic calls for the agents (parser, generator): streaming, schema-enforced JSON, long timeout."""

from __future__ import annotations

import base64
import json
import os
import threading
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv()

_DROP = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength",
         "pattern", "format", "default", "title", "minItems", "maxItems", "examples"}
_CLIENT: anthropic.Anthropic | None = None
_LOCK = threading.Lock()


class LLMError(RuntimeError):
    pass


class Refusal(LLMError):
    pass


def client() -> anthropic.Anthropic:
    global _CLIENT
    with _LOCK:
        if _CLIENT is None:
            key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
            _CLIENT = anthropic.Anthropic(api_key=key, max_retries=4,
                                          timeout=anthropic.Timeout(1800.0, read=900.0, write=60.0, connect=30.0))
    return _CLIENT


def clean_schema(schema: Any) -> Any:
    if isinstance(schema, dict):
        out = {k: clean_schema(v) for k, v in schema.items() if k not in _DROP}
        if out.get("type") == "object" and "additionalProperties" not in out:
            out["additionalProperties"] = False
        return out
    if isinstance(schema, list):
        return [clean_schema(x) for x in schema]
    return schema


def call(model: str, system: str, user: str, out: type[BaseModel] | dict[str, Any], *, role: str = "llm",
         images: list[tuple[str, bytes]] = (), pdfs: list[bytes] = (), effort: str | None = None,
         max_tokens: int = 16000, retries: int = 1) -> tuple[Any, dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for media_type, data in images:
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": media_type,
                                                    "data": base64.standard_b64encode(data).decode()}})
    for data in pdfs:
        blocks.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                       "data": base64.standard_b64encode(data).decode()}})
    blocks.append({"type": "text", "text": user})
    is_model = isinstance(out, type) and issubclass(out, BaseModel)
    schema = out.model_json_schema() if is_model else out
    kwargs: dict[str, Any] = dict(model=model, max_tokens=max_tokens, system=system,
                                  messages=[{"role": "user", "content": blocks}],
                                  thinking={"type": "adaptive", "display": "summarized"},
                                  output_config={"format": {"type": "json_schema", "schema": clean_schema(schema)}})
    if effort:
        kwargs["output_config"]["effort"] = effort

    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            with client().beta.messages.stream(**kwargs) as stream:
                resp = stream.get_final_message()
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
            last = e
            continue
        meta = {"role": role, "model": model, "served_by": resp.model, "stop": resp.stop_reason,
                "in": resp.usage.input_tokens, "out": resp.usage.output_tokens}
        if resp.stop_reason == "refusal":
            raise Refusal(f"{model} refused ({getattr(getattr(resp, 'stop_details', None), 'category', None)})")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            data = json.loads(text)
            return (out.model_validate(data) if is_model else data), meta
        except (json.JSONDecodeError, ValidationError) as e:
            last = e
            kwargs["messages"] = [{"role": "user", "content": blocks + [
                {"type": "text", "text": f"Your previous answer failed validation:\n{e}\nReturn corrected JSON only."}]}]
    raise LLMError(f"{role}: {type(last).__name__}: {str(last)[:300]}")
