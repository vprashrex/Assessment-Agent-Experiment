"""k stateless scorer sub-agents per submission, run in parallel."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..core.config import WORKERS
from ..core.runio import Run
from ..core.state import get_path
from ..parser import scores_from, submission_text
from .provider import score_one


def _run(run: Run, rubric: str, cid: str) -> dict[str, Any]:
    setup = run.setup
    try:
        raw = score_one(rubric, submission_text(run.rows[cid]), setup.score_schema)
    except Exception as e:
        return {"scores": None, "reasons": {}, "error": f"{type(e).__name__}: {e}"[:200]}
    scores = scores_from(raw, setup.metrics)
    reasons = {}
    for m in setup.metrics:
        try:
            reasons[m.name] = get_path(raw, m.reason_path) if m.reason_path else ""
        except KeyError:
            reasons[m.name] = ""
    return {"scores": scores, "reasons": reasons, "error": None if scores else "schema/range failure"}


def score_rows(run: Run, rubric: str, cids: list[str], k: int) -> dict[str, dict[str, Any]]:
    jobs = [(c, i) for c in cids for i in range(k)]
    with ThreadPoolExecutor(WORKERS) as ex:
        results = list(ex.map(lambda j: (j[0], _run(run, rubric, j[0])), jobs))
    out: dict[str, dict[str, Any]] = {c: {"runs": []} for c in cids}
    for c, r in results:
        out[c]["runs"].append(r)
    return out
