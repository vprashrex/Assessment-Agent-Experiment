"""Judge duty 2: control the flow. From the trend table and ledger -> continue / success / fail.
The circuit breaker (rounds ceiling, scorer failures) is code in loop/gate.py and pre-empts this call."""

from __future__ import annotations

from typing import Any

from ..core import llm
from ..core.config import MODELS, prompt
from ..core.runio import Run
from ..core.state import Decision, RunState
from ..loop.measure import trend_md


def decide(state: RunState) -> dict[str, Any]:
    if state.get("stop"):
        return {"decision": "circuit-breaker"}
    run = Run(state["run_dir"])
    user = (f"# TREND TABLE\n{trend_md(run.json('trend.json', []), run.metrics)}\n\n# LEDGER\n{run.text('ledger.md')}\n\n"
            f"# CURRENT BEST: {state['best']} (kept in round {state['best_round']}); consecutive not-kept: {state.get('consecutive_fail', 0)}; "
            f"round {state['round']} of ceiling {state['max_rounds']}\n# RUBRIC AUTHOR SAYS CONVERGED: {state.get('converged', False)}")
    try:
        d, _ = llm.call(MODELS["judge"], prompt("judge_decide"), user, Decision, role="judge_decide", effort="high", fallback=MODELS["judge_fallback"])
    except llm.LLMError as e:
        run.append("ledger.md", f"JUDGE: could not decide ({str(e)[:120]}) -> continue")
        return {"decision": "continue"}
    run.append("ledger.md", f"JUDGE: {d.decision.upper()} — {d.reason}")
    run.append("scratchpad.md", f"## Round {state['round']} — Judge decision\n{d.decision}: {d.reason}\n")
    stop = d.decision != "continue"
    if stop:
        run.append("ledger.md", f"STOP: judge {d.decision}")
    return {"decision": d.decision, "stop": stop, "stop_reason": f"judge {d.decision}: {d.reason}" if stop else ""}
