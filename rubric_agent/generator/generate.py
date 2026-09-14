"""Generator: writes the next rubric version from setup.md, the best rubric, consistency stats (k-run ICC /
within-std / unstable rows), the Judge's quality notes, the trend, the ledger and long-term principles."""

from __future__ import annotations

import json
import random
import re
from typing import Any

from ..core import llm
from ..core.config import LEN_BUDGET, MODELS, N_MAX, POOL_SHOW, PRINCIPLES, prompt
from ..core.runio import Run
from ..core.state import GenOut, RunState
from ..loop.measure import trend_md
from ..parser import submission_text


def _window(scratch: str, rounds: set[int]) -> str:
    parts = re.split(r"(?m)^(?=## Round \d+ — )", scratch)
    keep = [p for p in parts if (m := re.match(r"## Round (\d+)", p)) and int(m.group(1)) in rounds]
    return "\n".join(keep) if keep else "(none yet)"


def _stats_md(st: dict[str, Any], metrics: list[str]) -> str:
    if not st:
        return "(none)"
    ms, dis, conc, iss = st["metrics"], st["disagree"], st.get("concordance", {}), st.get("issues", {})
    lines = [f"mean ICC {ms['_icc_mean']} | mean within-std {ms['_within_mean']} | judge disagree {dis.get('_overall')}% | scorer failures {ms['_fail_rate']}"]
    for m in metrics:
        x = ms[m]
        lines.append(f"- {m}: ICC {x['icc']}, within-std {x['within_std']}, between-std {x['between_std']}, disagree {dis.get(m)}%, "
                     f"rank concordance {conc.get(m)}, issues {iss.get(m)}, unused values {x['unused']}, pile-up {x['pileup']}, "
                     f"unstable rows {x['unstable'][:8]}")
    return "\n".join(lines)


def _brief(run: Run, state: RunState, best: str, rnd: int, budget: int) -> str:
    best_md = run.rubric(best)
    last = run.json(f"judge/round_{state['round']}_stats.json", {})
    st = last.get(state.get("candidate") if state["round"] else "v0") or last.get(best) or {}
    pool = sorted(run.pool() & set(run.rows))
    pool_rows = [run.rows[c] for c in random.Random(f"pool{rnd}").sample(pool, k=min(POOL_SHOW, len(pool)))]
    return (
        f"# SETUP.MD\n{run.text('setup.md')}\n\n# CURRENT BEST RUBRIC ({best}, {len(best_md)} chars; budget {budget} chars)\n<<<\n{best_md}\n>>>\n\n"
        f"# CONSISTENCY + QUALITY STATS FOR THE LAST EVALUATED VERSION\n{_stats_md(st, run.metrics)}\n\n"
        f"# TREND (all rounds)\n{trend_md(run.json('trend.json', []), run.metrics)}\n\n"
        f"# JUDGE NOTES (scratchpad window)\n{_window(run.text('scratchpad.md'), {state['round'], state['round'] - 1, state['best_round']})}\n\n"
        f"# LEDGER\n{run.text('ledger.md')}\n\n# PRINCIPLES FROM EARLIER RUNS\n{PRINCIPLES.read_text() if PRINCIPLES.exists() else '(none)'}\n\n"
        + (f"# HUMAN REVIEW COMMENTS (highest priority)\n{state['comments']}\n\n" if state.get("comments") else "")
        + "# EXAMPLE POOL (the only rows you may use as worked examples)\n"
        + "\n\n".join(f"[{r['cid']}]\n{submission_text(r)[:700]}" for r in pool_rows)
        + f"\n\n# CONSTRAINTS\n- Every metric name must appear: {run.metrics}\n- rubric_md <= {budget} chars\n- n_random in [20,{N_MAX}]"
    )


def generate(state: RunState) -> dict[str, Any]:
    run = Run(state["run_dir"])
    rnd, best = state["round"] + 1, state["best"]
    budget = int(LEN_BUDGET * max(len(run.rubric("v0")), 8000))
    user = _brief(run, state, best, rnd, budget)
    out, _ = llm.call(MODELS["generator"], prompt("generator"), user, GenOut, role="generator", effort="high")
    problems = [f"metric name '{m}' missing" for m in run.metrics if m not in out.rubric_md]
    if len(out.rubric_md) > budget:
        problems.append(f"rubric is {len(out.rubric_md)} chars, budget {budget}")
    if problems:
        out, _ = llm.call(MODELS["generator"], prompt("generator"), user + "\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED: "
                          + "; ".join(problems) + ". Fix and return again.", GenOut, role="generator", effort="high")
    cand = f"v{rnd}"
    run.write(f"rubric/{cand}.md", out.rubric_md)
    run.append("scratchpad.md", f"## Round {rnd} — Generator\n{cand} from {best}. Change: {out.change_summary}\nHypothesis: {out.hypothesis}\n"
               + (f"Generator declares converged: {out.converged_reason}\n" if out.converged else ""))
    versions = run.json("versions.json", {})
    versions[cand] = {"round": rnd, "base": best, "summary": out.change_summary, "kept": False}
    run.write("versions.json", versions)
    return {"round": rnd, "candidate": cand, "n_random": max(20, min(N_MAX, out.n_random)), "converged": out.converged}
