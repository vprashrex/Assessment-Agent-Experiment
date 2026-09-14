"""Scorer: a plain API call, repeated k times per row. Rubric as system prompt, one submission as user,
schema-enforced JSON. No tools, no memory. The k runs are the consistency measurement."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..core import llm
from ..core.config import MODELS, SCORER_EFFORT, WORKERS
from ..core.runio import Run
from ..core.state import get_path
from ..parser import scores_from, submission_text


def _has(obj: Any, path: str) -> bool:
    try:
        get_path(obj, path)
        return True
    except KeyError:
        return False


def _one(run: Run, rubric_md: str, cid: str) -> dict[str, Any]:
    setup = run.setup
    try:
        raw, _ = llm.call(MODELS["scorer"], rubric_md, submission_text(run.rows[cid]) + "\n\nReturn the JSON object exactly as specified.",
                          setup.score_schema, role="scorer", effort=SCORER_EFFORT, retries=0)
    except Exception as e:
        return {"scores": None, "reasons": {}, "error": f"{type(e).__name__}: {e}"[:200]}
    scores = scores_from(raw, setup.metrics)
    reasons = {m.name: (get_path(raw, m.reason_path) if m.reason_path else "") for m in setup.metrics
               if not m.reason_path or _has(raw, m.reason_path)}
    return {"scores": scores, "reasons": reasons, "error": None if scores else "schema/range failure"}


def score_rows(run: Run, rubric_md: str, cids: list[str], k: int) -> dict[str, dict[str, Any]]:
    """{cid: {"runs": [run, ...]}} with k runs per row. A failed run has scores=None and is kept (it counts)."""
    jobs = [(c, i) for c in cids for i in range(k)]
    with ThreadPoolExecutor(WORKERS) as ex:
        results = list(ex.map(lambda j: (j[0], _one(run, rubric_md, j[0])), jobs))
    out: dict[str, dict[str, Any]] = {c: {"runs": []} for c in cids}
    for c, r in results:
        out[c]["runs"].append(r)
    return out
