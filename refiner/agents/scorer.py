"""The scorer: the scoring model applies a rubric version to every item, exactly as in production. Its system prompt
is the rubric itself."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .. import prompts
from . import llm
from .layers import files_of, label


def output_schema(out: dict) -> dict:
    field = ({"type": "string", "enum": out["values"]} if out["type"] == "enum"
             else {"type": "integer" if float(out["min"]).is_integer() and float(out["max"]).is_integer() else "number"})
    return {"type": "object", "properties": {out["field"]: field}, "required": [out["field"]]}


def parse_output(raw: dict, out: dict) -> Any:
    """The scorer's value for the output field, validated against setup; None if unusable."""
    v = raw.get(out["field"])
    if out["type"] == "enum":
        return label(v, out["values"])
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if out["min"] <= v <= out["max"] else None


def score(rubric: str, items: list[dict], out: dict, model: str, effort: str, workers: int,
          schema: dict | None = None, raw: dict | None = None) -> dict[str, Any]:
    return score_all(rubric, items, {"_": out}, model, effort, workers, schema, raw)["_"]


def score_all(rubric: str, items: list[dict], outs: dict[str, dict], model: str, effort: str,
              workers: int, schema: dict | None = None, raw: dict | None = None) -> dict[str, dict[str, Any]]:
    """Every output field from one scorer call per item: key -> {item id -> value or None}. With the operator's
    output schema the scorer answers in full, as in production, and only the output fields are read from it;
    `raw` (if given) receives each item's whole answer."""
    if not (schema and all(o["field"] in schema.get("properties", {}) for o in outs.values())):
        schema = {"type": "object", "properties": {o["field"]: output_schema(o)["properties"][o["field"]] for o in outs.values()},
                  "required": [o["field"] for o in outs.values()]}

    def one(it: dict) -> tuple[str, dict]:
        try:
            answer = llm.call(model, rubric, prompts.render("scorer", submission=it["input"]), schema, effort=effort,
                              files=files_of(it))
        except llm.LLMError:
            answer = {}
        return it["id"], answer

    with ThreadPoolExecutor(workers) as ex:
        answers = dict(ex.map(one, items))
    if raw is not None:
        raw.update(answers)
    return {k: {i: parse_output(a, o) for i, a in answers.items()} for k, o in outs.items()}
