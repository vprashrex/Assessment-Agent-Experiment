"""Run configuration: one object shared by the CLI, the Python API and the MCP server."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "gpt-6.1-sol"


@dataclass
class RunConfig:
    """Everything a run needs. Paths may be relative to the current directory.

    sheet      spreadsheet with the submissions and the reference judgements
    context    operator notes: which columns are input, which is the reference, answers to parser questions
    prompt     the prompt in use today (v0)
    run        run folder; rerunning with the same folder resumes
    schema     optional output schema (JSON file)
    docs_dir   folder of downloaded files for links that cannot be fetched (matched by name)
    model      parser, judge and generator; `scorer` defaults to it
    effort     reasoning effort; `mode` is the OpenAI reasoning mode (standard | pro)
    rounds     ceiling on rounds; `patience` stops after that many rejected rounds in a row; `target` stops at that MAE
    n          use only the first n items
    """
    sheet: str
    context: str
    prompt: str
    run: str
    schema: str | None = None
    sheet_name: str | None = None
    docs_dir: str | None = None
    model: str = DEFAULT_MODEL
    effort: str = "high"
    mode: str = "standard"
    scorer: str | None = None
    rounds: int = 8
    patience: int = 4
    target: float | None = None
    n: int | None = None
    workers: int = 8
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.scorer = self.scorer or self.model
        missing = [f"{k}: {v}" for k, v in (("sheet", self.sheet), ("context", self.context), ("prompt", self.prompt),
                                             ("schema", self.schema), ("docs_dir", self.docs_dir)) if v and not Path(v).exists()]
        if missing:
            raise FileNotFoundError("Not found — " + "; ".join(missing))
        if self.mode not in ("standard", "pro"):
            raise ValueError("mode must be 'standard' or 'pro'")

    def args(self) -> list[str]:
        """The same run as command-line arguments for `python -m refiner`."""
        out = []
        for k, v in asdict(self).items():
            if k == "extra" or v is None:
                continue
            out += [f"--{k.replace('_', '-')}", str(v)]
        return out
