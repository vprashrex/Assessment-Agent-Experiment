"""Inside a round: score the candidate k times per submission, then measure."""

from __future__ import annotations

from typing import Any

from ..core.config import K, K_ASSURE

CHUNK = 100
from ..core.runio import Run
from ..core.state import RunState
from ..scorer.score import score_rows
from .measure import bootstrap_se, metric_stats, row_deltas, row_stats


def score(state: RunState) -> dict[str, Any]:
    run = Run(state["run_dir"])
    v, rnd = state["candidate"], state["round"]
    f = f"scores/{v}_r{rnd}.json"
    have = run.json(f, {})
    todo = [c for c in state["sample"] if c not in have]
    k = K_ASSURE if state.get("mode") == "assure" else K
    for i in range(0, len(todo), CHUNK):
        have.update(score_rows(run, run.rubric(v), todo[i:i + CHUNK], k))
        run.write(f, have)
    return {}


def best_stats(run: Run, state: RunState) -> dict[str, Any]:
    return run.json(f"stats/round_{state['best_round']}.json", {})[state["best"]]


def measure(state: RunState) -> dict[str, Any]:
    run = Run(state["run_dir"])
    v, rnd = state["candidate"], state["round"]
    lo, hi = run.scale
    rows = row_stats(run.json(f"scores/{v}_r{rnd}.json", {}), run.metrics)
    ms = metric_stats(rows, run.metrics, lo, hi)
    prev = best_stats(run, state)["rows"]
    run.write(f"stats/round_{rnd}.json", {v: {"rows": rows, "metrics": ms, "se": bootstrap_se(rows, run.metrics, lo, hi),
                                             "deltas": row_deltas(rows, prev, run.metrics)}})
    return {}
