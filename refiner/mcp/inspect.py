"""What the Chat Agent and the UI see of a chat's uploads: the file list, a preview of each file judged by its content
(never its name), and a file's opening lines for naming the chat."""

from __future__ import annotations

from pathlib import Path

from refiner import paths
from refiner.utils.files import IMAGE_MIME


def inputs(chat_id: str) -> dict:
    d = paths.inputs_dir(chat_id)
    return {"files": [{"name": p.name, "size": p.stat().st_size, "folder": p.is_dir()} for p in sorted(d.iterdir())
                      if not p.name.startswith(".")] if d.exists() else []}


def peek(p: Path) -> dict:
    """What one uploaded file contains, judged by its content, never by its name."""
    import pandas as pd
    from refiner.utils.documents import docx
    from refiner.utils.excel import read_sheet

    ext = p.suffix.lower()
    out: dict = {"name": p.name, "size": p.stat().st_size}
    if p.is_dir():
        files = sorted(x for x in p.rglob("*") if x.is_file())
        return {**out, "kind": "folder", "files": len(files), "examples": [x.name for x in files[:8]]}
    try:
        if ext in (".xlsx", ".xls", ".xlsm", ".csv", ".tsv"):
            sheets = ["(csv)"] if ext in (".csv", ".tsv") else pd.ExcelFile(p).sheet_names
            df = read_sheet(p)
            short = lambda v: "" if pd.isna(v) else (str(v) if len(str(v)) <= 160 else str(v)[:160] + "…")  # noqa: E731
            head = df.head(8).map(short)
            return {**out, "kind": "table", "sheets": sheets, "rows": len(df), "columns": list(map(str, df.columns)),
                    "first_rows": head.to_dict("records")}
        if ext == ".json":
            text = p.read_text(errors="ignore")
            return {**out, "kind": "json", "content": text[:6000], "truncated": len(text) > 6000}
        if ext == ".docx":
            text, _ = docx(p)
            return {**out, "kind": "document", "content": text[:6000], "truncated": len(text) > 6000}
        if ext == ".pdf":
            try:
                from pypdf import PdfReader

                r = PdfReader(str(p))
                text = "\n".join((pg.extract_text() or "") for pg in r.pages[:3])
                return {**out, "kind": "pdf", "pages": len(r.pages), "content": text[:4000]}
            except Exception:
                return {**out, "kind": "pdf"}
        if ext in IMAGE_MIME:
            return {**out, "kind": "image"}
        text = p.read_text(errors="ignore")
        return {**out, "kind": "text", "content": text[:6000], "truncated": len(text) > 6000}
    except Exception as e:  # unreadable: say so, the agent asks the user
        return {**out, "kind": "unreadable", "error": f"{type(e).__name__}: {e}"[:200]}


def opening(p: Path) -> str:
    """The start of a file, for naming the chat: a text file's first lines, a CSV's header row."""
    ext = p.suffix.lower()
    try:
        if ext in (".md", ".txt", ".json"):
            return p.read_text(errors="ignore")[:1500]
        if ext == ".csv":
            return p.read_text(errors="ignore").split("\n", 1)[0][:400]
    except OSError:
        pass
    return ""
