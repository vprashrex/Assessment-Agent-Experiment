"""The four calls: parser (once), scorer (per item), judge (per item + one summary), generator (one per round)."""

from __future__ import annotations

import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pandas as pd

from . import llm, tracing
from .math_tool import item_errors


def label(v: Any, values: list[str]) -> str | None:
    key = str(v).strip().lower()
    return next((x for x in values if x.strip().lower() == key), None)


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


def reference(v: Any, out: dict) -> Any:
    if v is None or (isinstance(v, float) and v != v):
        return None
    return label(v, out["values"]) if out["type"] == "enum" else float(v)

PROMPTS = Path(__file__).parent / "prompts"
ROOT = Path(__file__).resolve().parents[1]
MEDIA = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
         ".webp": "image/webp"}
MAX_IMAGE = 4_500_000


def files_of(item: dict) -> list[tuple[str, bytes]]:
    """The item's attachments as (media_type, bytes); large images are shrunk to fit the APIs."""
    out = []
    for f in item.get("files", []):
        p = Path(f) if Path(f).is_absolute() else ROOT / f
        mt, data = MEDIA[p.suffix.lower()], p.read_bytes()
        if mt.startswith("image/") and (len(data) > MAX_IMAGE or mt == "image/gif"):
            from PIL import Image
            im = Image.open(io.BytesIO(data)).convert("RGB")
            im.thumbnail((3000, 3000))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
            mt, data = "image/jpeg", buf.getvalue()
        out.append((mt, data))
    return out


def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text()


# ---------- prompt layers ----------
# The parser cuts the baseline prompt into ordered chunks, each tagged with a layer. Only `metrics` chunks are ever
# edited; the program context, the global notes and the output instruction stay word for word. With several metrics,
# every metrics chunk also names the metric it scores.

LAYERS = ["program", "metrics", "notes", "output"]
EDITABLE = "metrics"


def numbered(text: str) -> str:
    return "".join(f"{i:>4}| {ln}" for i, ln in enumerate(text.splitlines(keepends=True), start=1))


def layout(text: str, spans: list[dict]) -> tuple[list[dict], list[str]]:
    """Line spans from the parser -> ordered chunks [{layer, text}] that join back to `text` exactly."""
    lines = text.splitlines(keepends=True)
    spans, problems, nxt = sorted(spans, key=lambda s: s["from_line"]), [], 1
    for s in spans:
        if s["from_line"] != nxt or s["to_line"] < s["from_line"]:
            problems.append(f"layer spans must cover every line once, in order; problem at line {nxt} ({s})")
        nxt = s["to_line"] + 1
    if nxt != len(lines) + 1:
        problems.append(f"layer spans end at line {nxt - 1}; the prompt has {len(lines)} lines")
    chunks: list[dict] = []
    for s in spans:
        t = "".join(lines[s["from_line"] - 1:s["to_line"]])
        metric = s.get("metric") if s["layer"] == EDITABLE else None
        if chunks and chunks[-1]["layer"] == s["layer"] and chunks[-1].get("metric") == metric:
            chunks[-1]["text"] += t
        else:
            chunks.append({"layer": s["layer"], "text": t, **({"metric": metric} if metric else {})})
    if not problems and assemble(chunks) != text:
        problems.append("the layers do not join back to the original prompt")
    if not any(c["layer"] == EDITABLE for c in chunks):
        problems.append("no part of the prompt was marked as the metrics layer, so nothing could be refined")
    return chunks, problems


def assemble(chunks: list[dict]) -> str:
    return "".join(c["text"] for c in chunks)


def annotated(chunks: list[dict]) -> str:
    """The prompt as the agents see it: every chunk marked LOCKED or EDITABLE with its layer."""
    out, k = [], 0
    for c in chunks:
        if c["layer"] == EDITABLE:
            k += 1
            out.append(f"[EDITABLE · {c['layer']} · part {k}]\n{c['text'].rstrip()}\n[/EDITABLE]")
        else:
            out.append(f"[LOCKED · {c['layer']}]\n{c['text'].rstrip()}\n[/LOCKED]")
    return "\n".join(out) + "\n"


# ---------- parser ----------

