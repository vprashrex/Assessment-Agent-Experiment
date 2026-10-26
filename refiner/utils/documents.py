"""Text out of files: Word documents (with their embedded images), web pages, and a downloaded file's type."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}


def extension(data: bytes, ctype: str) -> str:
    """The file extension for downloaded bytes, from their first bytes (or the content type for text)."""
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


def html_text(data: bytes) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(data, "html.parser")
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "noscript"]):
        t.decompose()
    text = (soup.find("article") or soup.find("main") or soup.body or soup).get_text("\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:40_000]


def docx(path: Path) -> tuple[str, list[Path]]:
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
