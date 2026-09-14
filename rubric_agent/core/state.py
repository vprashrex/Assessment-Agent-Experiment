"""Graph state and structured-output models. Nothing here knows the org's columns or metrics:
columns come from the sheet + operator text, metrics from the operator's output schema."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Parser -----------------------------------------------------------------------


class ColumnPlan(Strict):
    """Which columns of the sheet make up a submission. Empty `unresolved` = proceed."""

    use: list[str]
    id_column: str | None
    unresolved: list[str]


class MetricSpec(Strict):
    """One scored dimension, located inside the operator's output schema by dot-path."""

    name: str
    score_path: str
    reason_path: str | None
    min: int
    max: int


class Constitution(Strict):
    """setup.md text for judge + generator, and where the scores live in the output schema."""

    setup_md: str
    metrics: list[MetricSpec]


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


# --- Judge: quality assurance over k-run scores, batch-wise -----------------------------


class RowVerdict(Strict):
    cid: str
    metric: str
    agree: bool
    issue: Literal["none", "unstable", "too_high", "too_low", "reason_unsupported"] = "none"
    comment: str = ""


class MetricRank(Strict):
    metric: str
    order: list[str] = []  # cids best -> worst within the batch


class Review(Strict):
    rows: list[RowVerdict] = []
    ranks: list[MetricRank] = []
    patterns: list[str] = []
    summary: str = ""


# --- Judge: flow control -------------------------------------------------------------


class Decision(Strict):
    decision: Literal["continue", "success", "fail"]
    reason: str


# --- Generator ------------------------------------------------------------------------


class GenOut(Strict):
    rubric_md: str
    n_random: int
    change_summary: str
    hypothesis: str
    converged: bool
    converged_reason: str


class Reflection(Strict):
    guide_md: str
    principles: list[str]


# --- Graph state (small; heavy artefacts live under run_dir) -----------------------------


class RunState(TypedDict, total=False):
    run_dir: str
    context: str
    sheet_path: str
    prompt_path: str
    constitution_path: str
    schema_path: str
    operator_answers: list[str]
    needs_input: list[str]
    review: bool
    max_attachments: int | None
    k_full: bool

    round: int
    max_rounds: int
    best: str
    best_round: int
    candidate: str
    sample: list[str]
    carry: list[str]
    carry_count: dict[str, int]
    consecutive_fail: int
    ledger: list[str]
    n_random: int
    converged: bool
    stop: bool
    stop_reason: str
    decision: str
    comments: str
    resume_loop: bool


def get_path(obj: Any, path: str) -> Any:
    """Read a dot-path like 'X_score' or 'X.score' from a parsed JSON object."""
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(path)
        cur = cur[part]
    return cur
