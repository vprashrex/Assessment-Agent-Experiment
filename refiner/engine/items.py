"""Sheet -> items. No model calls here.

Each item: id, `input` (the text columns), `files` (the actual attachments: PDFs and images, passed to the models
as files so they see layout, scans and pictures), and the reference value.

Input column types:
  text        shown as written
  document    a link whose target IS the submission (Google Doc, Drive file, PDF, DOCX, web page)
  attachment  one or more links to supporting files (photos, scans, PDFs)
PDFs and images go to the model as files; DOCX gives its text plus its embedded images; web pages give their text.
A link that cannot be downloaded is looked up in --docs-dir (files named after the submission), else skipped.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

import pandas as pd

from ..utils.documents import IMAGE_EXT, docx, html_text
from ..utils.downloads import fetch

LINK = re.compile(r"https?://\S+")
FILE_EXT = {".pdf": "application/pdf", **IMAGE_EXT}


def resolve(path: Path) -> tuple[str, list[Path]]:
    """A cached file -> (text to inline, files to attach)."""
    ext = path.suffix.lower()
    if ext in FILE_EXT:
        return "", [path]
    if ext == ".docx":
        return docx(path)
    if ext == ".html":
        return html_text(path.read_bytes()), []
    return path.read_text(errors="ignore")[:40_000], []


def build_items(df: pd.DataFrame, setup: dict, docs_dir: Path | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Items for every row with an id, some input, and a reference value for at least one metric. Returns (items, problems).
    `truths` holds every metric's reference by key; `truth` is the first one's (what a single-metric run reads)."""
    from ..agents import metrics_of
    items, problems = [], []
    idc, ms = setup["id_column"], metrics_of(setup)
    for i, r in df.iterrows():
        rid = str(r[idc]).strip() if idc and pd.notna(r[idc]) else f"row{i}"
        truths = {m["key"]: None if pd.isna(r[m["truth_column"]]) else r[m["truth_column"]] for m in ms}
        if all(v is None for v in truths.values()):
            continue
        hints = [str(r[c["name"]]) for c in setup["input_columns"] if c["type"] == "text" and pd.notna(r.get(c["name"]))]
        parts, files = [], []
        for col in setup["input_columns"]:
            v = r.get(col["name"])
            if v is None or (isinstance(v, float) and pd.isna(v)):
                continue
            if col["type"] == "text":
                parts.append(f"{col['name']}:\n{v}")
                continue
            for url in LINK.findall(html.unescape(str(v))) or [str(v)]:  # links exported from HTML carry &amp;
                p = fetch(url, hints, docs_dir)
                if not p:
                    problems.append(f"{rid}: could not get {col['name']} ({url[:80]})")
                    continue
                text, attach = resolve(p)
                if text:
                    parts.append(f"{col['name']}:\n{text}")
                files += [str(f.resolve()) for f in attach]
                if attach and not text:
                    parts.append(f"{col['name']}: attached as file{'s' if len(attach) > 1 else ''} ({', '.join(f.name for f in attach)})")
        if not parts and not files:
            problems.append(f"{rid}: no input, skipped")
            continue
        fields = {c: html.unescape(str(r[c])) if pd.notna(r[c]) else "" for c in [idc, *(x["name"] for x in setup["input_columns"])] if c}
        items.append({"id": rid, "input": "\n\n".join(parts), "files": files, "truth": truths[ms[0]["key"]], "truths": truths,
                      "fields": fields})
    return items, problems
