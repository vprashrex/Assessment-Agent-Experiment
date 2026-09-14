"""Keep/revert gate — plain code, never skippable.
Two axes: consistency (mean ICC, bootstrap SE) and quality (Judge disagree %, binomial SE). KEPT on the train
sample iff at least one axis improves beyond its noise band and neither regresses beyond it; then confirmed on
the held-out split. Records the trend row and carry-over. Circuit breaker lives here too."""

from __future__ import annotations

import math
from typing import Any

from ..core.config import CARRY_CAP, CARRY_RETIRE, K_RUNS
from ..core.runio import Run
from ..core.state import RunState
from ..judge.review import review_rows
from ..scorer.score import score_rows
from .measure import fmt, icc_bootstrap_se, trend_row
from .steps import compute_stats


def heldout(run: Run, version: str) -> dict[str, Any]:
    """Score + review `version` on the held-out split once; cached under scores/<v>_test.json, judge/test_<v>.json."""
    test = run.json("split.json", {})["test"]
    if not (run.dir / f"scores/{version}_test.json").exists():
        run.write(f"scores/{version}_test.json", score_rows(run, run.rubric(version), test, K_RUNS))
    if not (run.dir / f"judge/test_{version}.json").exists():
        run.write(f"judge/test_{version}.json", review_rows(run, run.json(f"scores/{version}_test.json", {}), test))
    return compute_stats(run, run.json(f"scores/{version}_test.json", {}), run.json(f"judge/test_{version}.json", {}), test)


def gate(state: RunState) -> dict[str, Any]:
    run = Run(state["run_dir"])
    rnd, cand, best = state["round"], state["candidate"], state["best"]
    spec = run.setup.metrics
    st = run.json(f"judge/round_{rnd}_stats.json", {})
    c, b = st[cand], st[best]
    se_icc = icc_bootstrap_se(c["rows"], run.metrics, spec[0].min, spec[0].max)
    d_icc = c["metrics"]["_icc_mean"] - b["metrics"]["_icc_mean"]
    p = (b["disagree"].get("_overall") or 0) / 100
    n_cells = max(1, len(state["sample"]) * len(run.metrics))
    se_dis = 100 * math.sqrt(max(p * (1 - p), 0.01) / n_cells)
    d_dis = (c["disagree"].get("_overall") or 0) - (b["disagree"].get("_overall") or 0)
    # two axes: consistency (ICC) and quality (Judge disagree %). KEPT if either improves beyond its noise band
    # and neither regresses beyond it; then confirmed on rows the loop never tunes on.
    better_icc, better_dis = d_icc > se_icc, d_dis < -se_dis
    no_worse = d_icc >= -se_icc and d_dis <= se_dis
    kept_train = no_worse and (better_icc or better_dis)
    axis = "consistency+quality" if better_icc and better_dis else "consistency" if better_icc else "quality" if better_dis else ""
    note = ""
    if kept_train:
        hc, hb = heldout(run, cand), heldout(run, best)
        se_h = icc_bootstrap_se(hc["rows"], run.metrics, spec[0].min, spec[0].max)
        kept = hc["metrics"]["_icc_mean"] >= hb["metrics"]["_icc_mean"] - se_h and \
            (hc["disagree"].get("_overall") or 0) <= (hb["disagree"].get("_overall") or 0) + se_dis
        note = (f" | held-out ICC {hc['metrics']['_icc_mean']:.2f} vs {hb['metrics']['_icc_mean']:.2f}, dis {hc['disagree'].get('_overall')} vs "
                f"{hb['disagree'].get('_overall')} | axis {axis}")
    else:
        kept = False
    versions = run.json("versions.json", {})
    versions[cand].update(icc=c["metrics"]["_icc_mean"], disagree=c["disagree"].get("_overall"), kept=kept, d_icc=round(d_icc, 3), se_icc=round(se_icc, 3))
    run.write("versions.json", versions)
    trend_row(run, rnd, cand, c["metrics"], c["disagree"], c["rows"], run.metrics, kept=kept, d_icc=round(d_icc, 3), se=round(se_icc, 3))
    line = (f"r{rnd:02d} | {cand} ← {best} \"{versions[cand]['summary']}\" | n={len(state['sample'])} k={K_RUNS} | {fmt(c['metrics'], c['disagree'], run.metrics)}"
            f" | ICC {c['metrics']['_icc_mean']:.2f} vs {b['metrics']['_icc_mean']:.2f} (Δ {d_icc:+.3f}, SE {se_icc:.3f}) | dis {c['disagree'].get('_overall')} vs "
            f"{b['disagree'].get('_overall')} (Δ {d_dis:+.1f}, SE {se_dis:.1f}){note} | {'KEPT' if kept else 'NOT KEPT'}")
    run.append("ledger.md", line)

    counts, carry = dict(state.get("carry_count", {})), []
    flagged = {r["cid"] for r in run.json(f"judge/round_{rnd}_{cand}.json", {}).get("rows", []) if not r["agree"]}
    flagged |= {cid for m in run.metrics for cid in c["metrics"][m]["unstable"]}
    for cid in sorted(flagged):
        counts[cid] = counts.get(cid, 0) + 1
        if counts[cid] > CARRY_RETIRE:
            run.append("unresolved.md", f"{cid}: flagged {counts[cid]} rounds running (last {cand})")
        else:
            carry.append(cid)
    carry = carry[:CARRY_CAP]

    fail = 0 if kept else state.get("consecutive_fail", 0) + 1
    err = c["metrics"]["_fail_rate"]
    reason = (f"circuit breaker: {err:.0%} of scorer runs failed" if err > 0.3
              else "circuit breaker: max rounds" if rnd >= state["max_rounds"] else None)
    if reason:
        run.append("ledger.md", f"STOP: {reason}")
    return {"best": cand if kept else best, "best_round": rnd if kept else state["best_round"], "consecutive_fail": fail,
            "carry": carry, "carry_count": {x: counts[x] for x in carry}, "ledger": state["ledger"] + [line],
            "stop": reason is not None, "stop_reason": reason or ""}
