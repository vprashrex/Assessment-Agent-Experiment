"""GPT, through the OpenAI Responses API: reasoning effort, JSON-schema output, function calls."""

from __future__ import annotations

import json
from typing import Any

from . import base
from .base import MAX_TOOL_TURNS, Files, LLMError, Tools, b64, clean_schema, run_tool


def _content(user: str, files: Files) -> list[dict]:
    blocks = [{"type": "input_file", "filename": f"file{k}.pdf", "file_data": f"data:{mt};base64,{b64(d)}"} if mt == "application/pdf"
              else {"type": "input_image", "image_url": f"data:{mt};base64,{b64(d)}"} for k, (mt, d) in enumerate(files)]
    return blocks + [{"type": "input_text", "text": user}]


def complete(model: str, system: str, user: str, schema: dict, effort: str | None, tools: Tools | None, log: list,
             files: Files) -> str:
    kw: dict[str, Any] = dict(model=model, instructions=system, **({"reasoning": {"effort": effort}} if effort else {}),
                              text={"format": {"type": "json_schema", "name": "out", "schema": clean_schema(schema), "strict": False}})
    if tools:
        kw["tools"] = [{"type": "function", "name": n, "description": d, "parameters": s} for n, (d, s, _) in tools.items()]

    def create(**args: Any) -> Any:
        return base.client("openai").responses.create(**args, **kw)

    resp = create(input=[{"role": "user", "content": _content(user, files)}])
    for _ in range(MAX_TOOL_TURNS):
        calls = [o for o in resp.output if o.type == "function_call"]
        if not calls:
            return resp.output_text
        outs = [{"type": "function_call_output", "call_id": c.call_id, "output": run_tool(tools, c.name, json.loads(c.arguments or "{}"), log)}
                for c in calls]
        resp = create(previous_response_id=resp.id, input=outs)
    raise LLMError(f"{model}: no final answer after {MAX_TOOL_TURNS} tool turns")