SETUP_SCHEMA = {
    "type": "object",
    "properties": {
        "id_column": {"type": ["string", "null"]},
        "input_columns": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "type": {"type": "string", "enum": ["text", "document", "attachment"]}}, "required": ["name", "type"]}},
        "metrics": {"type": "array", "items": {"type": "object", "properties": {
            "key": {"type": "string"},
            "truth_column": {"type": "string"},
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


def metrics_of(setup: dict) -> list[dict]:
    """The metrics a run refines: [{key, truth_column, output}]. Setups from before fan-out hold a single one."""
    return setup.get("metrics") or [{"key": "score", "truth_column": setup["truth_column"], "output": setup["output"]}]


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
    user = (f"OPERATOR NOTES:\n{context}\n\nCURRENT PROMPT (line-numbered):\n<<<\n{numbered(rubric)}>>>\n\n"
            f"OUTPUT SCHEMA (may be absent):\n{json.dumps(schema) if schema else '(none)'}\n\n"
            f"COLUMNS:\n{json.dumps(profile(df), ensure_ascii=False, indent=1)}")
    setup = llm.call(model, prompt("parser"), user, SETUP_SCHEMA, effort=effort, name="parse-sheet")
    ms, q = setup["metrics"], setup["questions"]
    keys = [m["key"] for m in ms]
    if not ms or len(set(keys)) != len(keys):
        q.append(f"Metric keys must be present and distinct; got {keys}.")
    for sp in setup["layers"]:  # one metric: its chunks need no tag
        if sp["layer"] == EDITABLE and not sp.get("metric") and len(ms) == 1:
            sp["metric"] = keys[0]
    cols = set(df.columns)
    bad = [c["name"] for c in setup["input_columns"] if c["name"] not in cols] + [m["truth_column"] for m in ms if m["truth_column"] not in cols]
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


# ---------- scorer ----------

def output_schema(out: dict) -> dict:
    field = ({"type": "string", "enum": out["values"]} if out["type"] == "enum"
             else {"type": "integer" if float(out["min"]).is_integer() and float(out["max"]).is_integer() else "number"})
    return {"type": "object", "properties": {out["field"]: field}, "required": [out["field"]]}


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
            answer = llm.call(model, rubric, it["input"] + "\n\nReturn the JSON object exactly as specified.", schema, effort=effort,
                              files=files_of(it), name="score-item", metadata={"item": it["id"]})
        except llm.LLMError:
            answer = {}
        return it["id"], answer

    with ThreadPoolExecutor(workers) as ex:
        answers = dict(ex.map(tracing.bind(one), items))
    if raw is not None:
        raw.update(answers)
    return {k: {i: parse_output(a, o) for i, a in answers.items()} for k, o in outs.items()}


# ---------- judge ----------

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
        user = (f"TASK: ITEM\n\nRUBRIC (the scoring model sees it without the LOCKED/EDITABLE marks):\n<<<\n{rubric}\n>>>\n\nSUBMISSION (as the scoring model saw it; any attached files are part of it):\n"
                f"<<<\n{it['input'][:30000]}\n>>>\n\n"
                f"MODEL OUTPUT: {p}\nREFERENCE: {t}\nERROR (output − reference): {_gap(p, t, out)}")
        try:
            return it["id"], llm.call(model, prompt("judge"), user, ITEM_SCHEMA, effort=effort, files=files_of(it),
                                     name="review-item", metadata={"item": it["id"], "output": p, "reference": t})
        except llm.LLMError as e:
            return it["id"], {"observations": "", "model_reasoning": "", "direction": "aligned", "clause": "none",
                              "comment": f"(review unavailable: {e})"}

    todo = [it for it in items if preds.get(it["id"]) is not None and truths.get(it["id"]) is not None]
    with ThreadPoolExecutor(workers) as ex:
        return dict(ex.map(tracing.bind(one), todo))


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
    user = (f"TASK: SUMMARY\n\nCURRENT BEST RUBRIC ({version}; the scoring model sees it without the LOCKED/EDITABLE marks):\n<<<\n{rubric}\n>>>\n\n"
            f"VERSIONS SCORED SO FAR: {versions}\n\nISSUE CHECKLIST FROM EARLIER ROUNDS:\n{checklist_text(checklist)}\n\n"
            f"WHAT CHANGED SINCE LAST ROUND:\n{change}\n\nNOTES ON EVERY SUBMISSION, scored with {version}:\n" + "\n".join(notes)
            + f"\n\nDIALOGUE SO FAR:\n{dialogue[-20000:] or '(none)'}")
    return llm.call(model, prompt("judge"), user, SUMMARY_SCHEMA, effort=effort, tools=tools, tool_log=tool_log,
                    name="summarise-round", metadata={"version": version})


def _size(e: float | None, out: dict) -> str:
    if e is None:
        return "?"
    return ("miss" if e else "match") if out["type"] == "enum" else f"off by {abs(e):g}"


# ---------- generator ----------

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
    task = (f"MODE: REWRITE — the reviewer measured the misses as scattered with no systematic pattern, so piecewise edits will "
            f"not converge. Brief: {summary['rewrite_brief']}" if summary["mode"] == "rewrite" else "MODE: EDIT")
    user = (f"{task}\n\nCURRENT RUBRIC:\n<<<\n{annotated(chunks)}>>>\n\nREVIEWER OVERVIEW:\n{summary['overview']}\n\n"
            f"REVIEWER SUMMARY:\n{summary['summary']}\n\nISSUE CHECKLIST:\n{pats}\n\nPER-ITEM TABLE:\n{csv}\n\nDIALOGUE SO FAR:\n{dialogue[-20000:] or '(none)'}")

    def build(gen: dict) -> tuple[list[dict], list[str]]:
        return rewrite(chunks, gen["rewrite"]) if summary["mode"] == "rewrite" else apply(chunks, gen["edits"])

    gen = llm.call(model, prompt("generator"), user, GEN_SCHEMA, effort=effort, name="write-candidate",
                   metadata={"mode": summary["mode"]})
    new, problems = build(gen)
    if problems:
        gen = llm.call(model, prompt("generator"), user + "\n\nREJECTED: " + "; ".join(problems) + ". Fix and return again.",
                       GEN_SCHEMA, effort=effort, name="write-candidate",
                       metadata={"mode": summary["mode"], "retry_after": "; ".join(problems)[:500]})
        new, problems = build(gen)
    return new, gen, problems
