from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ColumnPlan(Strict):
    use: list[str]
    id_column: str | None
    unresolved: list[str]


class MetricSpec(Strict):
    name: str
    score_path: str
    reason_path: str | None
    min: int
    max: int


class Constitution(Strict):
    setup_md: str


class SchemaProposal(Strict):
    schema_text: str
    questions: list[str]


class Description(Strict):
    description: str
    readable: bool


class Setup(Strict):
    metrics: list[MetricSpec]
    score_schema: dict[str, Any]
    columns: ColumnPlan
    n_rows: int


class Stripped(Strict):
    rubric_md: str
    removed: list[str]


class Design(Strict):
    rubric_md: str
    notes: str


class GenOut(Strict):
    rubric_md: str
    change_summary: str
    hypothesis: str


class Assessment(Strict):
    consistent: bool
    next_action: Literal["revise", "assure", "stop"]
    notes: str
    focus_rows: list[str] = []


class Reflection(Strict):
    guide_md: str
    principles: list[str]


class RunState(TypedDict, total=False):
    run_dir: str
    context: str
    sheet_path: str
    prompt_path: str
    schema_path: str
    operator_answers: list[str]
    needs_input: list[str]
    review: bool
    max_attachments: int | None
    n: int

    round: int
    max_rounds: int
    best: str
    best_round: int
    candidate: str
    mode: Literal["revise", "assure"]
    sample: list[str]
    consecutive_fail: int
    baseline_icc: float
    ledger: list[str]
    stop: bool
    stop_reason: str
    comments: str
    resume_loop: bool


def get_path(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(path)
        cur = cur[part]
    return cur
