"""Generator's long-term memory + the run's written deliverable: HOW_TO_WRITE_AN_UNAMBIGUOUS_RUBRIC.md for the
run, and <= 3 tagged principles appended to memory/principles.md for the next run."""

from __future__ import annotations

from typing import Any

from ..core import llm
from ..core.config import MODELS, PRINCIPLES, prompt
from ..core.runio import Run
from ..core.state import Reflection, RunState


def reflect(state: RunState) -> dict[str, Any]:
    run = Run(state["run_dir"])
    user = f"SCRATCHPAD:\n{run.text('scratchpad.md')[-40000:]}\n\nLEDGER:\n{run.text('ledger.md')}"
    try:
        out, _ = llm.call(MODELS["generator"], prompt("reflect"), user, Reflection, role="reflect", effort="high")
    except llm.LLMError as e:
        run.write("HOW_TO_WRITE_AN_UNAMBIGUOUS_RUBRIC.md", f"(reflection unavailable: {str(e)[:200]})\n")
        return {}
    run.write("HOW_TO_WRITE_AN_UNAMBIGUOUS_RUBRIC.md", out.guide_md.rstrip() + "\n")
    if out.principles:
        PRINCIPLES.parent.mkdir(exist_ok=True)
        tag = f"[run={run.dir.name} judge={MODELS['judge']} setup={abs(hash(run.text('setup.md'))) % 10**8:08d}]"
        with PRINCIPLES.open("a") as f:
            f.writelines(f"- {p.strip()} {tag}\n" for p in out.principles[:3])
        lines = PRINCIPLES.read_text().splitlines()
        if len(lines) > 40:
            PRINCIPLES.write_text("\n".join(lines[-40:]) + "\n")
    return {}
