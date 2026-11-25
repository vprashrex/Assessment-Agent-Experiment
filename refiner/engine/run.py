"""Entry point of a refinement: set up, refine (one loop, or the fan-out), write report.json. api.refine calls this."""

from __future__ import annotations

from pathlib import Path

from .. import agents
from ..agents import llm, spend
from . import fanout, report
from .loop import Run, debug, refine, setup_run

HARD_FACTOR = 1.25  # no model call starts once spend passes budget × this


def main(a) -> dict:
    """Returns the best version per metric. The spend ledger lives for the whole process: every sub-run and stage
    adds to <run>/spend.json, and a resume continues from it."""
    run = Run(Path(a.run))
    spend.attach(run.dir)
    spend.start(spend.read(run.dir))
    llm.HARD_CAP["usd"] = a.budget * HARD_FACTOR if a.budget else None
    if spend.total():
        debug(run, f"resume: ${spend.total():.2f} spent so far" + (f" of a ${a.budget:.2f} budget" if a.budget else ""))
    setup, items = setup_run(run, a)
    if len(agents.metrics_of(setup)) > 1:
        return fanout.main(run, a, setup, items)
    layout = run.read("setup/baseline/layout.json")
    ed = ((agents.EDITABLE, agents.PROCEDURE) if any(c["layer"] == agents.PROCEDURE for c in layout)
          else (agents.EDITABLE,))
    best = {agents.metrics_of(setup)[0]["key"]: refine(run, a, setup, items, editable=ed)}
    finish(run)
    report.write(run, a)
    return best


def finish(run: Run) -> None:
    """The run's cost line, once, at the end of every path."""
    s = spend.snapshot()
    by = " · ".join(f"{m} ${v['usd']:.2f} ({v['calls']} calls)" for m, v in s["by_model"].items())
    debug(run, f"=== SPENT ${s['usd']:.2f} · {by}" + (f" · no price in models.yaml for {', '.join(spend.unpriced())}: their cost is not counted"
                                                        if spend.unpriced() else ""))
    print(f"SPENT ${s['usd']:.2f} · {by}", flush=True)
