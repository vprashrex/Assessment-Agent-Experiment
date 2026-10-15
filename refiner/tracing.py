"""Langfuse tracing. The only module that knows about Langfuse; the rest of the code calls span, generation and bind.

On only when TRACING=true (environment or .env) and the Langfuse keys are set; otherwise every call here
is a no-op and Langfuse is never imported.

One trace per unit of work; all traces of a run share one session (the run folder's name):
  prepare-run     parse-sheet (generation)
  refine-round    score-items > score-item · review-items > review-item · summarise-round (agent) > generations + tools ·
                  write-candidate
Attached files are recorded as a placeholder (media type, size), never uploaded: they are real people's work.
"""

from __future__ import annotations

import contextvars
import json
import os
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, Callable, Iterator

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")  # before the Langfuse client reads its settings
load_dotenv()

ON = (os.getenv("TRACING", "false").strip().lower() == "true"
      and bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")))


class _Off:
    def update(self, **_: Any) -> "_Off":
        return self


@contextmanager
def span(name: str, as_type: str = "span", session: str | None = None, **kw: Any) -> Iterator[Any]:
    """An observation under the current one. With `session`, a new trace in that session whose metadata every
    observation under it inherits. Errors raised inside are recorded on it and re-raised."""
    if not ON:
        yield _Off()
        return
    from langfuse import get_client, propagate_attributes
    meta = {k: str(v) for k, v in (kw.get("metadata") or {}).items()}
    with get_client().start_as_current_observation(name=name, as_type=as_type, **kw) as o, \
            (propagate_attributes(session_id=session, trace_name=name, metadata=meta) if session else nullcontext()):
        try:
            yield o
        except Exception as e:
            o.update(level="ERROR", status_message=f"{type(e).__name__}: {str(e)[:500]}")
            raise


@contextmanager
def generation(name: str, model: str, system: str, user: str, files: list[tuple[str, bytes]], metadata: dict | None,
               **params: Any) -> Iterator[Callable[[Any], None]]:
    """One model request. Yields `record(response)`, which stores the answer, tool calls, thinking and token usage of
    an Anthropic Message or an OpenAI Response."""
    if not ON:
        yield lambda _: None
        return
    content = [*({"type": "file", "media_type": mt, "bytes": len(d)} for mt, d in files), {"type": "text", "text": user}]
    with span(name, "generation", model=model, metadata=metadata, model_parameters=params,
              input=[{"role": "system", "content": system}, {"role": "user", "content": content if files else user}]) as g:
        yield lambda resp: g.update(model=resp.model, **(_anthropic(resp) if hasattr(resp, "stop_reason") else _openai(resp)))


def _said(text: str, calls: list[tuple[str, str, Any]], thinking: str = "") -> dict:
    msg: dict[str, Any] = {"role": "assistant", "content": text, **({"thinking": thinking} if thinking else {})}
    if calls:
        msg["tool_calls"] = [{"id": i, "type": "function", "function": {"name": n, "arguments": json.dumps(a, ensure_ascii=False)}}
                             for i, n, a in calls]
    return msg


def _anthropic(resp: Any) -> dict:
    b = resp.content
    u = resp.usage
    return {"output": _said(next((x.text for x in b if x.type == "text"), ""), [(x.id, x.name, x.input) for x in b if x.type == "tool_use"],
                            "\n\n".join(x.thinking for x in b if x.type == "thinking" and x.thinking)),
            "usage_details": {k: v for k, v in {"input": u.input_tokens, "output": u.output_tokens, "cache_read_input_tokens":
                              u.cache_read_input_tokens, "cache_creation_input_tokens": u.cache_creation_input_tokens}.items() if v},
            **({"level": "WARNING", "status_message": "refusal"} if resp.stop_reason == "refusal" else {})}


def _openai(resp: Any) -> dict:
    u = resp.usage
    calls = [(c.call_id, c.name, json.loads(c.arguments or "{}")) for c in resp.output if c.type == "function_call"]
    usage = {"prompt_tokens": u.input_tokens, "completion_tokens": u.output_tokens, "total_tokens": u.total_tokens,  # OpenAI-style:
             "prompt_tokens_details": {"cached_tokens": u.input_tokens_details.cached_tokens or 0},  # Langfuse maps it
             "completion_tokens_details": {"reasoning_tokens": u.output_tokens_details.reasoning_tokens or 0}} if u else None
    return {"output": _said(resp.output_text, calls), **({"usage_details": usage} if usage else {})}


def bind(fn: Callable) -> Callable:
    """`fn` for a worker thread, run inside the caller's tracing context so its observations nest correctly."""
    ctx = contextvars.copy_context()
    return lambda *args: ctx.copy().run(fn, *args)


def flush() -> None:
    if ON:
        from langfuse import get_client
        get_client().flush()
