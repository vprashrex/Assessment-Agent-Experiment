"""The generator: writes the next version of the metrics sections from the judge's diagnosis, as edits (EDIT) or
a full rewrite of the editable parts (REWRITE). It never sees reference values; code refuses edits to locked text."""

from __future__ import annotations

import re

from .. import prompts
from . import llm
from .judge import checklist_text
from .layers import EDITABLE, annotated, editable_words

GEN_SCHEMA = {"type": "object", "properties": {
    "realisation": {"type": "string"},
    "edits": {"type": "array", "items": {"type": "object", "properties": {
        "issue": {"type": "string"}, "op": {"type": "string", "enum": ["replace", "insert_after", "delete"]},
        "old_text": {"type": "string"}, "new_text": {"type": "string"}},
        "required": ["issue", "op", "old_text", "new_text"]}},
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


def _splice(t: str, a: int, b: int, e: dict) -> str:
    """One edit at span [a, b) of `t`: replace it, delete it, or add new_text on its own line after the line it ends on."""
    op = e.get("op", "replace")
    if op == "delete":
        out = t[:a] + t[b:]
        return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+\n", "\n", out))
    if op == "insert_after":
        eol = t.find("\n", b)
        eol = len(t) if eol == -1 else eol
        return t[:eol] + "\n" + e["new_text"].strip("\n") + t[eol:]
    return t[:a] + e["new_text"] + t[b:]


def apply(chunks: list[dict], edits: list[dict], editable: tuple[str, ...] = (EDITABLE,)) -> tuple[list[dict], list[str]]:
    """Each edit (replace, insert_after or delete) on the one EDITABLE chunk that holds its old_text; edits that touch
    locked text are refused."""
    chunks, problems = [dict(c) for c in chunks], []
    for e in edits:
        hits = [(k, sp) for k, c in enumerate(chunks) if (sp := _find(c["text"], e["old_text"]))]
        ok = [(k, sp) for k, sp in hits if chunks[k]["layer"] in editable]
        if len(ok) != 1:
            problems.append(prompts.render("problem_locked" if hits and not ok else "problem_not_found", old=repr(e["old_text"][:80])))
            continue
        (k, (a, b)), = ok
        t = chunks[k]["text"]
        chunks[k]["text"] = _keep_newline(t, _splice(t, a, b, e))
    return chunks, problems


def rewrite(chunks: list[dict], parts: list[str], editable: tuple[str, ...] = (EDITABLE,)) -> tuple[list[dict], list[str]]:
    """Replace the EDITABLE chunks, in order, with the rewritten parts; locked chunks stay as they are."""
    n = sum(c["layer"] in editable for c in chunks)
    if len(parts) != n or not all(p.strip() for p in parts):
        return chunks, [prompts.render("problem_rewrite_parts", n=n)]
    it = iter(parts)
    return [{**c, "text": _keep_newline(c["text"], next(it).strip() + "\n")} if c["layer"] in editable else dict(c)
            for c in chunks], []


RETRIES = 2


def generate(chunks: list[dict], summary: dict, csv: str, dialogue: str, model: str, effort: str,
             v0_words: int, editable: tuple[str, ...] = (EDITABLE,)) -> tuple[list[dict], dict, list[str]]:
    """The next version. The generator decides each change (replace, insert_after, delete) and how many words the
    text needs; it is shown the current and the original word count. Edits that cannot be applied are sent back with
    the reason, up to RETRIES times; any problem left is returned with the version."""
    pats = checklist_text(summary["checklist"])
    mode = (prompts.render("generator_mode_rewrite", brief=summary["rewrite_brief"]) if summary["mode"] == "rewrite"
            else prompts.render("generator_mode_simplify") if summary["mode"] == "simplify"
            else prompts.render("generator_mode_edit"))
    length = prompts.render("generator_length", words=editable_words(chunks, editable), v0_words=v0_words)
    user = prompts.render("generator", mode=mode, length=length, rubric=annotated(chunks, editable), overview=summary["overview"],
                          summary=summary["summary"], checklist=pats, table=csv, dialogue=dialogue[-20000:] or "(none)")

    def build(gen: dict) -> tuple[list[dict], list[str]]:
        new, problems = (rewrite(chunks, gen["rewrite"], editable) if summary["mode"] == "rewrite"
                         else apply(chunks, gen["edits"], editable))
        for c in new:  # degenerate filler (", , , ," runs and the like) must never enter the rubric
            if c["layer"] in editable and (m := re.search(r"(\S{1,3})(\s*\1){9,}", c["text"])):
                problems.append(prompts.render("problem_repetition", sample=repr(m.group(0)[:40])))
        return new, problems

    gen = llm.call(model, prompts.system("generator"), user, GEN_SCHEMA, effort=effort)
    new, problems = build(gen)
    for _ in range(RETRIES):
        if not problems:
            break
        gen = llm.call(model, prompts.system("generator"),
                       prompts.render("generator_retry", message=user, problems="; ".join(problems)),
                       GEN_SCHEMA, effort=effort)
        new, problems = build(gen)
    return new, gen, problems
