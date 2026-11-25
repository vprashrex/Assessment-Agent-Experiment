"""The judge: explains each item's miss (ITEM), then diagnoses the round into issues (SUMMARY). It writes no
numbers of its own: code hands it the measured numbers and afterwards measures every issue it names
(engine/loop.update_checklist). One call per item, one call per round, no tool loop."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .. import prompts
from . import llm
from .layers import files_of

ITEM_SCHEMA = {"type": "object", "properties": {
    "direction": {"type": "string", "enum": ["too_high", "too_low", "aligned"]},
    "clause": {"type": "string"}, "comment": {"type": "string"}},
    "required": ["direction", "clause", "comment"]}

SUMMARY_SCHEMA = {"type": "object", "properties": {
    "overview": {"type": "string"},
    "issues": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "root_cause": {"type": "string"},
        "direction": {"type": "string", "enum": ["too_high", "too_low"]},
        "items": {"type": "array", "items": {"type": "string"}},
        "clause": {"type": "string"},
        "fix": {"type": "string"}},
        "required": ["id", "title", "root_cause", "direction", "items", "clause", "fix"]}},
    "summary": {"type": "string"}},
    "required": ["overview", "issues", "summary"]}

# what the loop and the generator still read from a round but the judge no longer decides: the loop always
# edits (a rewrite never fired in 367 measured rounds) and locked-layer causes show up as `clause: none`
ROUND_DEFAULTS = {"mode": "edit", "rewrite_brief": "", "locked": []}


def _gap(pred: Any, truth: Any, out: dict) -> str:  # display only
    if isinstance(truth, dict):  # feedback mode: a verdict constraint, not a score
        old, v = truth.get("old"), truth.get("verdict")
        ok = (v == "agree" and float(pred) == float(old)) or (v == "too_high" and float(pred) < float(old)) \
             or (v == "too_low" and float(pred) > float(old))
        return "verdict satisfied" if ok else "verdict not satisfied"
    if out["type"] == "enum":
        return "match" if pred == truth else "mismatch"
    return f"{float(pred) - float(truth):+g}"


def _ref_text(truth: Any) -> Any:  # display only
    if isinstance(truth, dict):
        v = {"agree": "the score was right", "too_high": "the score was too high",
             "too_low": "the score was too low"}.get(truth.get("verdict"), truth.get("verdict"))
        return prompts.render("judge_verdict_reference", old=f"{truth.get('old'):g}", verdict=v,
                              remark=prompts.render("judge_verdict_remark", remark=truth["remark"]) if truth.get("remark") else "")
    return truth


def review(rubric: str, items: list[dict], preds: dict, truths: dict, out: dict, model: str, effort: str,
           workers: int) -> dict[str, dict]:
    """One judge call per item with an output; returns id -> {direction, clause, comment}."""
    def one(it: dict) -> tuple[str, dict]:
        p, t = preds.get(it["id"]), truths.get(it["id"])
        user = prompts.render("judge_item", rubric=rubric, submission=it["input"][:30000], output=p,
                              reference=_ref_text(t), error=_gap(p, t, out),
                              rationale=it.get("rationale") or prompts.USER["judge_no_rationale"])
        try:
            return it["id"], llm.call(model, prompts.system("judge"), user, ITEM_SCHEMA, effort=effort, files=files_of(it),
                                      role="judge")
        except llm.LLMError as e:
            return it["id"], {"direction": "aligned", "clause": "none", "comment": prompts.render("judge_review_unavailable", error=e)}

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
        return prompts.render("checklist_empty")
    out = []
    for k, x in issues.items():
        h = x["history"][-1]
        out.append(prompts.render("checklist_entry", id=k, status=x["status"].upper(), title=x["title"], direction=x["direction"],
                                  n=len(x["items"]), items=", ".join(x["items"]), root_cause=x["root_cause"],
                                  clause=" ".join(x["clause"].split())[:200], fix=x["fix"], version=h["version"],
                                  mean_error=f"{h['mean_error']:+.2f}", threshold=f"{h['threshold']:.2f}",
                                  history=" → ".join(f"r{e['round']} {e['status']}" for e in x["history"])))
    return "\n".join(out)


def summarise(rubric: str, version: str, versions: list[str], reviews: dict, errs: dict, out: dict, change: str,
              numbers: str, checklist: dict[str, dict], model: str, effort: str) -> dict:
    """The round's diagnosis from every item's note, the measured numbers (`numbers`, a line code wrote) and the
    checklist. One call, no tools: the judge names issues and their items, code measures them afterwards.
    Missed items come first, then the aligned ones (what the rubric gets right is evidence too)."""
    order = sorted(reviews, key=lambda i: (errs.get(i) in (0, 0.0, None), i))
    notes = [prompts.render("judge_note", id=i, direction=reviews[i]["direction"], size=_size(errs.get(i), out),
                            clause=reviews[i]["clause"][:200], comment=reviews[i]["comment"]) for i in order]
    user = prompts.render("judge_summary", version=version, rubric=rubric, versions=versions, numbers=numbers,
                          checklist=checklist_text(checklist), change=change, notes="\n".join(notes))
    return {**ROUND_DEFAULTS, **llm.call(model, prompts.system("judge"), user, SUMMARY_SCHEMA, effort=effort, role="judge")}


def synthetic_reviews(errs: dict[str, float]) -> dict[str, dict]:
    """Review rows from the numbers alone, for the shared stages that run no per-item judge: every missed pair
    (`<metric>:<item>`) with its direction and size."""
    return {pid: {"direction": "too_high" if e > 0 else "too_low", "clause": "",
                  "comment": prompts.render("synthetic_review", metric=pid.split(":", 1)[0], size=f"{abs(e):g}")}
            for pid, e in sorted(errs.items()) if e}


def _size(e: float | None, out: dict) -> str:
    if e is None:
        return "?"
    return ("miss" if e else "match") if out["type"] == "enum" else f"off by {abs(e):g}"
