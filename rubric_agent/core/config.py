"""Models, knobs and the prompt loader. All overridable by environment variables."""

from __future__ import annotations

import os
from pathlib import Path

MODELS = {
    "scorer": os.getenv("RUBRIC_SCORER", "claude-sonnet-5"),
    "judge": os.getenv("RUBRIC_JUDGE", "claude-fable-5-1"),
    "judge_fallback": os.getenv("RUBRIC_JUDGE_FALLBACK", "claude-opus-5"),
    "generator": os.getenv("RUBRIC_GENERATOR", "claude-opus-5"),
    "parser": os.getenv("RUBRIC_PARSER", "claude-opus-5"),
    "describe": os.getenv("RUBRIC_DESCRIBE", "claude-sonnet-5"),
}
SCORER_EFFORT = os.getenv("RUBRIC_SCORER_EFFORT", "medium")
WORKERS = int(os.getenv("RUBRIC_WORKERS", "8"))

K_RUNS = int(os.getenv("RUBRIC_K", "4"))            # repeated scorer runs per row inside the loop (consistency)
K_FULL = int(os.getenv("RUBRIC_K_FULL", "30"))      # repeats for the deep baseline / final measurement
N_MAX = int(os.getenv("RUBRIC_N_MAX", "150"))       # ceiling on the Generator's per-round train sample
TRAIN_N = int(os.getenv("RUBRIC_TRAIN", "140"))     # rows the loop may tune on
TEST_N = int(os.getenv("RUBRIC_TEST", "60"))        # held-out rows: every KEPT version is confirmed here
BATCH = int(os.getenv("RUBRIC_BATCH", "8"))         # submissions per Judge review call (comparative context)
CARRY_CAP, CARRY_RETIRE = 20, 2                     # unstable/disagreed rows carried into the next round; retire after 2
LEN_BUDGET, POOL_SHOW = 1.3, 6                      # rubric length ceiling (× v0); example-pool rows shown per round

ROOT = Path(__file__).resolve().parents[2]
PRINCIPLES = ROOT / "memory" / "principles.md"
PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text()
