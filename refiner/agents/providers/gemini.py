"""Gemini, through the google-genai SDK: structured JSON output (response_json_schema), thinking level, files as
inline parts. No tool calling, so Gemini models are offered as the scorer only."""

from __future__ import annotations

from .. import spend
from . import base
from .base import Files, LLMError, Tools, clean_schema


def complete(model: str, system: str, user: str, schema: dict, effort: str | None, tools: Tools | None, log: list,
             files: Files) -> str:
    if tools:
        raise LLMError(f"{model}: tool calling is not supported for Gemini models here")
    from google.genai import types

    parts = [types.Part.from_bytes(data=d, mime_type=mt) for mt, d in files] + [types.Part.from_text(text=user)]
    config = types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                                         response_json_schema=clean_schema(schema),
                                         thinking_config=types.ThinkingConfig(thinking_level=effort.upper()) if effort else None)
    resp = base.client("google").models.generate_content(
        model=model, contents=[types.Content(role="user", parts=parts)], config=config)
    if u := getattr(resp, "usage_metadata", None):
        spend.record(model, u.prompt_token_count or 0, (u.candidates_token_count or 0) + (getattr(u, "thoughts_token_count", 0) or 0),
                     cache_read=getattr(u, "cached_content_token_count", 0) or 0)
    if not resp.text:
        reason = resp.candidates[0].finish_reason if resp.candidates else "no candidates"
        raise LLMError(f"{model}: empty answer ({reason})")
    return resp.text
