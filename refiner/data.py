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

import difflib
import io
import html
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / "cache" / "files"
GDOC = re.compile(r"docs\.google\.com/document/d/([\w-]+)")
DRIVE = re.compile(r"(?:/d/|[?&]id=)([\w-]{20,})")
LINK = re.compile(r"https?://\S+")
IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
FILE_EXT = {".pdf": "application/pdf", **IMAGE_EXT}


def read_sheet(path: Path, sheet: str | None = None) -> pd.DataFrame:
    """The named sheet (or a CSV file), else the fullest one; empty rows/columns and 'Unnamed' columns dropped;
    hyperlinks resolved."""
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
        df.columns = [str(c).strip() for c in df.columns]
        df = df[[c for c in df.columns if not c.startswith("Unnamed")]].dropna(axis=1, how="all").dropna(axis=0, how="all")
        return df.reset_index(drop=True)
    xls = pd.ExcelFile(path)
    name = sheet or max(xls.sheet_names, key=lambda s: xls.parse(s).count().sum())
    df = xls.parse(name)
    df.columns = [str(c).strip() for c in df.columns]
    try:  # cells whose text is a label but whose hyperlink is the URL
        import openpyxl
        ws = openpyxl.load_workbook(path)[name]
        for j, col in enumerate(df.columns, start=1):
            links = [ws.cell(r, j).hyperlink.target if ws.cell(r, j).hyperlink else None for r in range(2, len(df) + 2)]
            if any(links):
                df[col] = [l or v for l, v in zip(links, df[col])]
    except Exception:
        pass
    df = df[[c for c in df.columns if not c.startswith("Unnamed")]].dropna(axis=1, how="all").dropna(axis=0, how="all")
    return df.reset_index(drop=True)


def _key(url: str) -> str:
    m = GDOC.search(url) or DRIVE.search(url)
    return m.group(1) if m else re.sub(r"\W+", "_", url)[-80:]


def _download(url: str) -> tuple[bytes, str] | None:
    if (m := GDOC.search(url)):
        get = f"https://docs.google.com/document/d/{m.group(1)}/export?format=pdf"
    elif (m := DRIVE.search(url)):
        get = f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    else:
        get = url
    try:
        r = httpx.get(get, follow_redirects=True, timeout=90, headers={"User-Agent": "Mozilla/5.0"})
    except httpx.HTTPError:
        return None
    if r.status_code != 200 or b"accounts.google.com" in r.content[:4000]:
        return None  # not public
    return r.content, r.headers.get("content-type", "").split(";")[0].lower()


def _ext(data: bytes, ctype: str) -> str:
    if data[:4] == b"%PDF":
        return ".pdf"
    if data[:2] == b"PK":
        return ".docx"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"GIF8":
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".html" if "html" in ctype or b"<html" in data[:2000].lower() else ".txt"


def _local(hints: list[str], docs_dir: Path | None) -> Path | None:
    """A file in docs_dir whose name best matches one of the row's text values (title, name...)."""
    if not docs_dir:
        return None
    files = [p for p in docs_dir.iterdir() if p.is_file() and not p.name.startswith(".")]
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()  # noqa: E731
    best, score = None, 0.0
    for p in files:
        stem = norm(p.stem)
        for h in hints:
            h = norm(h)
            if len(h) < 4 or h in ("nan", "none", "null"):
                continue
            s = 1.0 if f" {h} " in f" {stem} " else difflib.SequenceMatcher(None, h, stem[: len(h) + 5]).ratio()
            if s > score:
                best, score = p, s
    return best if score >= 0.75 else None


def fetch(url: str, hints: list[str], docs_dir: Path | None) -> Path | None:
    """The linked file, downloaded once into cache/files/<key>.<ext>; falls back to a matching file in docs_dir."""
    FILES.mkdir(parents=True, exist_ok=True)
    key = _key(url)
    for p in FILES.glob(f"{key}.*"):
        return p
    got = _download(url)
    if got:
        p = FILES / f"{key}{_ext(*got)}"
        p.write_bytes(got[0])
        return p
    if (local := _local(hints, docs_dir)):
        p = FILES / f"{key}{local.suffix.lower()}"
        shutil.copy(local, p)
        return p
    return None


def _html_text(data: bytes) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(data, "html.parser")
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "noscript"]):
        t.decompose()
    text = (soup.find("article") or soup.find("main") or soup.body or soup).get_text("\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:40_000]


def _docx(path: Path) -> tuple[str, list[Path]]:
    """DOCX -> its text and its embedded images (extracted next to it in the cache)."""
    z = zipfile.ZipFile(path)
    xml = z.read("word/document.xml").decode("utf8", "ignore")
    text = re.sub(r"<[^>]+>", "", xml.replace("</w:p>", "\n")).strip()
    imgs = []
    for name in z.namelist():
        ext = Path(name).suffix.lower()
        if name.startswith("word/media/") and ext in IMAGE_EXT:
            out = path.with_name(f"{path.stem}__{Path(name).name}")
            if not out.exists():
                out.write_bytes(z.read(name))
            imgs.append(out)
    return text, imgs


def resolve(path: Path) -> tuple[str, list[Path]]:
    """A cached file -> (text to inline, files to attach)."""
    ext = path.suffix.lower()
    if ext in FILE_EXT:
        return "", [path]
    if ext == ".docx":
        return _docx(path)
    if ext == ".html":
        return _html_text(path.read_bytes()), []
    return path.read_text(errors="ignore")[:40_000], []


def build_items(df: pd.DataFrame, setup: dict, docs_dir: Path | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Items for every row with an id, some input, and a reference value for at least one metric. Returns (items, problems).
    `truths` holds every metric's reference by key; `truth` is the first one's (what a single-metric run reads)."""
    from .agents import metrics_of
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
