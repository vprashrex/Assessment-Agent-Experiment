"""The rubric agent's server: the agent's actions (MCP). The plain HTTP routes are in routes.py, file previews in
inspect.py; both are wired in here.

    uv run refiner-server        # HTTP on 127.0.0.1:8765: /mcp, /events/{chat_id}, /health/{chat_id}, /runs/{chat_id}/…
    uv run refiner-mcp           # the same actions over stdio, for Claude Desktop / Claude Code

Every action takes a chat_id: the chat's folder in the refiner's own data folder (refiner/paths.py) holds its
uploaded inputs and its run. Files arrive only through this server (POST /chats/{chat_id}/inputs, add_context_note);
nothing else writes there. File arguments are names of files uploaded to that chat. Model calls take minutes and a
refinement takes hours, so prepare_run and start_run start background processes and return at once.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastmcp import FastMCP

from refiner import api, paths  # absolute imports: `fastmcp run` loads this file by path
from refiner.config import DEFAULTS, RunConfig
from refiner.mcp import inspect, routes
from refiner.prompts import mcp as mcp_prompts

mcp = FastMCP("rubric-agent", instructions=mcp_prompts.INSTRUCTIONS)
CONTEXT_FILE = "context.md"  # where answers go when the user uploaded no context notes

READ = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}


def _cfg(chat_id: str, sheet: str, context: str | None, prompt: str, schema: str | None, docs_dir: str | None, **kw) -> RunConfig:
    f = lambda name: paths.input_file(chat_id, name)  # noqa: E731
    return RunConfig(sheet=f(sheet), context=f(context), prompt=f(prompt), schema=f(schema), docs_dir=f(docs_dir),
                     run=str(paths.run_dir(chat_id)), **{k: v for k, v in kw.items() if v is not None})


@mcp.tool(annotations=READ, description=mcp_prompts.TOOLS["list_inputs"])
def list_inputs(chat_id: str) -> dict:
    return inspect.inputs(chat_id)


@mcp.tool(annotations=READ, description=mcp_prompts.TOOLS["inspect_inputs"])
def inspect_inputs(chat_id: str) -> dict:
    d = paths.inputs_dir(chat_id)
    if not d.exists():
        return {"files": []}
    return {"files": [inspect.peek(x) for x in sorted(d.iterdir()) if not x.name.startswith(".")]}


@mcp.tool(annotations={"destructiveHint": False, "openWorldHint": False}, description=mcp_prompts.TOOLS["add_context_note"])
def add_context_note(chat_id: str, note: str, context: str | None = None) -> str:
    note = note.strip()
    if not note:
        raise ValueError("The note is empty.")
    if context:
        file = Path(paths.input_file(chat_id, context) or "")
        if not file.is_file():
            raise ValueError(f"No uploaded file named {context}.")
    else:  # no context file yet: the answers start one in the chat's inputs
        file = paths.inputs_dir(chat_id) / CONTEXT_FILE
        file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("a", encoding="utf-8") as f:
        f.write(f"\n\n## Answers\n{note}\n")
    return f"Added to the context notes in {file.name}; pass context={file.name!r} when preparing again."


@mcp.tool(annotations={"openWorldHint": True}, description=mcp_prompts.TOOLS["prepare_run"])
def prepare_run(chat_id: str, sheet: str, prompt: str, context: str | None = None, schema: str | None = None, docs_dir: str | None = None,
                sheet_name: str | None = None, model: str = DEFAULTS["model"], parser_model: str | None = None,
                effort: str = DEFAULTS["effort"], n: int | None = None, split: str = DEFAULTS["split"],
                seed: int = DEFAULTS["seed"]) -> dict:
    return api.start(_cfg(chat_id, sheet, context, prompt, schema, docs_dir, sheet_name=sheet_name, model=model,
                          parser_model=parser_model, effort=effort, n=n, split=split, seed=seed), prepare_only=True)


@mcp.tool(annotations={"openWorldHint": True}, description=mcp_prompts.TOOLS["start_run"])
def start_run(chat_id: str, sheet: str, prompt: str, context: str | None = None, schema: str | None = None, docs_dir: str | None = None,
              sheet_name: str | None = None, model: str = DEFAULTS["model"], parser_model: str | None = None,
              judge_model: str | None = None, generator_model: str | None = None, scorer: str | None = None,
              effort: str = DEFAULTS["effort"], scorer_effort: str | None = None, rounds: int = DEFAULTS["rounds"],
              patience: int = DEFAULTS["patience"], target: float | None = None, n: int | None = None,
              split: str = DEFAULTS["split"], seed: int = DEFAULTS["seed"]) -> dict:
    return api.start(_cfg(chat_id, sheet, context, prompt, schema, docs_dir, sheet_name=sheet_name, model=model,
                          parser_model=parser_model, judge_model=judge_model, generator_model=generator_model,
                          scorer=scorer, effort=effort, scorer_effort=scorer_effort, rounds=rounds,
                          patience=patience, target=target, n=n, split=split, seed=seed))


@mcp.tool(annotations=READ, description=mcp_prompts.TOOLS["run_status"])
def run_status(chat_id: str) -> dict:
    return {**api.status(str(paths.run_dir(chat_id))), "health": api.health(str(paths.run_dir(chat_id)))}


@mcp.tool(annotations={"destructiveHint": False, "idempotentHint": True, "openWorldHint": False}, description=mcp_prompts.TOOLS["stop_run"])
def stop_run(chat_id: str) -> dict:
    return api.stop(str(paths.run_dir(chat_id)))


@mcp.tool(annotations=READ, description=mcp_prompts.TOOLS["get_checklist"])
def get_checklist(chat_id: str, metric: str | None = None) -> dict:
    d = paths.run_dir(chat_id)
    return api.checklist(str(api.metric_dir(str(d), metric)[0] if metric else d))


@mcp.tool(annotations=READ, description=mcp_prompts.TOOLS["get_version_report"])
def get_version_report(chat_id: str, metric: str | None = None) -> dict:
    return api.version_report(str(paths.run_dir(chat_id)), metric)


@mcp.tool(annotations=READ, description=mcp_prompts.TOOLS["get_rubric"])
def get_rubric(chat_id: str, metric: str, version: str) -> dict:
    return api.rubric(str(paths.run_dir(chat_id)), metric, version)


@mcp.tool(annotations=READ, description=mcp_prompts.TOOLS["get_report"])
def get_report(chat_id: str) -> dict:
    return api.report(str(paths.run_dir(chat_id))) or {"note": "the report is written when the run finishes"}


@mcp.tool(annotations=READ, description=mcp_prompts.TOOLS["get_final_prompt"])
def get_final_prompt(chat_id: str) -> str:
    p = paths.run_dir(chat_id) / "final_prompt.md"
    return p.read_text() if p.exists() else "(no final rubric yet)"


routes.register(mcp)


def main() -> None:
    """stdio, for Claude Desktop / Claude Code."""
    mcp.run()


def serve() -> None:
    """HTTP on 127.0.0.1 (RUBRIC_AGENT_HOST / RUBRIC_AGENT_PORT): the agent's actions at /mcp plus the routes above."""
    mcp.run(transport="http", host=os.getenv("RUBRIC_AGENT_HOST", "127.0.0.1"),
            port=int(os.getenv("RUBRIC_AGENT_PORT", "8765")), show_banner=False)


if __name__ == "__main__":
    main()
