"""Entry point of a refinement: set up, refine (one loop, or the fan-out), write report.json. api.refine calls this."""

from __future__ import annotations

from pathlib import Path

from .. import agents
from . import fanout, report
from .loop import Run, refine, setup_run


def main(a) -> dict:
    """Returns the best version per metric."""
    run = Run(Path(a.run))
    setup, items = setup_run(run, a)
    if len(agents.metrics_of(setup)) > 1:
        return fanout.main(run, a, setup, items)
    layout = run.read("setup/baseline/layout.json")
    ed = ((agents.EDITABLE, agents.PROCEDURE) if any(c["layer"] == agents.PROCEDURE for c in layout)
          else (agents.EDITABLE,))
    best = {agents.metrics_of(setup)[0]["key"]: refine(run, a, setup, items, editable=ed)}
    report.write(run, a)
    return best
