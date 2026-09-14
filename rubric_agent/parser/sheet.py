"""Spreadsheet cleaning and cell helpers. No LLM calls, no knowledge of any particular sheet."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


def pick_sheet(path: Path, context: str) -> str:
    """The sheet the operator names in the context, else the one with the most non-empty cells."""
    xls = pd.ExcelFile(path)
    named = [s for s in xls.sheet_names if re.search(rf"(?<!\w){re.escape(s)}(?!\w)", context)]
    return named[0] if named else max(xls.sheet_names, key=lambda s: xls.parse(s).count().sum())


def clean_sheet(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Drop empty rows/columns and unnamed columns, strip whitespace, blank strings -> None."""
    stats = {"rows_in": len(df), "cols_in": len(df.columns)}
    df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")
    df = df[[c for c in df.columns if not (str(c).startswith("Unnamed") or str(c) in ("None", "nan"))]]
    df.columns = [str(c).strip() for c in df.columns]
    df = df.map(lambda v: v.strip() if isinstance(v, str) else v).replace({"": None}).dropna(axis=0, how="all")
    stats.update(rows_out=len(df), cols_out=len(df.columns))
    return df.reset_index(drop=True), stats


def cell(v: Any) -> Any:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, float) and v == int(v):
        return int(v)
    return v


def links_in(v: Any) -> list[str]:
    return [t for t in re.split(r"[,\s]+", v) if t.startswith("http")] if isinstance(v, str) else []


def is_link_column(series: pd.Series) -> bool:
    vals = [v for v in series if isinstance(v, str)]
    return bool(vals) and sum(1 for v in vals if links_in(v)) >= 0.3 * len(vals)


def load_schema(path: Path) -> dict[str, Any]:
    """The operator's output schema: a JSON file, or JSON inside a ``` fence in a Markdown file."""
    text = path.read_text()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    return json.loads(m.group(1) if m else text)
