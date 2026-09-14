"""Harness steps inside a round: sample train rows, score candidate + best k times, compute stats after review."""

from __future__ import annotations

from typing import Any

from ..core.config import K_RUNS
from ..core.runio import Run
from ..core.state import RunState
from ..scorer.score import score_rows
from .measure import concordance, disagreement, mean, metric_stats, row_stats


def sample(state: RunState) -> dict[str, Any]:
    """random N from the train split (Generator's choice) + carry-over (last round's unstable/disagreed rows)."""
    run = Run(state["run_dir"])
    train, carry = run.json("split.json", {})["train"], state.get("carry", [])
    fresh = run.draw_from(train, state["n_random"], set(carry), f"r{state['round']}")
    return {"sample": fresh + carry}


def score(state: RunState) -> dict[str, Any]:
    """Score candidate AND best on the same rows, k runs each (paired); rows already scored this round are skipped."""
    run = Run(state["run_dir"])
    for v in (state["candidate"], state["best"]):
        f = f"scores/{v}_r{state['round']}.json"
        have = run.json(f, {})
        todo = [c for c in state["sample"] if c not in have]
        if todo:
            have.update(score_rows(run, run.rubric(v), todo, K_RUNS))
            run.write(f, have)
    return {}


def compute_stats(run: Run, scores: dict[str, dict[str, Any]], review: dict[str, Any], cids: list[str]) -> dict[str, Any]:
    """Consistency (k-run) + quality (Judge) numbers for one version on one set of rows."""
    spec = run.setup.metrics
    rows = row_stats({c: scores[c] for c in cids if c in scores}, run.metrics)
    ms = metric_stats(rows, run.metrics, spec[0].min, spec[0].max)
    dis = disagreement(review.get("rows", []), run.metrics)
    taus = {m: [t for k in review.get("ranks", []) if k["metric"] == m for t in [concordance(k["order"], rows, m)] if t is not None]
            for m in run.metrics}
    return {"rows": rows, "metrics": ms, "disagree": dis, "concordance": {m: round(mean(t), 2) if t else None for m, t in taus.items()},
            "issues": {m: {i: sum(1 for r in review.get("rows", []) if r["metric"] == m and r["issue"] == i)
                           for i in ("unstable", "too_high", "too_low", "reason_unsupported")} for m in run.metrics}}


def stats(state: RunState) -> dict[str, Any]:
    """Node: stats for candidate and best on this round's sample; Judge notes for the candidate go to the scratchpad."""
    run = Run(state["run_dir"])
    rnd, cand = state["round"], state["candidate"]
    out = {v: compute_stats(run, run.json(f"scores/{v}_r{rnd}.json", {}), run.json(f"judge/round_{rnd}_{v}.json", {}), state["sample"])
           for v in (cand, state["best"])}
    run.write(f"judge/round_{rnd}_stats.json", out)
    rv, st = run.json(f"judge/round_{rnd}_{cand}.json", {}), out[cand]
    worst = sorted((r for r in rv.get("rows", []) if not r["agree"]), key=lambda r: r["issue"] != "unstable")[:25]
    lines = [f"## Round {rnd} — Judge", f"{cand}: ICC {st['metrics']['_icc_mean']} | within-std {st['metrics']['_within_mean']} | "
             f"disagree {st['disagree'].get('_overall')}% | issues {st['issues']}", *rv.get("summaries", []), "", "Patterns:"]
    lines += [f"- {p}" for p in rv.get("patterns", [])]
    lines += ["", "Unstable rows (cid: metric values):"]
    lines += [f"- {c}: " + "; ".join(f"{m} {st['rows'][c]['metrics'][m]['values']}" for m in run.metrics if st['rows'][c]['metrics'][m]['std'] and st['rows'][c]['metrics'][m]['std'] > 1.0)
              for c in sorted(st["rows"], key=lambda c: -sum(x["std"] or 0 for x in st["rows"][c]["metrics"].values()))[:10]]
    lines += ["", "Disagreements:"] + [f"- {r['cid']} / {r['metric']} [{r['issue']}]: {r['comment']}" for r in worst]
    run.append("scratchpad.md", "\n".join(lines) + "\n")
    return {}
