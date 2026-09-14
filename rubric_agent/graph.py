"""The LangGraph: parse → (ask_operator) → review_setup → baseline → [generate → sample → score → review →
stats → gate → decide]* → bakeoff → reflect → handoff. Keep/revert and the rounds ceiling are code
(loop/gate); continue/success/fail is the Judge (judge/decide). `continue` re-enters at generate."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from .core.state import RunState
from .generator.generate import generate
from .generator.reflect import reflect
from .judge.decide import decide
from .judge.review import review
from .loop.finish import bakeoff, handoff
from .loop.gate import gate
from .loop.lifecycle import ask_operator, baseline, parse, review_setup
from .loop.steps import sample, score, stats

LOOP = [generate, sample, score, review, stats, gate, decide]


def build(checkpoint: Path):
    g = StateGraph(RunState)
    for fn in [parse, ask_operator, review_setup, baseline, *LOOP, bakeoff, reflect, handoff]:
        g.add_node(fn.__name__, fn)

    g.add_edge(START, "parse")
    g.add_conditional_edges("parse", lambda s: "ask_operator" if s.get("needs_input") else "generate" if s.get("resume_loop") else "review_setup")
    g.add_edge("ask_operator", "parse")
    g.add_edge("review_setup", "baseline")
    g.add_conditional_edges("baseline", lambda s: END if s.get("stop") else "generate")
    for a, b in zip(LOOP, LOOP[1:]):
        g.add_edge(a.__name__, b.__name__)
    g.add_conditional_edges("decide", lambda s: "bakeoff" if s.get("stop") else "generate")
    g.add_edge("bakeoff", "reflect")
    g.add_edge("reflect", "handoff")
    g.add_edge("handoff", END)

    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    return g.compile(checkpointer=SqliteSaver(sqlite3.connect(checkpoint, check_same_thread=False)))
