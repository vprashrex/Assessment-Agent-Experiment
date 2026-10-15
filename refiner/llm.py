"""One function: call(model, system, user, schema, tools=None) -> dict.

Anthropic for claude-*, OpenAI Responses for gpt-*/o*. With `tools`, the model may call them (client tools): we run
the Python function, send the result back, and repeat until the model returns the final JSON.
`name` and `metadata` label the call in tracing (see tracing.py).
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from . import tracing

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
load_dotenv()  # and from the current directory

_LOCK = threading.Lock()
_CLIENTS: dict[str, Any] = {}
_DROP = {"minimum", "maximum", "minLength", "maxLength", "pattern", "format", "default", "title", "minItems", "maxItems"}
MAX_TOOL_TURNS = 10

# name -> (description, input_schema, function(**args) -> json-able)
Tools = dict[str, tuple[str, dict, Callable[..., Any]]]


class LLMError(RuntimeError):
    pass


def _clean(schema: Any) -> Any:
    if isinstance(schema, dict):
        out = {k: _clean(v) for k, v in schema.items() if k not in _DROP}
        if isinstance(schema.get("properties"), dict):  # property names are data, never metadata to drop
            out["properties"] = {k: _clean(v) for k, v in schema["properties"].items()}
        if out.get("type") == "object":
            out.setdefault("additionalProperties", False)
        return out
    return [_clean(x) for x in schema] if isinstance(schema, list) else schema


def _client(kind: str):
    with _LOCK:
        if kind not in _CLIENTS:
            if kind == "anthropic":
                import anthropic
                _CLIENTS[kind] = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY"),
                                                     max_retries=4, timeout=1800.0)
            else:
                import openai
                _CLIENTS[kind] = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"), max_retries=4, timeout=1800.0)
        return _CLIENTS[kind]


def _run_tool(tools: Tools, name: str, args: dict, log: list) -> str:
    with tracing.span(name, "tool", input=args) as t:
        try:
            result = tools[name][2](**args)
        except Exception as e:  # the model sees the error and can correct its call
            result = {"error": f"{type(e).__name__}: {e}"}
        t.update(output=result)
    log.append({"tool": name, "args": args, "result": result})
    return json.dumps(result, ensure_ascii=False)


Files = list[tuple[str, bytes]]  # (media_type, bytes): application/pdf or image/*


def _b64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode()


def _anthropic_content(user: str, files: Files) -> list[dict] | str:
    if not files:
        return user
    blocks = [{"type": "document", "source": {"type": "base64", "media_type": mt, "data": _b64(d)}} if mt == "application/pdf"
              else {"type": "image", "source": {"type": "base64", "media_type": mt, "data": _b64(d)}} for mt, d in files]
    return blocks + [{"type": "text", "text": user}]


def _openai_content(user: str, files: Files) -> list[dict]:
    blocks = [{"type": "input_file", "filename": f"file{k}.pdf", "file_data": f"data:{mt};base64,{_b64(d)}"} if mt == "application/pdf"
              else {"type": "input_image", "image_url": f"data:{mt};base64,{_b64(d)}"} for k, (mt, d) in enumerate(files)]
    return blocks + [{"type": "input_text", "text": user}]


def _anthropic(model: str, system: str, user: str, schema: dict, effort: str, tools: Tools | None, log: list, files: Files,
               name: str, meta: dict | None) -> str:
    kw: dict[str, Any] = dict(model=model, max_tokens=16000, system=system, thinking={"type": "adaptive", "display": "summarized"},
                              output_config={"format": {"type": "json_schema", "schema": _clean(schema)}, "effort": effort})
    if tools:
        kw["tools"] = [{"name": n, "description": d, "input_schema": s} for n, (d, s, _) in tools.items()]
    messages: list[dict] = [{"role": "user", "content": _anthropic_content(user, files)}]
    for _ in range(MAX_TOOL_TURNS):
        with tracing.generation(name, model, system, user, files, meta, effort=effort) as record:
            with _client("anthropic").beta.messages.stream(messages=messages, **kw) as s:
                resp = s.get_final_message()
            record(resp)
        if resp.stop_reason == "refusal":
            raise LLMError(f"{model} refused")
        if resp.stop_reason != "tool_use":
            return next((b.text for b in resp.content if b.type == "text"), "")
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": b.id, "content": _run_tool(tools, b.name, b.input, log)}
            for b in resp.content if b.type == "tool_use"]})
    raise LLMError(f"{model}: no final answer after {MAX_TOOL_TURNS} tool turns")


def _openai(model: str, system: str, user: str, schema: dict, effort: str, tools: Tools | None, log: list, files: Files,
            name: str, meta: dict | None) -> str:
    kw: dict[str, Any] = dict(model=model, instructions=system, reasoning={"effort": effort},
                              text={"format": {"type": "json_schema", "name": "out", "schema": _clean(schema), "strict": False}})
    if tools:
        kw["tools"] = [{"type": "function", "name": n, "description": d, "parameters": s} for n, (d, s, _) in tools.items()]

    def create(**args: Any) -> Any:
        with tracing.generation(name, model, system, user, files, meta, effort=effort) as record:
            resp = _client("openai").responses.create(**args, **kw)
            record(resp)
        return resp

    resp = create(input=[{"role": "user", "content": _openai_content(user, files)}])
    for _ in range(MAX_TOOL_TURNS):
        calls = [o for o in resp.output if o.type == "function_call"]
        if not calls:
            return resp.output_text
        outs = [{"type": "function_call_output", "call_id": c.call_id, "output": _run_tool(tools, c.name, json.loads(c.arguments or "{}"), log)}
                for c in calls]
        resp = create(previous_response_id=resp.id, input=outs)
    raise LLMError(f"{model}: no final answer after {MAX_TOOL_TURNS} tool turns")


def call(model: str, system: str, user: str, schema: dict, *, effort: str = "high",
         tools: Tools | None = None, tool_log: list | None = None, files: Files | None = None, tries: int = 4,
         name: str = "llm-call", metadata: dict | None = None) -> dict:
    """Structured JSON from any supported model; retries transport errors and invalid JSON with backoff.
    Every tool call made is appended to `tool_log` as {tool, args, result}."""
    with tracing.span(name, "agent", metadata=metadata) if tools else nullcontext(None) as agent:
        last: Exception | None = None
        for i in range(tries):
            log: list = []
            try:
                text = (_openai(model, system, user, schema, effort, tools, log, files or [], name, metadata)
                        if model.startswith(("gpt-", "o1", "o3", "o4"))
                        else _anthropic(model, system, user, schema, effort, tools, log, files or [], name, metadata))
                out = json.loads(text)
                if tool_log is not None:
                    tool_log.extend(log)
                if agent:
                    agent.update(output=out)
                return out
            except LLMError:
                raise
            except Exception as e:  # network, overload, 5xx, malformed JSON — all retried the same way
                if "invalid_request" in str(e) or "BadRequest" in type(e).__name__:
                    raise
                last = e
                time.sleep(5 * (i + 1))
        raise LLMError(f"{model}: {type(last).__name__}: {str(last)[:200]}")
