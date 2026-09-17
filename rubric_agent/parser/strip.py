from __future__ import annotations

from pathlib import Path

from ..core import llm
from ..core.config import PARSER, prompt
from ..core.state import Stripped


def strip(prompt_path: Path, out_path: Path) -> Stripped:
    out, _ = llm.call(PARSER, prompt("parser_strip"), f"MATURE RUBRIC PROMPT:\n<<<\n{prompt_path.read_text()}\n>>>",
                      Stripped, role="strip", effort="high")
    out_path.write_text(out.rubric_md)
    return out
