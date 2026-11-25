"""Claude, through the Anthropic SDK: streamed, adaptive thinking at the run's effort, JSON-schema output, client tools."""

from __future__ import annotations

from typing import Any

from .. import models, spend
from . import base
from .base import MAX_TOOL_TURNS, Files, LLMError, Tools, b64, clean_schema, run_tool


def _content(user: str, files: Files) -> list[dict] | str:
    if not files:
        return user
    blocks = [{"type": "document", "source": {"type": "base64", "media_type": mt, "data": b64(d)}} if mt == "application/pdf"
              else {"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64(d)}} for mt, d in files]
    return blocks + [{"type": "text", "text": user}]


def complete(model: str, system: str, user: str, schema: dict, effort: str | None, tools: Tools | None, log: list,
             files: Files) -> str:
    kw: dict[str, Any] = dict(model=model, max_tokens=models.max_output(model), system=system,
                              output_config={"format": {"type": "json_schema", "schema": clean_schema(schema)}})
    if effort:  # models without a reasoning setting in models.yaml run without thinking
        kw["thinking"] = {"type": "adaptive", "display": "summarized"}
        kw["output_config"]["effort"] = effort
    if tools:
        kw["tools"] = [{"name": n, "description": d, "input_schema": s} for n, (d, s, _) in tools.items()]
    messages: list[dict] = [{"role": "user", "content": _content(user, files)}]
    for _ in range(MAX_TOOL_TURNS):
        with base.client("anthropic").beta.messages.stream(messages=messages, **kw) as s:
            resp = s.get_final_message()
        u = resp.usage  # every turn is paid for, tool turns included
        spend.record(model, u.input_tokens or 0, u.output_tokens or 0, getattr(u, "cache_creation_input_tokens", 0) or 0,
                     getattr(u, "cache_read_input_tokens", 0) or 0)
        if resp.stop_reason == "refusal":
            raise LLMError(f"{model} refused")
        if resp.stop_reason != "tool_use":
            return next((b.text for b in resp.content if b.type == "text"), "")
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": b.id, "content": run_tool(tools, b.name, b.input, log)}
            for b in resp.content if b.type == "tool_use"]})
    raise LLMError(f"{model}: no final answer after {MAX_TOOL_TURNS} tool turns")
