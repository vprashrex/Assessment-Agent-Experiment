"""Parser duty 1: decide which columns make up a submission (operator-named, else inferred from the data)."""

from __future__ import annotations

import json

import pandas as pd

from ..core import llm
from ..core.config import prompt
from ..core.state import ColumnPlan
from .sheet import cell


def plan_columns(df: pd.DataFrame, context: str, model: str) -> ColumnPlan:
    sample = [{k: (str(v)[:160] if cell(v) is not None else None) for k, v in r.items()} for r in df.head(3).to_dict("records")]
    user = f"OPERATOR CONTEXT:\n{context}\n\nCOLUMNS: {list(df.columns)}\n\nSAMPLE ROWS:\n{json.dumps(sample, ensure_ascii=False, indent=1)}"
    plan, _ = llm.call(model, prompt("parser_columns"), user, ColumnPlan, role="parser", effort="medium")
    missing = [c for c in plan.use + ([plan.id_column] if plan.id_column else []) if c not in df.columns]
    if missing:
        plan.unresolved.append(f"Columns {missing} do not exist; the sheet has {list(df.columns)}.")
    if not plan.use and not plan.unresolved:
        plan.unresolved.append("No columns selected. Which columns hold the submission?")
    return plan
