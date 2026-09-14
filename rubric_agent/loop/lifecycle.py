"""Before the loop: parse (with operator questions), optional setup review, train/test split, round-0 baseline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.types import interrupt

from .. import parser
from ..core.config import CARRY_CAP, K_FULL, K_RUNS, MODELS, TEST_N, TRAIN_N, WORKERS
from ..core.runio import Run
from ..core.state import RunState
from ..judge.review import review_rows
from ..scorer.score import score_rows
from .measure import fmt, trend_row
from .steps import compute_stats


def parse(state: RunState) -> dict[str, Any]:
    run = Run(state["run_dir"])
    context = state["context"] + "".join(f"\n\nOPERATOR ANSWER: {a}" for a in state.get("operator_answers", []))
    _, questions = parser.run(context, Path(state["sheet_path"]), Path(state["prompt_path"]), Path(state["schema_path"]), run.dir,
                              model=MODELS["parser"], describe_model=MODELS["describe"], max_attachments=state.get("max_attachments"),
                              constitution_path=Path(state.get("constitution_path") or state["prompt_path"]), workers=WORKERS)
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
    """Round 0: fix the train/test split, score v0 k times on a train sample and on the held-out set, review, measure."""
    run = Run(state["run_dir"])
    if not (run.dir / "split.json").exists():
        train = run.draw(TRAIN_N, run.pool(), "train")
        test = run.draw(TEST_N, run.pool() | set(train), "test")
        run.write("split.json", {"train": train, "test": test})
    split = run.json("split.json", {})
    n = state.get("n_random") or 60
    sample = run.draw_from(split["train"], n, set(), "r0")
    k = K_FULL if state.get("k_full") else K_RUNS
    if not (run.dir / "scores/v0_r0.json").exists():
        run.write("scores/v0_r0.json", score_rows(run, run.rubric("v0"), sample, k))
    if not (run.dir / "judge/round_0_v0.json").exists():
        run.write("judge/round_0_v0.json", review_rows(run, run.json("scores/v0_r0.json", {}), sample))
    st = compute_stats(run, run.json("scores/v0_r0.json", {}), run.json("judge/round_0_v0.json", {}), sample)
    run.write("judge/round_0_stats.json", {"v0": st})
    trend_row(run, 0, "v0", st["metrics"], st["disagree"], st["rows"], run.metrics, kept=True)
    line = (f"r00 | v0 baseline | n={len(sample)} k={k} | {fmt(st['metrics'], st['disagree'], run.metrics)} | ICC {st['metrics']['_icc_mean']:.2f} "
            f"| within {st['metrics']['_within_mean']:.2f} | dis {st['disagree'].get('_overall')} | BEST")
    run.append("ledger.md", line)
    run.write("versions.json", {"v0": {"round": 0, "base": None, "icc": st["metrics"]["_icc_mean"], "disagree": st["disagree"].get("_overall"),
                                       "kept": True, "summary": "baseline"}})
    rv = run.json("judge/round_0_v0.json", {})
    run.append("scratchpad.md", f"## Round 0 — Judge\nv0 on {len(sample)} rows × {k} runs. ICC {st['metrics']['_icc_mean']}, within-std "
               f"{st['metrics']['_within_mean']}, disagree {st['disagree'].get('_overall')}%. Issues {st['issues']}\n"
               + "\n".join(rv.get("summaries", [])) + "\nPatterns:\n" + "\n".join(f"- {p}" for p in rv.get("patterns", [])) + "\n")
    flagged = sorted({r["cid"] for r in rv.get("rows", []) if not r["agree"]} | {c for m in run.metrics for c in st["metrics"][m]["unstable"]})
    carry = flagged[:CARRY_CAP]
    stop = state.get("max_rounds", 0) <= 0
    return {"round": 0, "best": "v0", "best_round": 0, "carry": carry, "carry_count": {c: 1 for c in carry}, "consecutive_fail": 0,
            "ledger": [line], "stop": stop, "stop_reason": "circuit breaker: max rounds" if stop else ""}
