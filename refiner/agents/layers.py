"""The rubric as the agents handle it, and what every agent shares.

The parser cuts the baseline prompt into ordered chunks, each tagged with a layer. Only `metrics` chunks are ever
edited; the program context, the global notes and the output instruction stay word for word. With several metrics,
every metrics chunk also names the metric it scores. Also here: reading a reference value, and an item's attached
files as the models receive them.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from .. import prompts
from ..paths import ROOT
from ..utils.files import MIME as MEDIA  # the attachment types every agent sends

LAYERS = ["program", "metrics", "procedure", "notes", "output"]
EDITABLE = "metrics"          # the per-metric layer; each fan-out loop edits only its own chunks
PROCEDURE = "procedure"       # shared scoring logic (gates, tie-breaks); tuned once for all metrics, never per metric
MAX_IMAGE = 4_500_000


def kind_of(setup: dict, out: dict) -> str:
    """How errors are measured for an output: 'verdict' in feedback mode (references are reviewers' verdicts),
    else the output's type ('number' | 'enum')."""
    return "verdict" if setup.get("feedback") else out["type"]


def refs_by(items: list[dict], outs: dict[str, dict], ids=None) -> dict[str, dict]:
    """metric key -> {item id -> reference value}, for the items in `ids` (all when None)."""
    keep = None if ids is None else set(ids)
    return {k: {it["id"]: v for it in items if (keep is None or it["id"] in keep)
                and (v := reference(it["truths"].get(k), outs[k])) is not None} for k in outs}


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


def editable_words(chunks: list[dict], editable: tuple[str, ...] = (EDITABLE,)) -> int:
    """Words in the parts a loop may change (shown to the generator, used in the gate's tie-break)."""
    return sum(len(c["text"].split()) for c in chunks if c["layer"] in editable)


def assemble(chunks: list[dict]) -> str:
    return "".join(c["text"] for c in chunks)


def annotated(chunks: list[dict], editable: tuple[str, ...] = (EDITABLE,)) -> str:
    """The prompt as the agents see it: every chunk marked LOCKED or EDITABLE with its layer."""
    out, k = [], 0
    for c in chunks:
        if c["layer"] in editable:
            k += 1
            out.append(prompts.render("marker_editable", layer=c["layer"], k=k, text=c["text"].rstrip()))
        else:
            out.append(prompts.render("marker_locked", layer=c["layer"], text=c["text"].rstrip()))
    return "\n".join(out) + "\n"


def metrics_of(setup: dict) -> list[dict]:
    """The metrics a run refines: [{key, truth_column, output}]. Setups from before fan-out hold a single one."""
    return setup.get("metrics") or [{"key": "score", "truth_column": setup["truth_column"], "output": setup["output"]}]


def label(v: Any, values: list[str]) -> str | None:
    key = str(v).strip().lower()
    return next((x for x in values if x.strip().lower() == key), None)


def reference(v: Any, out: dict) -> Any:
    if v is None or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, dict):  # feedback mode: a verdict constraint rides through untouched
        return v
    if out["type"] == "enum":
        return label(v, out["values"])
    try:
        return float(v)
    except (TypeError, ValueError):  # a stray label in a score column (a repeated header row) is no reference
        return None


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
