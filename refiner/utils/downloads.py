"""Linked files: download once into cache/files/<key>.<ext> (Google Docs as PDF, Drive files, any URL), else
use a matching file from the operator's docs folder."""

from __future__ import annotations

import difflib
import re
import shutil
from pathlib import Path

import httpx

from ..paths import ROOT
from .documents import extension

FILES = ROOT / "cache" / "files"
GDOC = re.compile(r"docs\.google\.com/document/d/([\w-]+)")
DRIVE = re.compile(r"(?:/d/|[?&]id=)([\w-]{20,})")


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
        p = FILES / f"{key}{extension(*got)}"
        p.write_bytes(got[0])
        return p
    if (local := _local(hints, docs_dir)):
        p = FILES / f"{key}{local.suffix.lower()}"
        shutil.copy(local, p)
        return p
    return None
