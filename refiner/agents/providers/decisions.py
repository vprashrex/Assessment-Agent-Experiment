"""The decision APIs as the scorer: OpenAI `/v1/decisions` (gpt-6-luna-decisions) and Gemini decisions (gemini-decision-1).

No prose comes back. Per metric the call asks one question about the submission: a `score` question whose ordered
levels are the metric's own integer scale, or a `choice` question whose options are an enum's values. The answer
is a calibrated probability per level; the score recorded is the most likely level (what production reports),
and the probability-weighted expected value, the confidence and the whole distribution ride along in the item's
answer for the judge. Input: the rubric first (evidence), the item's files, then the submission text. Output
tokens are free, so a call costs its input only.

OpenAI accepts 2–10 levels and images only: an 11-level scale merges its two lowest levels (`check` says so), and
a PDF goes as one image per page. Gemini accepts 2–255 levels and PDFs as documents.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from ... import prompts
from .. import models, spend
from . import base
from .base import Files, LLMError, b64

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/decisions"
OPENAI_MAX_LEVELS = 10
TRIES = 4
RETRY_STATUS = (429, 500, 502, 503, 504)


def is_decision(model: str) -> bool:
    """A model served by a decision API (models.yaml: completion_type includes `decision`)."""
    return "decision" in (models.entry(model).get("completion_type") or [])


def api_name(model: str) -> str:
    """The id sent to the API: `api_name` in models.yaml when the catalog name differs from it."""
    return models.entry(model).get("api_name") or model


def levels(out: dict, provider: str) -> list[tuple[str, float]]:
    """(label, value) per ordered level of a number metric, lowest first. OpenAI takes at most 10 levels, so a
    longer scale merges its lowest levels into one (its value is the merged range's upper bound)."""
    lo, hi = int(out["min"]), int(out["max"])
    vals = [float(v) for v in range(lo, hi + 1)]
    if provider == "openai" and len(vals) > OPENAI_MAX_LEVELS:
        cut = len(vals) - OPENAI_MAX_LEVELS + 1
        return [(f"{int(vals[0])} to {int(vals[cut - 1])}", vals[cut - 1])] + [(str(int(v)), v) for v in vals[cut:]]
    return [(str(int(v)), v) for v in vals]


def check(model: str, outs: dict[str, dict], items: list[dict]) -> list[str]:
    """Plain-language warnings for this scorer on these metrics and items, for debug.txt at preparation."""
    if not is_decision(model):
        return []
    notes = []
    p = models.provider(model)
    for k, o in outs.items():
        if o["type"] == "number" and p == "openai" and int(o["max"]) - int(o["min"]) + 1 > OPENAI_MAX_LEVELS:
            lv = levels(o, p)[0][0]
            notes.append(f"{model} takes at most {OPENAI_MAX_LEVELS} score levels: metric {k} ({o['field']}) scores {lv} as one "
                         f"level, so an exact match there is impossible and the gate undercounts it")
    pdfs = sum(1 for it in items for f in it.get("files") or [] if str(f).lower().endswith(".pdf"))
    if pdfs and p == "openai":
        notes.append(f"{model} takes images only: {pdfs} PDF attachment(s) are sent as one image per page (more input tokens)")
    return notes


# ---------- questions ----------
def _instructions(out: dict) -> str:
    return prompts.render("decision_instructions", field=out["field"])


def _openai_questions(outs: dict[str, dict]) -> list[dict]:
    qs = []
    for k, o in outs.items():
        if o["type"] == "enum":
            qs.append({"type": "choice", "name": k, "instructions": _instructions(o),
                       "choices": [{"value": v, "description": prompts.render("decision_choice", value=v, field=o["field"])}
                                   for v in o["values"]]})
        else:
            qs.append({"type": "score", "name": k, "instructions": _instructions(o),
                       "levels": [{"label": lab, "description": prompts.render("decision_level", label=lab, field=o["field"])}
                                  for lab, _ in levels(o, "openai")]})
    return qs


def _gemini_questions(outs: dict[str, dict]) -> dict[str, dict]:
    qs = {}
    for k, o in outs.items():
        if o["type"] == "enum":
            qs[k] = {"type": "choice", "instructions": _instructions(o),
                     "criteria": {v: prompts.render("decision_choice", value=v, field=o["field"]) for v in o["values"]}}
        else:
            qs[k] = {"type": "score", "instructions": _instructions(o),
                     "criteria": [prompts.render("decision_level", label=lab, field=o["field"]) for lab, _ in levels(o, "gemini")]}
    return qs


# ---------- answers ----------
def _distribution(out: dict, provider: str, probs: list[float]) -> dict[str, Any]:
    """The item's answer for one metric from its per-level probabilities: the most likely level as the score, plus
    the expected value, the confidence (the top probability) and the distribution by label."""
    labels = out["values"] if out["type"] == "enum" else [lab for lab, _ in levels(out, provider)]
    values = labels if out["type"] == "enum" else [v for _, v in levels(out, provider)]
    probs = [float(p or 0) for p in probs][:len(labels)]
    if len(probs) != len(labels) or sum(probs) <= 0:
        return {out["field"]: None}
    top = max(range(len(probs)), key=probs.__getitem__)
    f = out["field"]
    ans = {f: values[top], f"{f} confidence": round(probs[top], 4), f"{f} probabilities": {labels[i]: round(probs[i], 4) for i in range(len(labels))}}
    if out["type"] != "enum":
        ans[f"{f} expected"] = round(sum(values[i] * probs[i] for i in range(len(probs))), 3)
    return ans


def _refused(out: dict) -> dict[str, Any]:
    return {out["field"]: None, f"{out['field']} refusal": True}


def _openai(model: str, rubric: str, user: str, files: Files, outs: dict[str, dict]) -> dict[str, Any]:
    # one user message of parts; the rubric ends a cacheable prefix (prompt_cache_breakpoint), files and submission follow
    parts: list[dict] = [{"type": "input_text", "text": rubric, "prompt_cache_breakpoint": {"mode": "explicit"}}]
    for mt, data in files:
        if mt == "application/pdf":
            from ...utils.files import pdf_pages
            parts += [{"type": "input_image", "image_url": f"data:image/png;base64,{b64(png)}"} for png in pdf_pages(data)]
        else:
            parts.append({"type": "input_image", "image_url": f"data:{mt};base64,{b64(data)}"})
    parts.append({"type": "input_text", "text": user})
    r = base.client("openai").decisions.create(model=api_name(model), input=[{"type": "message", "role": "user", "content": parts}],
                                               questions=_openai_questions(outs)).model_dump()
    if u := r.get("usage"):
        det = u.get("input_tokens_details") or {}
        cached, written = det.get("cached_tokens", 0) or 0, det.get("cache_write_tokens", 0) or 0
        spend.record(model, (u.get("input_tokens", 0) or 0) - cached - written, 0, cache_write=written, cache_read=cached)
    answer: dict[str, Any] = {}
    for q, a in zip(outs.items(), r["answers"]):
        k, o = q
        if a.get("type") == "score":
            answer.update(_distribution(o, "openai", [p["probability"] for p in a["probabilities"]]))
        elif a.get("type") == "choice":
            by = {str(p["value"]): p["probability"] for p in a["probabilities"]}
            answer.update(_distribution(o, "openai", [by.get(v, 0) for v in o["values"]]))
        else:
            answer.update(_refused(o))
    return answer


def _gemini(model: str, rubric: str, user: str, files: Files, outs: dict[str, dict]) -> dict[str, Any]:
    blocks: list[dict] = [{"type": "text", "text": rubric}]
    blocks += [{"type": "document" if mt == "application/pdf" else "image", "data": b64(data), "mime_type": mt} for mt, data in files]
    blocks.append({"type": "text", "text": user})
    body = {"model": api_name(model), "input": blocks, "questions": _gemini_questions(outs)}
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    r = None
    for attempt in range(TRIES):
        r = httpx.post(GEMINI_URL, json=body, timeout=300, headers={"x-goog-api-key": key or "", "Content-Type": "application/json"})
        if r.status_code in RETRY_STATUS and attempt < TRIES - 1:
            time.sleep(5 * (attempt + 1))
            continue
        break
    if r is None or r.status_code != 200:
        raise LLMError(f"{model}: {r.status_code if r is not None else '?'} {r.text[:300] if r is not None else ''}")
    d = r.json()
    if u := d.get("usage"):
        spend.record(model, u.get("total_input_tokens", u.get("totalInputTokens", 0)) or 0, 0)
    answer: dict[str, Any] = {}
    for k, o in outs.items():
        a = (d.get("answers") or {}).get(k) or {}
        pr = a.get("probabilities")
        if a.get("type") == "score" and pr is not None:
            n = len(levels(o, "gemini"))
            probs = ([x.get("probability", 0) for x in pr] if pr and isinstance(pr[0], dict) else list(pr)) if isinstance(pr, list) \
                else [pr.get(str(i), 0) for i in range(n)]
            answer.update(_distribution(o, "gemini", probs))
        elif a.get("type") == "choice" and pr is not None:
            by = {str(x.get("value", x.get("option"))): x.get("probability", 0) for x in pr} if isinstance(pr, list) and pr and isinstance(pr[0], dict) \
                else dict(pr) if isinstance(pr, dict) else {}
            answer.update(_distribution(o, "gemini", [by.get(v, 0) for v in o["values"]]))
        else:
            answer.update(_refused(o))
    return answer


ASK = {"openai": _openai, "google": _gemini}


def ask(model: str, rubric: str, user: str, files: Files, outs: dict[str, dict]) -> dict[str, Any]:
    """One decision call for one item: every metric's question at once. Returns the item's answer in the shape of
    a generative scorer's JSON (field -> value, plus the `<field> expected / confidence / probabilities` keys)."""
    fn = ASK.get(models.provider(model))
    if fn is None:
        raise LLMError(f"{model}: no decision API for provider {models.provider(model)}")
    return fn(model, rubric, user, files, outs)
