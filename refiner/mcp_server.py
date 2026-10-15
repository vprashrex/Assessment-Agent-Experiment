"""FastMCP server for the rubric refiner (stdio), for Claude Desktop, Claude Code or any MCP client.

    fastmcp run refiner/mcp_server.py           # or: python -m refiner.mcp_server, or the `refiner-mcp` script
    fastmcp install claude-desktop refiner/mcp_server.py --project . --env REFINER_WORKDIR=$PWD

Relative paths resolve against REFINER_WORKDIR (default: the directory the server was started in).
Model calls take minutes and a refinement takes hours, so prepare_run and start_run launch background processes
and return at once; poll with run_status.
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

from refiner import api  # absolute imports: `fastmcp run` loads this file by path
from refiner.config import DEFAULT_MODEL, RunConfig

if os.getenv("REFINER_WORKDIR"):
    os.chdir(os.environ["REFINER_WORKDIR"])

mcp = FastMCP("rubric-refiner", instructions=(
    "Refines an assessment prompt (rubric) until a scoring model's outputs agree with human reference judgements in a "
    "spreadsheet. Only the metrics layer of the prompt is edited; the programme context, global notes and output format "
    "stay word for word. Flow: prepare_run, then run_status until the setup is ready (it may return questions, which the "
    "operator answers in the context file before calling prepare_run again) -> start_run -> run_status while it runs "
    "(it takes hours) -> get_checklist, get_version, get_final_prompt. Paths may be relative to the working folder."))

READ = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}


def _cfg(sheet: str, context: str, prompt: str, run: str, **kw) -> RunConfig:
    return RunConfig(sheet=sheet, context=context, prompt=prompt, run=run, **{k: v for k, v in kw.items() if v is not None})


@mcp.tool(annotations={"openWorldHint": True})
def prepare_run(sheet: str, context: str, prompt: str, run: str, schema: str | None = None, docs_dir: str | None = None,
                sheet_name: str | None = None, model: str = DEFAULT_MODEL, effort: str = "high",
                n: int | None = None) -> dict:
    """Prepare a run without scoring, in the background. The parser maps the sheet's columns and the output field,
    cuts the prompt into layers (program, metrics, notes, output; only metrics will ever be edited) and fetches every
    submission's attachments. Poll run_status: it shows the setup to review, or questions to answer in the context file.

    sheet: spreadsheet with submissions and reference judgements. context: operator notes. prompt: the prompt in use
    today (v0). run: run folder. schema: optional output schema (JSON). docs_dir: folder of downloaded files for links
    that cannot be fetched. effort: reasoning effort, low, medium or high. n: use only the first n submissions."""
    return api.start(_cfg(sheet, context, prompt, run, schema=schema, docs_dir=docs_dir, sheet_name=sheet_name,
                          model=model, effort=effort, n=n), prepare_only=True)


@mcp.tool(annotations={"openWorldHint": True})
def start_run(sheet: str, context: str, prompt: str, run: str, schema: str | None = None, docs_dir: str | None = None,
              sheet_name: str | None = None, model: str = DEFAULT_MODEL, scorer: str | None = None, effort: str = "high",
              rounds: int = 8, patience: int = 4, target: float | None = None, n: int | None = None,
              workers: int = 8) -> dict:
    """Start or resume the refinement in the background; returns at once. Same arguments as prepare_run, plus
    scorer (scoring model, defaults to model) and the stop rules: rounds (ceiling), patience (rejected rounds in a
    row), target (stop at this MAE)."""
    return api.start(_cfg(sheet, context, prompt, run, schema=schema, docs_dir=docs_dir, sheet_name=sheet_name, model=model,
                          scorer=scorer, effort=effort, rounds=rounds, patience=patience, target=target, n=n,
                          workers=workers))


@mcp.tool(annotations=READ)
def run_status(run: str) -> dict:
    """Where a run stands: running or not, the setup or the parser's questions, the round, the best version, MAE / bias /
    within ±1 / ±2 of every version with its verdict, the issue checklist with statuses, locked-layer flags, the stop reason."""
    return api.status(run)


@mcp.tool(annotations=READ)
def get_checklist(run: str) -> dict:
    """The full issue checklist: each issue's root cause, items, rubric clause, fix and its status in every round
    (new, open, resolved, reopened, watch — measured by code)."""
    return api.checklist(run)


@mcp.tool(annotations=READ)
def get_version(run: str, version: str) -> dict:
    """One version of the prompt (v0, v1, ...): its numbers, verdict, full text and what changed."""
    return api.version(run, version)


@mcp.tool(annotations=READ)
def get_final_prompt(run: str) -> str:
    """The best prompt so far, ready to use."""
    st = api.status(run)
    return api.version(run, st["best"])["prompt"] if st.get("best") else "(no version scored yet)"


@mcp.tool(annotations=READ)
def list_runs(root: str = "runs") -> list[dict]:
    """Every refiner run under a folder (default: runs), newest first."""
    return api.list_runs(root)


@mcp.tool(annotations={"destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
def stop_run(run: str) -> dict:
    """Stop a background run. Progress is kept; start_run with the same folder resumes it."""
    return api.stop(run)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
