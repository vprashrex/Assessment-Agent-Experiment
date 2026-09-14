"""Judge duty 1: quality assurance. Batches of submissions with their k-run scores -> agree/disagree per
metric with an issue and a comment, plus a per-metric ranking of the batch. Never sees the rubric."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..core import llm
from ..core.config import BATCH, MODELS, WORKERS, prompt
from ..core.runio import Run
from ..core.state import Review, RunState
from ..loop.measure import row_stats
from ..parser import submission_text

ISSUES = {"none", "unstable", "too_high", "too_low", "reason_unsupported"}


def _item(run: Run, cid: str, rec: dict[str, Any], stats: dict[str, Any]) -> dict[str, Any]:
    runs = [r for r in rec["runs"] if r.get("scores")]
    per = {}
    for m, st in stats["metrics"].items():
        lo = min(runs, key=lambda r: r["scores"][m], default=None)
        hi = max(runs, key=lambda r: r["scores"][m], default=None)
        per[m] = {"scores": st["values"], "mean": st["mean"], "std": st["std"],
                  "reason_low": lo["reasons"].get(m, "") if lo else "", "reason_high": hi["reasons"].get(m, "") if hi else ""}
    return {"cid": cid, "failed_runs": stats["n_fail"], "submission": submission_text(run.rows[cid])[:6000], "metrics": per}


def review_rows(run: Run, scores: dict[str, dict[str, Any]], cids: list[str]) -> dict[str, Any]:
    """Review `cids` in batches; returns {"rows": [...], "ranks": [...], "patterns": [...], "summaries": [...]}."""
    stats = row_stats({c: scores[c] for c in cids}, run.metrics)
    system = prompt("judge_review") + "\n\n# SETUP\n" + run.text("setup.md")
    names = ", ".join(run.metrics)
    batches = [cids[i:i + BATCH] for i in range(0, len(cids), BATCH)]

    def one(batch: list[str]) -> dict[str, Any]:
        user = (f"Metrics (exact names): {names}.\n\nBATCH ({len(batch)} submissions, each scored k times):\n"
                + json.dumps([_item(run, c, scores[c], stats[c]) for c in batch], ensure_ascii=False))
        try:
            out, _ = llm.call(MODELS["judge"], system, user, Review, role="judge_review", effort="high",
                              fallback=MODELS["judge_fallback"], max_tokens=24000)
        except llm.LLMError as e:
            return {"rows": [], "ranks": [], "patterns": [], "summaries": [f"[batch unavailable: {str(e)[:120]}]"]}
        known = set(batch)
        rows = [r.model_dump() for r in out.rows if r.cid in known and r.metric in run.metrics]
        for r in rows:
            r["issue"] = r["issue"] if r["issue"] in ISSUES else "none"
        ranks = [{"metric": k.metric, "order": [c for c in k.order if c in known]} for k in out.ranks if k.metric in run.metrics]
        return {"rows": rows, "ranks": ranks, "patterns": out.patterns, "summaries": [out.summary] if out.summary else []}

    with ThreadPoolExecutor(WORKERS) as ex:
        parts = list(ex.map(one, batches))
    merged: dict[str, Any] = {"rows": [], "ranks": [], "patterns": [], "summaries": []}
    for p in parts:
        for k in merged:
            merged[k].extend(p[k])
    return merged


def review(state: RunState) -> dict[str, Any]:
    """Node: review candidate and best on this round's sample (paired), write judge/round_K_<version>.json."""
    run = Run(state["run_dir"])
    rnd = state["round"]
    for v in (state["candidate"], state["best"]):
        f = f"judge/round_{rnd}_{v}.json"
        if not (run.dir / f).exists():
            run.write(f, review_rows(run, run.json(f"scores/{v}_r{rnd}.json", {}), state["sample"]))
    return {}
