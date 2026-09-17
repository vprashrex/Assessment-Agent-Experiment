"""Generator reads the graph and decides: revise, assure (repeat the best rubric), or stop (only after assurance)."""

from __future__ import annotations

from typing import Any

from ..core import llm
from ..core.config import GENERATOR, prompt
from ..core.runio import Run
from ..core.state import Assessment, RunState
from ..loop.measure import trend_md
from ..loop.steps import best_stats
from .generate import GRAPH_NOTE, graphs, stats_md, unescape, window


def assess(state: RunState) -> dict[str, Any]:
    if state.get("stop"):
        return {}
    run = Run(state["run_dir"])
    rnd = state["round"]
    st = best_stats(run, state)
    user = (GRAPH_NOTE + f"# TREND TABLE\n{trend_md(run.json('trend.json', []), run.metrics)}\n\n# CURRENT BEST: {state['best']} (measured round {state['best_round']})\n"
            f"{stats_md(st, run.metrics)}\n\n# SCRATCHPAD (recent)\n{window(run.text('scratchpad.md'), {rnd, rnd - 1, state['best_round']})}\n\n"
            f"# LEDGER\n{run.text('ledger.md')}\n\n# STATE\nround {rnd} of ceiling {state['max_rounds']}; consecutive not-kept {state.get('consecutive_fail', 0)}; "
            f"last mode {state['mode']}; assurance {'passed' if state.get('stop') else 'not yet passed'}")
    images = graphs(run)
    try:
        a, _ = llm.call(GENERATOR, prompt("generator_assess"), user, Assessment, role="assess", effort="high", images=images)
    except llm.LLMError as e:
        run.append("ledger.md", f"ASSESS: unavailable ({str(e)[:100]}) -> revise")
        return {"mode": "revise"}
    action = a.next_action
    if action == "stop":
        action = "assure"
    if state["mode"] == "assure":
        action = "revise"
    notes = unescape(a.notes)
    run.append("ledger.md", f"ASSESS: {a.next_action.upper()} -> {action} — {notes}")
    run.append("scratchpad.md", unescape(f"## Round {rnd} — Assessment\nconsistent={a.consistent}; next={action}. {notes}\nFocus rows: {a.focus_rows}\n"))
    if action == "assure":
        return {"mode": "assure", "candidate": state["best"], "round": rnd + 1}
    return {"mode": "revise"}
