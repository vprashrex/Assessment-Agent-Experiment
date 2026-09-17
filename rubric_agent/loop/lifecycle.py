"""Before the loop: parse (with operator questions), optional setup review, round-0 baseline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.types import interrupt

from .. import parser
from ..core.config import K
from ..core.runio import Run
from ..core.state import RunState
from ..scorer.score import score_rows
from .measure import bootstrap_se, fmt, metric_stats, row_stats, trend_row
from .plot import plot_all


def parse(state: RunState) -> dict[str, Any]:
    run = Run(state["run_dir"])
    context = state["context"] + "".join(f"\n\nOPERATOR ANSWER: {a}" for a in state.get("operator_answers", []))
    _, questions = parser.run(context, Path(state["sheet_path"]), run.dir,
                              prompt_path=Path(state["prompt_path"]) if state.get("prompt_path") else None,
                              schema_path=Path(state["schema_path"]) if state.get("schema_path") else None,
                              max_attachments=state.get("max_attachments"))
    return {"needs_input": questions}


def ask_operator(state: RunState) -> dict[str, Any]:
    answer = interrupt({"questions": state["needs_input"]})
    return {"operator_answers": state.get("operator_answers", []) + [str(answer)], "needs_input": []}


def review_setup(state: RunState) -> dict[str, Any]:
    if not state.get("review"):
        return {}
    run = Run(state["run_dir"])
    edited = interrupt({"review": "setup.md — return 'approve' or the full edited text", "setup_md": run.text("setup.md")})
    if isinstance(edited, str) and edited.strip() and edited.strip().lower() != "approve":
        run.write("setup.md", edited)
    return {}


def baseline(state: RunState) -> dict[str, Any]:
    run = Run(state["run_dir"])
    sample = run.sample(state.get("n"))
    lo, hi = run.scale
    if not (run.dir / "scores/v0_r0.json").exists():
        run.write("scores/v0_r0.json", score_rows(run, run.rubric("v0"), sample, K))
    rows = row_stats(run.json("scores/v0_r0.json", {}), run.metrics)
    ms = metric_stats(rows, run.metrics, lo, hi)
    run.write("stats/round_0.json", {"v0": {"rows": rows, "metrics": ms, "se": bootstrap_se(rows, run.metrics, lo, hi), "deltas": {}}})
    trend_row(run, 0, "v0", ms, rows, run.metrics, kept=True)
    plot_all(run.dir)
    line = (f"r00 | v0 baseline | n={len(sample)} k={K} | {fmt(ms, run.metrics)} | stable {ms['_stable_pct']:.0f}% | std {ms['_within']:.2f} "
            f"| flips {ms['_severe']} | ICC {ms['_icc']:.2f} | fail {ms['_fail_rate']:.0%} | BEST")
    run.append("ledger.md", line)
    run.write("versions.json", {"v0": {"round": 0, "base": None, "icc": ms["_icc"], "within": ms["_within"], "stable_pct": ms["_stable_pct"],
                                       "kept": True, "summary": "baseline"}})
    run.append("scratchpad.md", f"## Round 0 — Measure\nv0 on {len(sample)} rows × {K} runs: within-std {ms['_within']}, stable {ms['_stable_pct']}%, "
               f"ICC {ms['_icc']}. Unstable per metric: {{{', '.join(f'{m}: {len(ms[m]['unstable'])}' for m in run.metrics)}}}\n")
    stop = state.get("max_rounds", 0) <= 0
    return {"round": 0, "best": "v0", "best_round": 0, "baseline_icc": ms["_icc"], "sample": sample, "mode": "revise",
            "consecutive_fail": 0, "ledger": [line], "stop": stop, "stop_reason": "ceiling — max rounds is 0" if stop else ""}
