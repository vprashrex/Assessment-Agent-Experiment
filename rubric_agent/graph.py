"""The LangGraph: parse → (ask_operator) → review_setup → baseline → [generate → sample → score →
band → verdict → comment → gate]* → bakeoff → reflect. Gate and routing are plain code."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from . import nodes
from .state import RunState

LOOP = ["generate", "sample", "score", "band", "verdict", "comment", "gate"]


def build(checkpoint: Path):
    g = StateGraph(RunState)
    for name in ["parse", "ask_operator", "review_setup", "baseline", *LOOP, "bakeoff", "reflect"]:
        g.add_node(name, getattr(nodes, name))

    g.add_edge(START, "parse")
    g.add_conditional_edges("parse", lambda s: "ask_operator" if s.get("needs_input") else "review_setup")
    g.add_edge("ask_operator", "parse")
    g.add_edge("review_setup", "baseline")
    g.add_conditional_edges("baseline", lambda s: END if s.get("stop") else "generate")
    for a, b in zip(LOOP, LOOP[1:]):
        g.add_edge(a, b)
    g.add_conditional_edges("gate", lambda s: "score" if s.get("retest") else "bakeoff" if s.get("stop") else "generate")
    g.add_edge("bakeoff", "reflect")
    g.add_edge("reflect", END)

    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    return g.compile(checkpointer=SqliteSaver(sqlite3.connect(checkpoint, check_same_thread=False)))
