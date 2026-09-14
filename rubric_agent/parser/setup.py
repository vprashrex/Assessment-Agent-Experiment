"""Parser duty 2: write setup.md (what judge + generator read) and locate the score fields in the schema."""

from __future__ import annotations

import json
from typing import Any

from ..core import llm
from ..core.config import prompt
from ..core.state import Constitution, MetricSpec


def schema_paths(schema: dict[str, Any], prefix: str = "") -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for k, v in schema.get("properties", {}).items():
        out[prefix + k] = v
        if isinstance(v, dict) and v.get("type") == "object":
            out.update(schema_paths(v, prefix + k + "."))
    return out


def write_setup(prompt_md: str, schema: dict[str, Any], context: str, model: str) -> Constitution:
    user = (f"OPERATOR CONTEXT:\n{context}\n\nOUTPUT SCHEMA THE SCORER MUST RETURN:\n{json.dumps(schema, indent=1)}\n\n"
            f"EXISTING RUBRIC PROMPT (v0):\n<<<\n{prompt_md}\n>>>")
    con, _ = llm.call(model, prompt("parser_constitution"), user, Constitution, role="parser", effort="high")
    paths = schema_paths(schema)
    numeric = lambda p: p in paths and paths[p].get("type") in ("number", "integer")  # noqa: E731
    con.metrics = [m for m in con.metrics if numeric(m.score_path)]
    for m in con.metrics:
        if m.reason_path is not None and m.reason_path not in paths:
            m.reason_path = None
    if not con.metrics:  # fallback: any numeric field named <X>_score
        for p, v in paths.items():
            if p.endswith("_score") and numeric(p):
                n = p[: -len("_score")]
                con.metrics.append(MetricSpec(name=n, score_path=p, reason_path=f"{n}_reason" if f"{n}_reason" in paths else None,
                                              min=int(v.get("minimum", 1)), max=int(v.get("maximum", 10))))
    return con
