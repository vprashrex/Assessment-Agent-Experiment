from __future__ import annotations

import json
import os
from pathlib import Path

GENERATOR = os.getenv("RUBRIC_GENERATOR", "claude-opus-5")
PARSER = os.getenv("RUBRIC_PARSER", "claude-opus-5")
DESCRIBE = os.getenv("RUBRIC_DESCRIBE", "claude-sonnet-5")
SCORER = os.getenv("RUBRIC_SCORER", "google_genai:gemini-3.1-flash-lite-preview")
SCORER_PARAMS: dict = json.loads(os.getenv("RUBRIC_SCORER_PARAMS", "{}"))

K = int(os.getenv("RUBRIC_K", "4"))
K_ASSURE = int(os.getenv("RUBRIC_K_ASSURE", str(K)))
WORKERS = int(os.getenv("RUBRIC_WORKERS", "16"))
STABLE_RANGE = 1
SEVERE_RANGE = 2
FAIL_RATE_MAX = 0.3
COLLAPSE_DROP = 0.05
FAIL_STREAK = 4
LEN_BUDGET = 1.5
FOCUS_ROWS = 15

ROOT = Path(__file__).resolve().parents[2]
PRINCIPLES = ROOT / "memory" / "principles.md"
ATTACH_CACHE = Path(os.getenv("RUBRIC_ATTACH_CACHE", ROOT / "cache" / "attachments"))
PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text()
