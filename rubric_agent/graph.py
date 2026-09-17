"""parse → design → baseline → [generate → score → measure → gate → assess]* → reflect → handoff.
assess routes: revise → generate; assure → score (best again); stop after a passed assurance."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from .core.state import RunState
from .generator.assess import assess
from .generator.design import design
from .generator.generate import generate
from .generator.reflect import reflect
from .loop.finish import handoff
from .loop.gate import gate
from .loop.lifecycle import ask_operator, baseline, parse, review_setup
from .loop.steps import measure, score


def build(checkpoint: Path):
    g = StateGraph(RunState)
    for fn in [parse, ask_operator, review_setup, design, baseline, generate, score, measure, gate, assess, reflect, handoff]:
        g.add_node(fn.__name__, fn)

    g.add_edge(START, "parse")
    g.add_conditional_edges("parse", lambda s: "ask_operator" if s.get("needs_input") else "generate" if s.get("resume_loop") else "review_setup")
    g.add_edge("ask_operator", "parse")
    g.add_edge("review_setup", "design")
    g.add_edge("design", "baseline")
    g.add_conditional_edges("baseline", lambda s: END if s.get("stop") else "generate")
    g.add_edge("generate", "score")
    g.add_edge("score", "measure")
    g.add_edge("measure", "gate")
    g.add_edge("gate", "assess")
    g.add_conditional_edges("assess", lambda s: "reflect" if s.get("stop") else "score" if s.get("mode") == "assure" else "generate")
    g.add_edge("reflect", "handoff")
    g.add_edge("handoff", END)

    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    return g.compile(checkpointer=SqliteSaver(sqlite3.connect(checkpoint, check_same_thread=False)))
