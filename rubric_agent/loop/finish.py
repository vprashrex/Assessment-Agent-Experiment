"""After the loop: bake-off on the held-out split picks the final best; HANDOFF.md hands it to the human."""

from __future__ import annotations

from typing import Any

from ..core.runio import Run
from ..core.state import RunState
from .gate import heldout
from .measure import trend_md


def bakeoff(state: RunState) -> dict[str, Any]:
    """v0 + top-3 versions by train ICC, all measured on the held-out rows (k runs + Judge review)."""
    run = Run(state["run_dir"])
    versions = run.json("versions.json", {})
    ranked = sorted((v for v in versions if v != "v0" and "icc" in versions[v]), key=lambda v: -versions[v]["icc"])
    cands = ["v0"] + ranked[:3]
    results = {}
    for v in cands:
        h = heldout(run, v)
        results[v] = {"icc": h["metrics"]["_icc_mean"], "within": h["metrics"]["_within_mean"], "disagree": h["disagree"].get("_overall"),
                      "per_metric": {m: {"icc": h["metrics"][m]["icc"], "within": h["metrics"][m]["within_std"], "disagree": h["disagree"].get(m),
                                         "pileup": h["metrics"][m]["pileup"], "unused": h["metrics"][m]["unused"]} for m in run.metrics},
                      "chars": len(run.rubric(v))}
    winner = max(cands, key=lambda v: (results[v]["icc"], -(results[v]["disagree"] or 0), -results[v]["chars"]))
    run.write("rubric/best.md", run.rubric(winner))
    line = "bakeoff (held-out) | " + " ; ".join(f"{v} ICC {results[v]['icc']:.2f} dis {results[v]['disagree']}" for v in cands) + f" | WINNER {winner}"
    run.append("ledger.md", line)
    run.write("bakeoff.json", {**results, "winner": winner})
    return {"best": winner, "ledger": state["ledger"] + [line]}


def handoff(state: RunState) -> dict[str, Any]:
    """HANDOFF.md: best prompt, why the loop stopped, held-out results, trend, how to send comments back."""
    run = Run(state["run_dir"])
    bake = run.json("bakeoff.json", {})
    rows = [f"- {v}: ICC {r['icc']:.2f}, within-std {r['within']:.2f}, Judge disagree {r['disagree']}%, {r['chars']} chars"
            for v, r in bake.items() if isinstance(r, dict)]
    md = (f"# Handoff — {run.dir.name}\n\n**Best rubric:** `rubric/best.md` (= {state['best']})\n\n**Why the loop stopped:** {state.get('stop_reason', '')}\n\n"
          f"## Held-out results (rows never tuned on)\n" + "\n".join(rows) + f"\n\n## Trend (train samples)\n{trend_md(run.json('trend.json', []), run.metrics)}\n\n"
          f"## Ledger\n```\n{run.text('ledger.md')}```\n\n## Your review\nRead `rubric/best.md`, `HOW_TO_WRITE_AN_UNAMBIGUOUS_RUBRIC.md` and the latest "
          "`judge/round_*_stats.json`. Write your comments (what is misaligned, what to keep) to a file, then continue from this best version:\n\n"
          f"    python -m rubric_agent.cli continue --run {run.dir} --comments comments.md --rounds 5\n")
    run.write("HANDOFF.md", md)
    return {}
