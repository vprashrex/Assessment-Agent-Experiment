"""Run-directory I/O. Everything heavy lives in files under runs/<name>/; graph state stays small."""

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

    def pool(self) -> set[str]:
        return set(self.json("example_pool.json", []))

    def draw(self, k: int, exclude: set[str], seed: str) -> list[str]:
        """Seeded random sample of row ids with content, excluding the given ids."""
        return self.draw_from(list(self.rows), k, exclude, seed)

    def draw_from(self, cids: list[str], k: int, exclude: set[str], seed: str) -> list[str]:
        pool = [c for c in cids if c not in exclude and self.rows[c]["fields"]]
        return random.Random(seed).sample(pool, k=min(k, len(pool)))
