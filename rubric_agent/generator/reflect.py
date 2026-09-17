from __future__ import annotations

from typing import Any

from ..core import llm
from ..core.config import GENERATOR, PRINCIPLES, SCORER, prompt
from ..core.runio import Run
from ..core.state import Reflection, RunState
from .generate import unescape


def reflect(state: RunState) -> dict[str, Any]:
    run = Run(state["run_dir"])
    user = f"SCRATCHPAD:\n{run.text('scratchpad.md')[-40000:]}\n\nLEDGER:\n{run.text('ledger.md')}"
    try:
        out, _ = llm.call(GENERATOR, prompt("reflect"), user, Reflection, role="reflect", effort="high")
    except llm.LLMError as e:
        run.write("HOW_TO_WRITE_AN_UNAMBIGUOUS_RUBRIC.md", f"(reflection unavailable: {str(e)[:200]})\n")
        return {}
    run.write("HOW_TO_WRITE_AN_UNAMBIGUOUS_RUBRIC.md", unescape(out.guide_md).rstrip() + "\n")
    if out.principles:
        PRINCIPLES.parent.mkdir(exist_ok=True)
        tag = f"[run={run.dir.name} scorer={SCORER}]"
        with PRINCIPLES.open("a") as f:
            f.writelines(f"- {unescape(p).strip()} {tag}\n" for p in out.principles[:3])
        lines = PRINCIPLES.read_text().splitlines()
        if len(lines) > 40:
            PRINCIPLES.write_text("\n".join(lines[-40:]) + "\n")
    return {}
