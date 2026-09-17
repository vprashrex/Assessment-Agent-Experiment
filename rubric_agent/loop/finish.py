from __future__ import annotations

from typing import Any

from ..core.runio import Run
from ..core.state import RunState
from .measure import trend_md


def handoff(state: RunState) -> dict[str, Any]:
    run = Run(state["run_dir"])
    best = state["best"]
    run.write("rubric/best.md", run.rubric(best))
    v = run.json("versions.json", {}).get(best, {})
    md = (f"# Handoff — {run.dir.name}\n\n**Best rubric:** `rubric/best.md` (= {best})  \n**Output schema:** `score_schema.json`  \n"
          f"**Why the loop stopped:** {state.get('stop_reason', '')}\n\n"
          f"**Best on the dataset:** stable {v.get('stable_pct')}%, avg std {v.get('within')}, ICC {v.get('icc')}\n\n"
          f"## Trend\n![stable](trend_stable.png)\n![std](trend_std.png)\n![flips](trend_flips.png)\n![icc](trend_icc.png)\n![var](trend_var.png)\n\n{trend_md(run.json('trend.json', []), run.metrics)}\n\n"
          f"## Per-submission consistency (operator view)\n![rows](rows.png)\n\n## Ledger\n```\n{run.text('ledger.md')}```\n\n"
          "## Your review\nRead `rubric/best.md` and `HOW_TO_WRITE_AN_UNAMBIGUOUS_RUBRIC.md`. Write your comments to a file, then continue "
          f"from this best version:\n\n    python -m rubric_agent.cli continue --run {run.dir} --comments comments.md --rounds 5\n")
    run.write("HANDOFF.md", md)
    return {}
