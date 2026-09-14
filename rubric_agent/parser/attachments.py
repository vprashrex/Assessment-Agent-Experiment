"""Attachments: fetch a linked image/PDF once, describe it once (an eye, not a brain), cache both."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from ..core import llm
from ..core.config import prompt
from ..core.state import Description

DRIVE_ID = re.compile(r"(?:/d/|[?&]id=)([\w-]{20,})")
VIDEO = re.compile(r"youtu\.?be|vimeo|\.mp4\b|\.mov\b", re.I)
MEDIA = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
EXT2MEDIA = {v: k for k, v in MEDIA.items()}
MAX_IMG_BYTES = 4_500_000
MAX_IMG_SIDE = 7500


def fetch(url: str, raw_dir: Path) -> tuple[Path, str] | None:
    """Download once. (path, media_type) for images/PDFs; None for videos, HTML or failures."""
    if VIDEO.search(url):
        return None
    m = DRIVE_ID.search(url)
    fid = m.group(1) if m else re.sub(r"\W+", "_", url)[-60:]
    for p in raw_dir.glob(f"{fid}.*"):
        return (p, EXT2MEDIA[p.suffix[1:]]) if p.suffix[1:] in EXT2MEDIA else None
    try:
        r = httpx.get(f"https://drive.google.com/uc?export=download&id={fid}" if m else url, follow_redirects=True, timeout=60)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    data, ctype = r.content, r.headers.get("content-type", "").split(";")[0].strip().lower()
    if data[:4] == b"%PDF":
        ctype = "application/pdf"
    ext = MEDIA.get(ctype)
    if not ext:
        (raw_dir / f"{fid}.skip").write_text(ctype or "unknown")
        return None
    if ext != "pdf":
        data, ctype, ext = _shrink(data, ctype, ext)
    p = raw_dir / f"{fid}.{ext}"
    p.write_bytes(data)
    return p, ctype


def _shrink(data: bytes, ctype: str, ext: str) -> tuple[bytes, str, str]:
    """Keep images inside the API's size limits; convert oversized or GIF images to JPEG."""
    try:
        img = Image.open(io.BytesIO(data))
    except Exception:
        return data, ctype, ext
    if len(data) <= MAX_IMG_BYTES and max(img.size) <= MAX_IMG_SIDE and ext != "gif":
        return data, ctype, ext
    img = img.convert("RGB")
    if max(img.size) > 2000:
        s = 2000 / max(img.size)
        img = img.resize((int(img.width * s), int(img.height * s)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue(), "image/jpeg", "jpg"


def describe(path: Path, media_type: str, model: str, txt_dir: Path) -> dict[str, Any]:
    """Neutral description, cached as <file_id>.json next to the raw file."""
    out = txt_dir / f"{path.stem}.json"
    if out.exists():
        return json.loads(out.read_text())
    kind = "pdf" if media_type == "application/pdf" else "image"
    kw = {"pdfs": [path.read_bytes()]} if kind == "pdf" else {"images": [(media_type, path.read_bytes())]}
    try:
        d, _ = llm.call(model, prompt("parser_describe"), "Describe this attachment.", Description, role="describe", effort="low", **kw)
        rec = {"file_id": path.stem, "type": kind, "description": d.description, "readable": d.readable}
    except Exception as e:  # one bad file must not stop the run
        rec = {"file_id": path.stem, "type": kind, "description": f"[not described: {type(e).__name__}]", "readable": False}
    out.write_text(json.dumps(rec, ensure_ascii=False))
    return rec
