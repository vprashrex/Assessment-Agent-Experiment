"""report.json: the run's final artifact, built only from the run folder (numbers from math_tool, never typed).

{"meta":    {chat_id, created, task, models, effort, items, split: {spec, seed, train, test},
             metrics: [{key, field, type, min, max, values}], rounds: {key: int}, stopped: {key: reason}},
 "kpis":    {key: {before: numbers, after: numbers, test: {before, after}}},
             before = v0; after = composed final (several metrics) or best; numbers are on the train items,
             `test` the same prompts on the held-out items (absent when the run has no holdout or has not finished)
 "lineage": {key: [{version, parent, verdict, round, numbers, test?}]},     numbers on train; test where scored
 "rubrics": {key: {version: metric section text}},
 "final_rubric": str}
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .. import agents
from ..agents import math_tool as M
from ..agents import spend
from ..utils.files import read
from . import events, split


def metric_dirs(run_dir: Path, setup: dict) -> dict[str, Path]:
    """Where each metric's versions live: metrics/<key>/ with several metrics, the run folder itself with one."""
    ms = agents.metrics_of(setup)
    return {m["key"]: run_dir / "metrics" / m["key"] for m in ms} if len(ms) > 1 else {ms[0]["key"]: run_dir}


def lineage(metric_dir: Path, out: dict, kind: str | None = None) -> list[dict]:
    """Every version of one metric: parent, verdict, round and its numbers against the reference."""
    kind = kind or out["type"]
    st = read(metric_dir / "state.json") or {}
    items = read(metric_dir / "setup/items.json") or []
    refs = {it["id"]: v for it in items if (v := agents.reference(it.get("truth"), out)) is not None}
    sp = read(metric_dir / split.FILE) or {"train": list(refs), "test": []}
    refs_train, refs_test = split.filter_refs(refs, sp["train"]), split.filter_refs(refs, sp["test"])
    rows = []
    for v in st.get("versions", ["v0"]):
        c = st.get("changes", {}).get(v, {})
        sc, sct = read(metric_dir / f"versions/{v}/scores.json"), read(metric_dir / f"versions/{v}/scores_test.json")
        rows.append({"version": v, "parent": c.get("parent"),
                     "round": int(v[1:]) if v[1:].isdigit() else len(st.get("versions", [])) - 1,  # vS: the simplify pass
                     "verdict": "baseline" if v == "v0" else (c.get("verdict") or "testing").lower(),
                     "numbers": M.summary(M.item_errors(sc, refs_train, kind), kind) if sc is not None else {"n": 0},
                     **({"test": M.summary(M.item_errors(sct, refs_test, kind), kind)} if sct is not None and refs_test else {})})
    return rows


def section(metric_dir: Path, version: str, layers: tuple[str, ...] = (agents.EDITABLE,)) -> str | None:
    """The editable section of one version, as text (the metric layer, or the layers a stage edits)."""
    chunks = read(metric_dir / f"versions/{version}/chunks.json")
    if chunks is None:
        return None
    return "".join(c["text"] for c in chunks if c["layer"] in layers)


def build(run_dir: Path, a=None) -> dict:
    run_dir = Path(run_dir)
    setup = read(run_dir / "setup/setup.json")
    items = read(run_dir / "setup/items.json") or []
    ms = agents.metrics_of(setup)
    dirs = metric_dirs(run_dir, setup)
    outs = {m["key"]: m["output"] for m in ms}
    stopped = {e["metric"]: e["data"].get("reason") for e in events.read(run_dir) if e["type"] == "metric.stopped"}
    kind = "verdict" if setup.get("feedback") else None  # feedback mode: numbers measure verdict satisfaction (per-output type otherwise)
    lin = {k: lineage(d, outs[k], kind) for k, d in dirs.items()}
    states = {k: read(d / "state.json") or {} for k, d in dirs.items()}
    if len(ms) > 1:
        composed = read(run_dir / "composed.json") or {}
        together, tt = composed.get("together", {}), composed.get("together_test")
        kpis = {k: {"before": together.get("baseline", {}).get(k, {}), "after": together.get("final", {}).get(k, {}),
                    **({"test": {"before": tt["baseline"][k], "after": tt["final"][k]}} if tt else {})} for k in outs}
    else:
        k = ms[0]["key"]
        best = states[k].get("best", "v0")
        by_v = {r["version"]: r["numbers"] for r in lin[k]}
        by_t = {r["version"]: r["test"] for r in lin[k] if "test" in r}
        kpis = {k: {"before": by_v.get("v0", {}), "after": by_v.get(best, {}),
                    **({"test": {"before": by_t["v0"], "after": by_t[best]}} if "v0" in by_t and best in by_t else {})}}
    sp = read(run_dir / split.FILE) or {}
    models = ({"parser": a.parser_model, "judge": a.judge_model, "generator": a.generator_model, "scorer": a.scorer}
              if a is not None else {})
    chat_id = run_dir.parent.name if run_dir.name == "run" else run_dir.name
    return {
        "meta": {"chat_id": chat_id, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "task": "refine",
                 "models": models, "effort": getattr(a, "effort", None), "items": len(items),
                 "split": {"spec": sp.get("spec"), "seed": sp.get("seed"), "train": len(sp.get("train", items)), "test": len(sp.get("test", []))},
                 "spent": spend.read(run_dir),
                 "metrics": [{"key": m["key"], "field": m["output"]["field"], "type": m["output"]["type"],
                              "min": m["output"].get("min"), "max": m["output"].get("max"), "values": m["output"].get("values")}
                             for m in ms],
                 "rounds": {k: st.get("round", 0) for k, st in states.items()}, "stopped": stopped},
        "kpis": kpis,
        "lineage": lin,
        "rubrics": {k: {r["version"]: section(d, r["version"]) or "" for r in lin[k]} for k, d in dirs.items()},
        "final_rubric": read(run_dir / "final_prompt.md", ""),
    }


def write(run, a, setup: dict | None = None, items: list[dict] | None = None) -> dict:
    """Build report.json in the run folder and announce it. (`setup` and `items` are read from the run folder.)"""
    rep = build(run.dir, a)
    (run.dir / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    events.emit(run.dir, "report.ready", report="report.json", final_rubric="final_prompt.md", results="results.xlsx")
    return rep
