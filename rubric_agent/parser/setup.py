"""Parser: setup.md for the agents, and the output schema (given by the operator or proposed from context)."""

from __future__ import annotations

import json
from typing import Any

from ..core import llm
from ..core.config import PARSER, prompt
from ..core.state import Constitution, MetricSpec, SchemaProposal


def schema_paths(schema: dict[str, Any], prefix: str = "") -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for k, v in schema.get("properties", {}).items():
        out[prefix + k] = v
        if isinstance(v, dict) and v.get("type") == "object":
            out.update(schema_paths(v, prefix + k + "."))
    return out


def metrics_from(schema: dict[str, Any]) -> list[MetricSpec]:
    paths = schema_paths(schema)
    out = []
    for p, v in paths.items():
        if v.get("type") not in ("number", "integer"):
            continue
        name = p[: -len("_score")] if p.endswith("_score") else p.rsplit(".", 1)[0] if "." in p else p
        reason = next((r for r in (f"{name}_reason", f"{name}.reason") if r in paths), None)
        out.append(MetricSpec(name=name, score_path=p, reason_path=reason, min=int(v.get("minimum", 1)), max=int(v.get("maximum", 10))))
    return out


def propose_schema(context: str, prompt_md: str | None) -> tuple[dict[str, Any] | None, list[str]]:
    user = f"OPERATOR CONTEXT:\n{context}\n\nEXISTING RUBRIC (may be empty):\n<<<\n{prompt_md or ''}\n>>>"
    out, _ = llm.call(PARSER, prompt("parser_schema"), user, SchemaProposal, role="parser", effort="medium")
    if out.questions:
        return None, out.questions
    try:
        schema = json.loads(out.schema_text)
    except json.JSONDecodeError as e:
        return None, [f"Proposed schema was not valid JSON ({e}). Please provide the output schema."]
    if not metrics_from(schema):
        return None, ["Could not identify numeric score fields. Which metrics are scored, on what scale?"]
    return schema, []


def write_setup(context: str, prompt_md: str | None, schema: dict[str, Any]) -> str:
    user = (f"OPERATOR CONTEXT:\n{context}\n\nOUTPUT SCHEMA THE SCORER MUST RETURN:\n{json.dumps(schema, indent=1)}\n\n"
            f"EXISTING RUBRIC PROMPT (may be empty):\n<<<\n{prompt_md or ''}\n>>>")
    con, _ = llm.call(PARSER, prompt("parser_constitution"), user, Constitution, role="parser", effort="high")
    return con.setup_md
