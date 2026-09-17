"""Generator drafts v0 from setup.md and the frozen schema, unless the operator supplied one."""

from __future__ import annotations

import json
from typing import Any

from ..core import llm
from ..core.config import GENERATOR, prompt
from ..core.runio import Run
from ..core.state import Design, RunState


def design(state: RunState) -> dict[str, Any]:
    run = Run(state["run_dir"])
    if (run.dir / "rubric/v0.md").exists():
        return {}
    user = (f"# SETUP.MD\n{run.text('setup.md')}\n\n# OUTPUT SCHEMA (frozen; the rubric must instruct the scorer to return exactly this)\n"
            f"{json.dumps(run.setup.score_schema, indent=1)}\n\n# METRICS\n{[m.name for m in run.setup.metrics]} on {run.scale[0]}–{run.scale[1]}")
    out, _ = llm.call(GENERATOR, prompt("generator_design"), user, Design, role="design", effort="high")
    run.write("rubric/v0.md", out.rubric_md)
    run.append("scratchpad.md", f"## Round 0 — Design\nv0 drafted by the Generator. {out.notes}\n")
    return {}
