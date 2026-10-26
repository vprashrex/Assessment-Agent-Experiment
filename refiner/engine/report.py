"""report.json: the run's final artifact, built only from the run folder (numbers from math_tool, never typed).

{"meta":    {chat_id, created, task, models, effort, items, metrics: [{key, field, type, min, max, values}],
             rounds: {key: int}, stopped: {key: reason}},
 "kpis":    {key: {before: numbers, after: numbers}},     before = v0; after = composed final (several metrics) or best
 "lineage": {key: [{version, parent, verdict, round, numbers}]},
 "rubrics": {key: {version: metric section text}},
 "final_rubric": str}
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .. import agents
from ..agents import math_tool as M
from ..utils.files import read
from . import events


def _metric_dirs(run_dir: Path, setup: dict) -> dict[str, Path]:
    """Where each metric's versions live: metrics/<key>/ with several metrics, the run folder itself with one."""
    ms = agents.metrics_of(setup)
    return {m["key"]: run_dir / "metrics" / m["key"] for m in ms} if len(ms) > 1 else {ms[0]["key"]: run_dir}


def lineage(metric_dir: Path, out: dict) -> list[dict]:
    """Every version of one metric: parent, verdict, round and its numbers against the reference."""
    st = read(metric_dir / "state.json") or {}
    items = read(metric_dir / "setup/items.json") or []
    refs = {it["id"]: v for it in items if (v := agents.reference(it.get("truth"), out)) is not None}
    rows = []
    for v in st.get("versions", ["v0"]):
        c = st.get("changes", {}).get(v, {})
        sc = read(metric_dir / f"versions/{v}/scores.json")
        rows.append({"version": v, "parent": c.get("parent"), "round": int(v[1:]),
                     "verdict": "baseline" if v == "v0" else (c.get("verdict") or "testing").lower(),
                     "numbers": M.summary(M.item_errors(sc, refs, out["type"]), out["type"]) if sc is not None else {"n": 0}})
    return rows


def section(metric_dir: Path, version: str) -> str | None:
    """The editable metric section of one version, as text."""
    chunks = read(metric_dir / f"versions/{version}/chunks.json")
    if chunks is None:
        return None
    return "".join(c["text"] for c in chunks if c["layer"] == agents.EDITABLE)


def build(run_dir: Path, a=None) -> dict:
    run_dir = Path(run_dir)
    setup = read(run_dir / "setup/setup.json")
    items = read(run_dir / "setup/items.json") or []
    ms = agents.metrics_of(setup)
    dirs = _metric_dirs(run_dir, setup)
    outs = {m["key"]: m["output"] for m in ms}
    stopped = {e["metric"]: e["data"].get("reason") for e in events.read(run_dir) if e["type"] == "metric.stopped"}
    lin = {k: lineage(d, outs[k]) for k, d in dirs.items()}
    states = {k: read(d / "state.json") or {} for k, d in dirs.items()}
    if len(ms) > 1:
        together = (read(run_dir / "composed.json") or {}).get("together", {})
        kpis = {k: {"before": together.get("baseline", {}).get(k, {}), "after": together.get("final", {}).get(k, {})} for k in outs}
    else:
        k = ms[0]["key"]
        by_v = {r["version"]: r["numbers"] for r in lin[k]}
        kpis = {k: {"before": by_v.get("v0", {}), "after": by_v.get(states[k].get("best", "v0"), {})}}
    models = ({"parser": a.parser_model, "judge": a.judge_model, "generator": a.generator_model, "scorer": a.scorer}
              if a is not None else {})
    chat_id = run_dir.parent.name if run_dir.name == "run" else run_dir.name
    return {
        "meta": {"chat_id": chat_id, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "task": "refine",
                 "models": models, "effort": getattr(a, "effort", None), "items": len(items),
                 "metrics": [{"key": m["key"], "field": m["output"]["field"], "type": m["output"]["type"],
                              "min": m["output"].get("min"), "max": m["output"].get("max"), "values": m["output"].get("values")}
                             for m in ms],
                 "rounds": {k: st.get("round", 0) for k, st in states.items()}, "stopped": stopped},
        "kpis": kpis,
        "lineage": lin,
        "rubrics": {k: {r["version"]: section(d, r["version"]) or "" for r in lin[k]} for k, d in dirs.items()},
        "final_rubric": read(run_dir / "final_prompt.md", ""),
    }


def write(run, a, setup: dict, items: list[dict]) -> dict:
    """Build report.json in the run folder and announce it."""
    rep = build(run.dir, a)
    (run.dir / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    events.emit(run.dir, "report.ready", report="report.json", final_rubric="final_prompt.md", results="results.xlsx")
    return rep
