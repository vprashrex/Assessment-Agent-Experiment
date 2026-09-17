"""Generator revises the best rubric from the consistency graph, unstable rows, scratchpad and ledger."""

from __future__ import annotations

import json
import re
from typing import Any

from ..core import llm
from ..core.config import FOCUS_ROWS, GENERATOR, LEN_BUDGET, PRINCIPLES, prompt
from ..core.runio import Run
from ..core.state import GenOut, RunState
from ..loop.measure import trend_md
from ..loop.steps import best_stats
from ..parser import submission_text


def unescape(text: str) -> str:
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)


def window(scratch: str, rounds: set[int]) -> str:
    parts = re.split(r"(?m)^(?=## Round \d+ — )", scratch)
    keep = [p for p in parts if (m := re.match(r"## Round (\d+)", p)) and int(m.group(1)) in rounds]
    return "\n".join(keep) if keep else "(none yet)"


def stats_md(st: dict[str, Any], metrics: list[str]) -> str:
    ms = st["metrics"]
    lines = [f"stable rows {ms['_stable_pct']}% | avg std {ms['_within']} | severe flips (range>=2) {ms['_severe']} | ICC {ms['_icc']} | scorer failures {ms['_fail_rate']}"]
    for m in metrics:
        x = ms[m]
        lines.append(f"- {m}: stable {x['stable_pct']}%, avg std {x['within_std']}, severe flips {x['severe']} {x['severe_rows'][:10]}, between-std {x['between_std']}, "
                     f"ICC {x['icc']}, unused values {x['unused']}, pile-up {x['pileup']}")
    return "\n".join(lines)


def focus_md(run: Run, st: dict[str, Any]) -> str:
    rows = st["rows"]
    worst = sorted(rows, key=lambda c: -sum(x["std"] or 0 for x in rows[c]["metrics"].values()))[:FOCUS_ROWS]
    out = []
    for c in worst:
        vals = "; ".join(f"{m} {x['values']}" for m, x in rows[c]["metrics"].items() if not x["stable"])
        delta = st.get("deltas", {}).get(c)
        out.append(f"[{c}] unstable: {vals}" + (f" | Δstd vs previous: {delta}" if delta else "") + f"\n{submission_text(run.rows[c])[:600]}")
    return "\n\n".join(out) or "(all rows stable)"


def brief(run: Run, state: RunState, st: dict[str, Any], budget: int) -> str:
    best = state["best"]
    return (f"# SETUP.MD\n{run.text('setup.md')}\n\n# OUTPUT SCHEMA (frozen)\n{json.dumps(run.setup.score_schema)}\n\n"
            f"# CURRENT BEST RUBRIC ({best}, {len(run.rubric(best))} chars; budget {budget})\n<<<\n{run.rubric(best)}\n>>>\n\n"
            f"# CONSISTENCY OF {best}\n{stats_md(st, run.metrics)}\n\n# LEAST STABLE SUBMISSIONS (k scores per unstable metric)\n{focus_md(run, st)}\n\n"
            + GRAPH_NOTE + f"# TREND TABLE\n{trend_md(run.json('trend.json', []), run.metrics)}\n\n"
            f"# SCRATCHPAD (recent)\n{window(run.text('scratchpad.md'), {state['round'], state['round'] - 1, state['best_round']})}\n\n"
            f"# LEDGER\n{run.text('ledger.md')}\n\n# PRINCIPLES FROM EARLIER RUNS\n{PRINCIPLES.read_text() if PRINCIPLES.exists() else '(none)'}\n\n"
            + (f"# HUMAN REVIEW COMMENTS (highest priority)\n{state['comments']}\n\n" if state.get("comments") else "")
            + f"# CONSTRAINTS\n- every metric name must appear: {run.metrics}\n- rubric_md <= {budget} chars\n- the output instruction must match the schema exactly")


def graphs(run: Run) -> list[tuple[str, bytes]]:
    return [("image/png", (run.dir / f).read_bytes()) for f in ("trend_stable.png", "trend_std.png", "trend_flips.png", "trend_icc.png") if (run.dir / f).exists()]


GRAPH_NOTE = ("# GRAPHS (attached images; x = run, first panel = all metrics, then one panel per metric, filled marker = kept run)\n"
              "1. trend_stable.png — % of submissions whose k scores stay within one adjacent value (higher = consistent).\n"
              "2. trend_std.png — avg over submissions of the std of k scores (lower = consistent).\n"
              "3. trend_flips.png — number of submissions whose k scores span 2+ points (lower = consistent).\n"
              "4. trend_icc.png — between-submission variance / total: must stay high; a fall means the rubric stopped separating submissions.\n\n")


def generate(state: RunState) -> dict[str, Any]:
    run = Run(state["run_dir"])
    rnd, best = state["round"] + 1, state["best"]
    budget = int(max(LEN_BUDGET * len(run.rubric("v0")), 12000))
    st = run.json(f"stats/round_{state['round']}.json", {}).get(state.get("candidate")) or best_stats(run, state)
    user = brief(run, state, st, budget)
    images = graphs(run)
    out, _ = llm.call(GENERATOR, prompt("generator"), user, GenOut, role="generator", effort="high", images=images)
    problems = [f"metric name '{m}' missing" for m in run.metrics if m not in out.rubric_md]
    if len(out.rubric_md) > budget:
        problems.append(f"{len(out.rubric_md)} chars > budget {budget}")
    if problems:
        out, _ = llm.call(GENERATOR, prompt("generator"), user + "\n\nREJECTED: " + "; ".join(problems) + ". Fix and return again.",
                          GenOut, role="generator", effort="high", images=images)
    cand = f"v{rnd}"
    run.write(f"rubric/{cand}.md", out.rubric_md)
    run.append("scratchpad.md", unescape(f"## Round {rnd} — Generator\n{cand} from {best}. Change: {out.change_summary}\nHypothesis: {out.hypothesis}\n"))
    versions = run.json("versions.json", {})
    versions[cand] = {"round": rnd, "base": best, "summary": out.change_summary, "kept": False}
    run.write("versions.json", versions)
    return {"round": rnd, "candidate": cand, "mode": "revise"}
