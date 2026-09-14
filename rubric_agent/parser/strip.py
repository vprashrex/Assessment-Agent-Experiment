"""Make an under-specified starting rubric (v0) from a mature one, so a run tests refinement, not polishing."""

from __future__ import annotations

from pathlib import Path

from ..core import llm
from ..core.config import MODELS, prompt
from ..core.state import Stripped


def strip(prompt_path: Path, out_path: Path) -> Stripped:
    out, _ = llm.call(MODELS["parser"], prompt("parser_strip"), f"MATURE RUBRIC PROMPT:\n<<<\n{prompt_path.read_text()}\n>>>",
                      Stripped, role="strip", effort="high")
    out_path.write_text(out.rubric_md)
    return out
