from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from .state import Setup


class Run:
    def __init__(self, run_dir: str):
        self.dir = Path(run_dir)
        self._setup: Setup | None = None
        self._rows: dict[str, dict[str, Any]] | None = None

    @property
    def setup(self) -> Setup:
        if self._setup is None:
            self._setup = Setup.model_validate_json((self.dir / "setup.json").read_text())
        return self._setup

    @property
    def rows(self) -> dict[str, dict[str, Any]]:
        if self._rows is None:
            self._rows = {r["cid"]: r for r in json.loads((self.dir / "submissions.json").read_text())}
        return self._rows

    @property
    def metrics(self) -> list[str]:
        return [m.name for m in self.setup.metrics]

    @property
    def scale(self) -> tuple[int, int]:
        m = self.setup.metrics[0]
        return m.min, m.max

    def text(self, name: str) -> str:
        p = self.dir / name
        return p.read_text() if p.exists() else ""

    def json(self, name: str, default: Any) -> Any:
        p = self.dir / name
        return json.loads(p.read_text()) if p.exists() else default

    def write(self, name: str, data: Any) -> None:
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1))

    def append(self, name: str, text: str) -> None:
        with (self.dir / name).open("a") as f:
            f.write(text.rstrip() + "\n")

    def rubric(self, version: str) -> str:
        return self.text(f"rubric/{version}.md")

    def sample(self, n: int | None) -> list[str]:
        cids = [c for c in self.rows if self.rows[c]["fields"]]
        if not n or n >= len(cids):
            return cids
        return random.Random("sample").sample(cids, k=n)
