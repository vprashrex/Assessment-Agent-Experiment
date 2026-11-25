"""The parser: reads the sheet and the rubric once per run and decides the columns, the metrics, the layers and any
questions for the operator. Code then checks every answer against the sheet and the rubric."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from .. import prompts
from . import llm
from .layers import EDITABLE, LAYERS, layout, numbered

SETUP_SCHEMA = {
    "type": "object",
    "properties": {
        "id_column": {"type": ["string", "null"]},
        "input_columns": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "type": {"type": "string", "enum": ["text", "document", "attachment"]}}, "required": ["name", "type"]}},
        "metrics": {"type": "array", "items": {"type": "object", "properties": {
            "key": {"type": "string"},
            "truth_column": {"type": "string"},
            "verdict_column": {"type": ["string", "null"]},
            "remarks_column": {"type": ["string", "null"]},
            "rationale_column": {"type": ["string", "null"]},
            "output": {"type": "object", "properties": {
                "field": {"type": "string"}, "type": {"type": "string", "enum": ["number", "enum"]},
                "min": {"type": ["number", "null"]}, "max": {"type": ["number", "null"]},
                "values": {"type": ["array", "null"], "items": {"type": "string"}}}, "required": ["field", "type"]}},
            "required": ["key", "truth_column", "output"]}},
        "layers": {"type": "array", "items": {"type": "object", "properties": {
            "layer": {"type": "string", "enum": LAYERS}, "metric": {"type": ["string", "null"]},
            "from_line": {"type": "integer"}, "to_line": {"type": "integer"}},
            "required": ["layer", "metric", "from_line", "to_line"]}},
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["id_column", "input_columns", "metrics", "layers", "questions"],
}


def profile(df: pd.DataFrame) -> list[dict[str, Any]]:
    out = []
    for c in df.columns:
        v = df[c].dropna()
        num = pd.to_numeric(v, errors="coerce").dropna()
        out.append({"column": c, "filled": f"{len(v)}/{len(df)}", "distinct": int(v.nunique()),
                    "numeric_range": [float(num.min()), float(num.max())] if len(num) >= 0.8 * max(len(v), 1) and len(num) else None,
                    "samples": [str(x)[:120] for x in v.head(4)]})
    return out


def parse(df: pd.DataFrame, context: str, rubric: str, schema: dict | None, model: str, effort: str) -> dict:
    user = prompts.render("parser", context=context.strip() or prompts.USER["parser_no_notes"], rubric=numbered(rubric),
                          schema=json.dumps(schema) if schema else "(none)",
                          columns=json.dumps(profile(df), ensure_ascii=False, indent=1))
    setup = llm.call(model, prompts.system("parser"), user, SETUP_SCHEMA, effort=effort, role="parser")
    ms, q = setup["metrics"], setup["questions"]
    keys = [m["key"] for m in ms]
    if not ms or len(set(keys)) != len(keys):
        q.append(f"Metric keys must be present and distinct; got {keys}.")
    for sp in setup["layers"]:  # one metric: its chunks need no tag
        if sp["layer"] == EDITABLE and not sp.get("metric") and len(ms) == 1:
            sp["metric"] = keys[0]
    cols = set(df.columns)
    bad = [c["name"] for c in setup["input_columns"] if c["name"] not in cols] + [m["truth_column"] for m in ms if m["truth_column"] not in cols]
    bad += [m[k] for m in ms for k in ("verdict_column", "remarks_column", "rationale_column") if m.get(k) and m[k] not in cols]
    # feedback mode: the operator reviewed an assessment's own scores (agree / too high / too low) instead of scoring
    setup["feedback"] = all(m.get("verdict_column") for m in ms)
    if any(m.get("verdict_column") for m in ms) and not setup["feedback"]:
        q.append("Some metrics have a verdict column and some do not; feedback mode needs one per metric.")
    if bad:
        q.append(f"Columns {bad} do not exist; the sheet has {sorted(cols)}.")
    chunks, problems = layout(rubric, setup["layers"])
    q += problems
    tagged = {c.get("metric") for c in chunks if c["layer"] == EDITABLE}
    q += [f"No metrics lines were assigned to metric {k!r}." for k in keys if k not in tagged]
    q += [f"Metrics lines are tagged {k!r}, which is not one of the metrics {keys}." for k in tagged - set(keys)]
    editable = "".join(c["text"] for c in chunks if c["layer"] == EDITABLE)
    locked = "".join(c["text"] for c in chunks if c["layer"] != EDITABLE)
    if not problems and any(m["output"]["field"] in editable and m["output"]["field"] not in locked for m in ms):
        q.append("The output instruction seems to sit inside the metrics layer; which lines are the output format?")
    if len(ms) == 1:  # a single metric keeps the flat setup every single-metric run reads
        setup.update(truth_column=ms[0]["truth_column"], output=ms[0]["output"])
    return setup
