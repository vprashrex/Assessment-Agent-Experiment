"""Run configuration: one object shared by the CLI, the Python API and the MCP server. `DEFAULTS` and `HELP` are
the single source for every surface's defaults and option text (the CLI builds its flags from them)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .agents.models import catalog
from .engine.split import shares

EFFORTS = ("low", "medium", "high")  # the refiner's one reasoning knob; models.py maps it to each model's setting
DEFAULT_MODEL: str = (catalog().get("defaults") or {}).get("judge") or "claude-sonnet-5-5"


def decision_scorers() -> list[str]:
    """The decision models of models.yaml (completion_type `decision`): an alternative scorer, no prose, probabilities."""
    return [m["model_name"] for m in catalog().get("models") or [] if "decision" in (m.get("completion_type") or [])]


@dataclass
class RunConfig:
    """Everything a run needs. Paths may be relative to the current directory. Option text is in HELP below."""
    sheet: str
    prompt: str
    run: str
    context: str | None = None
    schema: str | None = None
    sheet_name: str | None = None
    docs_dir: str | None = None
    model: str = DEFAULT_MODEL
    effort: str = "high"
    scorer: str | None = None
    scorer_effort: str | None = None
    parser_model: str | None = None
    judge_model: str | None = None
    generator_model: str | None = None
    rounds: int = 8
    patience: int = 4
    target: float | None = None
    n: int | None = None
    split: str = "80/20"
    seed: int = 0
    budget: float | None = None
    workers: int = 24

    def __post_init__(self) -> None:
        self.scorer = self.scorer or self.model  # the model production scores with: generative, or a decision model
        self.scorer_effort = self.scorer_effort or "low"  # production scorers run lean; a decision model ignores it
        self.parser_model = self.parser_model or self.model
        self.judge_model = self.judge_model or self.model
        self.generator_model = self.generator_model or self.model
        missing = [f"{k}: {v}" for k, v in (("sheet", self.sheet), ("context", self.context), ("prompt", self.prompt),
                                             ("schema", self.schema), ("docs_dir", self.docs_dir)) if v and not Path(v).exists()]
        if missing:
            raise FileNotFoundError("Not found — " + "; ".join(missing))
        for name in ("effort", "scorer_effort"):
            if getattr(self, name) not in EFFORTS:
                raise ValueError(f"{name} must be one of {', '.join(EFFORTS)}")
        shares(self.split)  # raises on a bad spec
        if self.budget is not None and self.budget <= 0:
            raise ValueError("budget must be a positive amount in USD")

    def run_models(self) -> dict[str, str]:
        """The models and effort a refinement runs with; locked once it starts (see api.lock_models)."""
        return {"parser": self.parser_model, "judge": self.judge_model, "generator": self.generator_model,
                "scorer": self.scorer, "effort": self.effort, "scorer_effort": self.scorer_effort}

    def args(self) -> list[str]:
        """The same run as command-line arguments for `python -m refiner`."""
        out = []
        for k, v in asdict(self).items():
            if v is None:
                continue
            out += [f"--{k.replace('_', '-')}", str(v)]
        return out


REQUIRED = ("sheet", "prompt", "run")
DEFAULTS: dict = {f.name: f.default for f in fields(RunConfig) if f.name not in REQUIRED}

HELP: dict[str, str] = {
    "sheet": "spreadsheet with the submissions and the reference judgements",
    "sheet_name": "which sheet of the workbook (default: the first)",
    "context": "optional operator notes: which columns are input, which is the reference, answers to parser questions",
    "prompt": "the prompt in use today (v0)",
    "run": "run folder; rerunning with the same folder resumes",
    "schema": "optional output schema (JSON file)",
    "docs_dir": "folder of downloaded files for links that cannot be fetched (matched by name)",
    "model": "default model for every agent; the per-agent options override it",
    "effort": f"reasoning effort for every model: {' | '.join(EFFORTS)}",
    "scorer": "scoring model, the one production uses: generative (default: --model) or a decision model (gpt-6-luna-decisions, gemini-decision-1)",
    "scorer_effort": "effort for the scorer alone (default low: production scorers run lean; ignored by decision models)",
    "parser_model": "parser model (default: --model)",
    "judge_model": "judge model (default: --model)",
    "generator_model": "generator model (default: --model)",
    "rounds": "ceiling on rounds per metric",
    "patience": "stop after this many rejected rounds in a row",
    "target": "stop when the MAE (or miss rate) on train reaches this",
    "n": "use only the first N items; fixed when the run is prepared, a different value on resume is ignored",
    "split": "train/test share, like 80/20; the rubric is tuned on train only and test is scored once at the end "
             "(100/0 = no holdout). Fixed when the run is prepared",
    "seed": "which items go to train and test; fixed when the run is prepared",
    "budget": "USD: stop at the next round boundary once this much is spent (best version kept); no model call "
              "starts above 1.25 × budget. Prices come from models.yaml; an unpriced model counts as $0",
    "workers": "parallel model calls (network-bound; a laptop handles the default)",
}
