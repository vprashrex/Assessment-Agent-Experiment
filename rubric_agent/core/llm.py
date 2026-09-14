"""One call path for every LLM role: model + system + user (+ images / PDFs) -> validated JSON.

Uses the Anthropic SDK directly. Structured output via output_config.format; refusal fallbacks for
models that may decline (Judge on fable). Every call is stateless: no history, no tools."""

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

# JSON-schema keywords the structured-output endpoint does not accept; pydantic re-checks them.
_DROP = {
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength",
    "pattern", "format", "default", "title", "minItems", "maxItems", "examples",
}

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
            _CLIENT = anthropic.Anthropic(api_key=key, max_retries=4)
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


def call(
    model: str,
    system: str,
    user: str,
    out: type[BaseModel] | dict[str, Any],
    *,
    role: str = "llm",
    images: list[tuple[str, bytes]] = (),
    pdfs: list[bytes] = (),
    effort: str | None = None,
    max_tokens: int = 16000,
    fallback: str | None = None,
    retries: int = 1,
) -> tuple[Any, dict[str, Any]]:
    """Return (parsed, meta). `out` is a pydantic model class or a raw JSON schema dict.
    Raises Refusal when the whole model chain declined, LLMError when output never validated."""
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
    kwargs: dict[str, Any] = dict(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": blocks}],
        output_config={"format": {"type": "json_schema", "schema": clean_schema(schema)}},
    )
    if effort:
        kwargs["output_config"]["effort"] = effort
    if fallback:
        kwargs["betas"] = ["server-side-fallback-2026-06-01"]
        kwargs["fallbacks"] = [{"model": fallback}]

    last: Exception | None = None
    for _ in range(retries + 1):
        with client().beta.messages.stream(**kwargs) as stream:  # streaming: long outputs would otherwise be refused
            resp = stream.get_final_message()
        meta = {"role": role, "model": model, "served_by": resp.model, "stop": resp.stop_reason,
                "in": resp.usage.input_tokens, "out": resp.usage.output_tokens}
        if resp.stop_reason == "refusal":
            cat = getattr(getattr(resp, "stop_details", None), "category", None)
            raise Refusal(f"{model} refused ({cat})")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            data = json.loads(text)
            return (out.model_validate(data) if is_model else data), meta
        except (json.JSONDecodeError, ValidationError) as e:
            last = e
            kwargs["messages"] = [{"role": "user", "content": blocks + [
                {"type": "text", "text": f"Your previous answer failed validation:\n{e}\nReturn corrected JSON only."}]}]
    raise LLMError(f"{role}: output never validated: {last}")
