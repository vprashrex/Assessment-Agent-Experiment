"""The generator: writes the next version of the metrics sections from the judge's diagnosis, as edits (EDIT) or
a full rewrite of the editable parts (REWRITE). It never sees reference values; code refuses edits to locked text."""

from __future__ import annotations

import re

from .. import prompts
from . import llm
from .judge import checklist_text
from .layers import EDITABLE, annotated

GEN_SCHEMA = {"type": "object", "properties": {
    "realisation": {"type": "string"},
    "edits": {"type": "array", "items": {"type": "object", "properties": {
        "issue": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
        "required": ["issue", "old_text", "new_text"]}},
    "rewrite": {"type": "array", "items": {"type": "string"}},
    "summary": {"type": "string"}}, "required": ["realisation", "edits", "rewrite", "summary"]}

_SUBS = str.maketrans({"–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"', " ": " "})


def _find(text: str, snippet: str) -> tuple[int, int] | None:
    """Span of `snippet` in `text`, exact first, then tolerant of dash/quote/whitespace differences."""
    if text.count(snippet) == 1:
        i = text.index(snippet)
        return i, i + len(snippet)
    words = re.findall(r"\S+", snippet.translate(_SUBS))
    if not words:
        return None
    pat = r"\s+".join(re.escape(w) for w in words)
    hits = list(re.finditer(pat, text.translate(_SUBS)))
    return (hits[0].start(), hits[0].end()) if len(hits) == 1 else None


def _keep_newline(old: str, new: str) -> str:
    return new if not old.endswith("\n") or new.endswith("\n") else new + "\n"


def apply(chunks: list[dict], edits: list[dict]) -> tuple[list[dict], list[str]]:
    """Splice each edit into the one EDITABLE chunk that holds its old_text; edits touching locked text are refused."""
    chunks, problems = [dict(c) for c in chunks], []
    for e in edits:
        hits = [(k, sp) for k, c in enumerate(chunks) if (sp := _find(c["text"], e["old_text"]))]
        ok = [(k, sp) for k, sp in hits if chunks[k]["layer"] == EDITABLE]
        if len(ok) != 1:
            problems.append(f"old_text is in a LOCKED part: {e['old_text'][:80]!r}" if hits and not ok
                            else f"old_text not found exactly once in an EDITABLE part: {e['old_text'][:80]!r}")
            continue
        (k, (a, b)), = ok
        t = chunks[k]["text"]
        chunks[k]["text"] = _keep_newline(t, t[:a] + e["new_text"] + t[b:])
    return chunks, problems


def rewrite(chunks: list[dict], parts: list[str]) -> tuple[list[dict], list[str]]:
    """Replace the EDITABLE chunks, in order, with the rewritten parts; locked chunks stay as they are."""
    n = sum(c["layer"] == EDITABLE for c in chunks)
    if len(parts) != n or not all(p.strip() for p in parts):
        return chunks, [f"rewrite must return exactly {n} non-empty parts, one per EDITABLE part, in order"]
    it = iter(parts)
    return [{**c, "text": _keep_newline(c["text"], next(it).strip() + "\n")} if c["layer"] == EDITABLE else dict(c)
            for c in chunks], []


def generate(chunks: list[dict], summary: dict, csv: str, dialogue: str, model: str, effort: str) -> tuple[list[dict], dict, list[str]]:
    pats = checklist_text(summary["checklist"])
    mode = (prompts.render("generator_mode_rewrite", brief=summary["rewrite_brief"]) if summary["mode"] == "rewrite"
            else prompts.render("generator_mode_edit"))
    user = prompts.render("generator", mode=mode, rubric=annotated(chunks), overview=summary["overview"],
                          summary=summary["summary"], checklist=pats, table=csv, dialogue=dialogue[-20000:] or "(none)")

    def build(gen: dict) -> tuple[list[dict], list[str]]:
        return rewrite(chunks, gen["rewrite"]) if summary["mode"] == "rewrite" else apply(chunks, gen["edits"])

    gen = llm.call(model, prompts.system("generator"), user, GEN_SCHEMA, effort=effort)
    new, problems = build(gen)
    if problems:
        gen = llm.call(model, prompts.system("generator"),
                       prompts.render("generator_retry", message=user, problems="; ".join(problems)),
                       GEN_SCHEMA, effort=effort)
        new, problems = build(gen)
    return new, gen, problems
