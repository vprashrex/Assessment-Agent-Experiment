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

from ..paths import ROOT

LAYERS = ["program", "metrics", "notes", "output"]
EDITABLE = "metrics"
MEDIA = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
         ".webp": "image/webp"}
MAX_IMAGE = 4_500_000


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


def metrics_of(setup: dict) -> list[dict]:
    """The metrics a run refines: [{key, truth_column, output}]. Setups from before fan-out hold a single one."""
    return setup.get("metrics") or [{"key": "score", "truth_column": setup["truth_column"], "output": setup["output"]}]


def label(v: Any, values: list[str]) -> str | None:
    key = str(v).strip().lower()
    return next((x for x in values if x.strip().lower() == key), None)


def reference(v: Any, out: dict) -> Any:
    if v is None or (isinstance(v, float) and v != v):
        return None
    return label(v, out["values"]) if out["type"] == "enum" else float(v)


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
