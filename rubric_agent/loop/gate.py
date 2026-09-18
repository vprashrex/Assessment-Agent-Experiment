"""Keep/revert and assurance checks — plain code. Collapse guard and circuit breaker live here."""

from __future__ import annotations

from typing import Any

from ..core.config import COLLAPSE_DROP, FAIL_RATE_MAX, FAIL_STREAK, K, K_ASSURE
from ..core.runio import Run
from ..core.state import RunState
from .contrib import contrib_md, decompose, noise_floor, parent, tolerances, trade_guard
from .measure import fmt, trend_row
from .plot import plot_all
from .steps import best_stats


def attribute(run: Run, n: int) -> str:
    """Split this round's move in overall std across the metrics and append it to contributions.md.

    Runs after trend_row, so trend.json already carries the round just scored. Returns the table
    so the ledger can carry a one-line version of it.
    """
    trend, versions = run.json("trend.json", []), run.json("versions.json", {})
    rows = [t for t in trend if t.get("per_metric")]
    if len(rows) < 2:
        return ""
    cur = rows[-1]
    base = parent(versions, trend, cur)
    if base is None:
        return ""
    nf = noise_floor(trend, run.metrics, n)
    d = decompose(cur, base, run.metrics, nf["floor"])
    what = (f"round {cur['round']}: re-score of {cur['version']} vs its own round {base['round']}" if cur.get("assure")
            else f"round {cur['round']}: {cur['version']} vs parent {versions.get(cur['version'], {}).get('base')}"
                 f" [{'kept' if cur.get('kept') else 'rejected'}]")
    run.append("contributions.md", contrib_md(d, what) + f"\n\n_noise floor from {nf['source']}_\n")
    drivers = ", ".join(f"{x['metric']} {x['contribution']:+.3f}" for x in d["metrics"] if x["verdict"] in ("better", "worse"))
    return f"drivers: {drivers or 'none beyond the ±%.3f noise floor' % nf['floor']}"


def gate(state: RunState) -> dict[str, Any]:
    run = Run(state["run_dir"])
    rnd, cand, best = state["round"], state["candidate"], state["best"]
    c = run.json(f"stats/round_{rnd}.json", {})[cand]
    b = best_stats(run, state)
    cm, bm, se = c["metrics"], b["metrics"], c["se"]
    d_within, d_stable, d_icc = cm["_within"] - bm["_within"], cm["_stable_pct"] - bm["_stable_pct"], cm["_icc"] - bm["_icc"]
    d_severe = cm["_severe"] - bm["_severe"]
    no_worse = d_icc >= -se["_icc"] and d_within <= se["_within"] and d_stable >= -se["_stable_pct"] and d_severe <= se["_severe"]
    collapse = cm["_icc"] < state["baseline_icc"] - max(3 * se["_icc"], COLLAPSE_DROP)
    versions = run.json("versions.json", {})

    if state["mode"] == "assure":
        reproduced = all(abs(d) <= 2 * se[k] for d, k in ((d_within, "_within"), (d_stable, "_stable_pct"), (d_severe, "_severe"), (d_icc, "_icc")))
        passed = reproduced and not collapse
        line = (f"r{rnd:02d} | ASSURE {best} | n={len(state['sample'])} k={K_ASSURE} | {fmt(cm, run.metrics)} | within {cm['_within']:.2f} vs "
                f"{bm['_within']:.2f} (SE {se['_within']:.3f}) | stable {cm['_stable_pct']:.0f}% vs {bm['_stable_pct']:.0f}% | ICC {cm['_icc']:.2f} vs "
                f"{bm['_icc']:.2f} | {'PASSED' if passed else 'FAILED'}")
        run.append("ledger.md", line)
        trend_row(run, rnd, best, cm, c["rows"], run.metrics, kept=passed, assure=True)
        plot_all(run.dir)
        if (att := attribute(run, len(state["sample"]))):
            run.append("ledger.md", f"       {att}")
        if passed:
            run.append("ledger.md", "STOP: success — consistency held on a repeat run of the best rubric")
        return {"best_round": rnd if passed else state["best_round"], "ledger": state["ledger"] + [line],
                "stop": passed, "stop_reason": "success: assured consistent" if passed else "", "mode": "revise"}

    # Per-metric guard: the aggregate is a mean, so one big improvement can pay for several
    # regressions and still look like progress. Block only when a regression is NOT paid for —
    # i.e. the win vanishes once its largest single contributor is dropped.
    dm = {m: cm[m]["within_std"] - bm[m]["within_std"] for m in run.metrics}
    tol = tolerances(run.metrics, se, noise_floor(run.json("trend.json", []), run.metrics, len(state["sample"]))["floor"])
    tg = trade_guard(dm, tol)

    better = d_within < -se["_within"] or d_stable > se["_stable_pct"]
    kept = better and no_worse and not collapse and not tg["blocked"]
    versions[cand].update(icc=cm["_icc"], within=cm["_within"], stable_pct=cm["_stable_pct"], kept=kept,
                          d_within=round(d_within, 3), d_stable=round(d_stable, 1), d_icc=round(d_icc, 3),
                          regressed=tg["regressed"], loo_within=tg["loo"], traded=tg["blocked"])
    run.write("versions.json", versions)
    trend_row(run, rnd, cand, cm, c["rows"], run.metrics, kept=kept)
    plot_all(run.dir)
    line = (f"r{rnd:02d} | {cand} ← {best} \"{versions[cand]['summary']}\" | n={len(state['sample'])} k={K} | {fmt(cm, run.metrics)} | "
            f"within {cm['_within']:.2f} vs {bm['_within']:.2f} (Δ {d_within:+.3f}, SE {se['_within']:.3f}) | stable {cm['_stable_pct']:.0f}% vs "
            f"{bm['_stable_pct']:.0f}% (Δ {d_stable:+.1f}, SE {se['_stable_pct']:.1f}) | flips {cm['_severe']} vs {bm['_severe']} | ICC {cm['_icc']:.2f} vs {bm['_icc']:.2f}"
            + (" | COLLAPSE" if collapse else "") + (" | TRADED" if tg["blocked"] else "") + f" | {'KEPT' if kept else 'NOT KEPT'}")
    run.append("ledger.md", line)
    run.append("ledger.md", f"       per-metric: {tg['why']}")
    if (att := attribute(run, len(state["sample"]))):
        run.append("ledger.md", f"       {att}")
    fail = 0 if kept else state.get("consecutive_fail", 0) + 1
    reason = (f"fail — scorer unreliable: {cm['_fail_rate']:.0%} of runs failed" if cm["_fail_rate"] > FAIL_RATE_MAX
              else f"fail — no improvement in {FAIL_STREAK} consecutive revisions" if fail >= FAIL_STREAK
              else "ceiling — max rounds reached, best so far handed off" if rnd >= state["max_rounds"] else None)
    if reason:
        run.append("ledger.md", f"STOP: {reason}")
    return {"best": cand if kept else best, "best_round": rnd if kept else state["best_round"], "consecutive_fail": fail,
            "ledger": state["ledger"] + [line], "stop": reason is not None, "stop_reason": reason or ""}
