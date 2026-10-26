"""The judge: explains each item's miss (ITEM), then summarises the round into issues (SUMMARY), measuring with
math_tool through tool calls. It never sees or changes thresholds."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .. import prompts
from . import llm
from .layers import files_of

ITEM_SCHEMA = {"type": "object", "properties": {
    "observations": {"type": "string"}, "model_reasoning": {"type": "string"},
    "direction": {"type": "string", "enum": ["too_high", "too_low", "aligned"]},
    "clause": {"type": "string"}, "comment": {"type": "string"}},
    "required": ["observations", "model_reasoning", "direction", "clause", "comment"]}

SUMMARY_SCHEMA = {"type": "object", "properties": {
    "overview": {"type": "string"},
    "issues": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "root_cause": {"type": "string"},
        "what_items": {"type": "string"},
        "direction": {"type": "string", "enum": ["too_high", "too_low"]},
        "items": {"type": "array", "items": {"type": "string"}},
        "clause": {"type": "string"},
        "fix": {"type": "string"},
        "status_note": {"type": "string"}},
        "required": ["id", "title", "root_cause", "what_items", "direction", "items", "clause", "fix", "status_note"]}},
    "locked": {"type": "array", "items": {"type": "object", "properties": {
        "layer": {"type": "string"}, "clause": {"type": "string"}, "items": {"type": "array", "items": {"type": "string"}},
        "why": {"type": "string"}}, "required": ["layer", "clause", "items", "why"]}},
    "mode": {"type": "string", "enum": ["edit", "rewrite"]},
    "rewrite_brief": {"type": "string"},
    "summary": {"type": "string"}},
    "required": ["overview", "issues", "locked", "mode", "rewrite_brief", "summary"]}


def _gap(pred: Any, truth: Any, out: dict) -> str:  # display only
    if out["type"] == "enum":
        return "match" if pred == truth else "mismatch"
    return f"{float(pred) - float(truth):+g}"


def review(rubric: str, items: list[dict], preds: dict, truths: dict, out: dict, model: str, effort: str,
           workers: int) -> dict[str, dict]:
    """One judge call per item with an output; returns id -> {observations, model_reasoning, direction, clause, comment}."""
    def one(it: dict) -> tuple[str, dict]:
        p, t = preds.get(it["id"]), truths.get(it["id"])
        user = prompts.render("judge_item", rubric=rubric, submission=it["input"][:30000], output=p, reference=t,
                              error=_gap(p, t, out))
        try:
            return it["id"], llm.call(model, prompts.system("judge"), user, ITEM_SCHEMA, effort=effort, files=files_of(it))
        except llm.LLMError as e:
            return it["id"], {"observations": "", "model_reasoning": "", "direction": "aligned", "clause": "none",
                              "comment": f"(review unavailable: {e})"}

    todo = [it for it in items if preds.get(it["id"]) is not None and truths.get(it["id"]) is not None]
    with ThreadPoolExecutor(workers) as ex:
        return dict(ex.map(one, todo))


def table(reviews: dict[str, dict], errs: dict[str, float], out: dict, after: dict[str, str] | None = None,
          issues_of: dict[str, list[str]] | None = None) -> str:
    """The per-item view the generator gets: no reference values, no model outputs — direction, size, cause, and
    `edit_history`: what every earlier edit did to this item (closer / further + the reviewer's reading of why)."""
    after, issues_of = after or {}, issues_of or {}
    esc = lambda s: '"' + str(s).replace('"', "'").replace("\n", " ") + '"'  # noqa: E731
    rows = ["id,direction,how_far_off,issues,clause,comment,edit_history"]
    for i, r in sorted(reviews.items(), key=lambda kv: -abs(errs.get(kv[0], 0))):
        size = "" if out["type"] == "enum" else f"{abs(errs.get(i, 0)):g}"
        rows.append(f"{i},{r['direction']},{size},{' '.join(issues_of.get(i, []))},{esc(r['clause'][:200])},{esc(r['comment'])},"
                    f"{esc(after.get(i, ''))}")
    return "\n".join(rows)


def checklist_text(issues: dict[str, dict]) -> str:
    """The issue checklist as the judge and the author read it; status and numbers are measured by code."""
    if not issues:
        return "(empty — first round)"
    out = []
    for k, x in issues.items():
        h = x["history"][-1]
        trail = " → ".join(f"r{e['round']} {e['status']}" for e in x["history"])
        out.append(f"[{k}] {x['status'].upper()} · {x['title']} ({x['direction']}, {len(x['items'])} items: {', '.join(x['items'])})\n"
                   f"   root cause: {x['root_cause']}\n   clause: {' '.join(x['clause'].split())[:200]}\n   fix: {x['fix']}\n"
                   f"   measured on {h['version']}: mean error {h['mean_error']:+.2f} vs threshold {h['threshold']:.2f} · history: {trail}")
    return "\n".join(out)


def summarise(rubric: str, version: str, versions: list[str], reviews: dict, errs: dict, out: dict, change: str, dialogue: str,
              checklist: dict[str, dict], tools: llm.Tools, tool_log: list, model: str, effort: str) -> dict:
    notes = [f"[{i}] {r['direction']} ({_size(errs.get(i), out)})\n   observations: {r.get('observations', '')}\n"
             f"   model reasoning: {r.get('model_reasoning', '')}\n   clause: {r['clause'][:200]}\n   comment: {r['comment']}"
             for i, r in sorted(reviews.items())]
    user = prompts.render("judge_summary", version=version, rubric=rubric, versions=versions,
                          checklist=checklist_text(checklist), change=change, notes="\n".join(notes),
                          dialogue=dialogue[-20000:] or "(none)")
    return llm.call(model, prompts.system("judge"), user, SUMMARY_SCHEMA, effort=effort, tools=tools, tool_log=tool_log)


def _size(e: float | None, out: dict) -> str:
    if e is None:
        return "?"
    return ("miss" if e else "match") if out["type"] == "enum" else f"off by {abs(e):g}"
