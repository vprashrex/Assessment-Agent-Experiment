"""Python API. The CLI and the MCP server are thin wrappers over these functions.

    from refiner import RunConfig, prepare, refine, start, status

    cfg = RunConfig(sheet="data/s.xlsx", context="data/c.md", prompt="data/v0.md", run="runs/x")
    prepare(cfg)     # parser + layer split + attachments, no scoring; returns questions if anything is unclear
    refine(cfg)      # the whole loop in this process (blocks until it stops)
    start(cfg)       # the whole loop in a background process; poll with status(cfg.run)
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
from typing import Any

from .agents import math_tool as M
from .agents import metrics_of, reference
from .config import RunConfig
from .engine import events, loop
from .engine import report as rpt
from .engine.loop import NeedsAnswers, Run
from .utils import process
from .utils.files import read


def prepare(cfg: RunConfig) -> dict:
    """Run the parser, cut the prompt into layers and collect every submission with its attachments. No scoring.
    Returns the setup to review, or `questions` the operator must answer in the context file before starting."""
    run = Run(Path(cfg.run))
    try:
        setup, items = loop.setup_run(run, cfg)
    except NeedsAnswers as e:
        res = {"run": str(run.dir), "ready": False, "questions": e.questions}
        run.write("prepare.json", res)
        events.emit(run.dir, "setup.questions", questions=e.questions)
        return res
    chunks = run.read("setup/baseline/layout.json")
    problems = [ln[len("setup: "):] for ln in run.read("debug.txt", "").splitlines() if ln.startswith("setup: ")]
    res = {"run": str(run.dir), "ready": True, "questions": [],
            "columns": {"id": setup["id_column"], "inputs": setup["input_columns"]},
            "metrics": [{"key": m["key"], "reference": m["truth_column"], "output": m["output"]} for m in metrics_of(setup)],
            "items": len(items), "items_with_files": sum(bool(it.get("files")) for it in items),
            "problems": problems,
            "layers": [{"layer": c["layer"], **({"metric": c["metric"]} if c.get("metric") else {}),
                        "locked": c["layer"] != "metrics", "lines": c["text"].count("\n"),
                        "starts": c["text"].strip().splitlines()[0][:100] if c["text"].strip() else ""} for c in chunks]}
    run.write("prepare.json", res)
    return res


class ModelsLocked(ValueError):
    pass


def lock_models(cfg: RunConfig) -> None:
    """A refinement keeps the models it started with: every version is scored and reviewed by the same models, so
    the gate compares like with like. The first start writes <run>/models.json; a later start (a resume) with other
    models is refused."""
    path = Path(cfg.run) / "models.json"
    now, was = cfg.run_models(), read(path)
    if was is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(now, indent=1))
        return
    changed = [f"{k} {was.get(k)} → {v}" for k, v in now.items() if was.get(k) != v]
    if changed:
        raise ModelsLocked("This run's models are locked since it started (" + "; ".join(changed) + "). "
                           "Resume with the same models, or start a new run to use other ones.")


def refine(cfg: RunConfig) -> dict:
    """The full loop in this process. Resumes if the run folder already has progress. Returns the best version per
    metric."""
    return loop.main(cfg)


def start(cfg: RunConfig, prepare_only: bool = False) -> dict:
    """The full loop (or only the preparation) in a detached background process; output goes to <run>/run.log."""
    run = Run(Path(cfg.run))
    st = status(cfg.run)
    if st.get("running"):
        return {**st, "note": "already running"}
    if not prepare_only:
        try:
            lock_models(cfg)
        except ModelsLocked as e:
            return {"run": str(run.dir), "running": False, "error": str(e), "locked": read(run.dir / "models.json")}
    log = (run.dir / "run.log").open("a")
    if prepare_only:
        (run.dir / "prepare.json").unlink(missing_ok=True)
    p = subprocess.Popen([sys.executable, "-m", "refiner", *cfg.args(), *(["--prepare"] if prepare_only else [])], stdout=log, stderr=subprocess.STDOUT,
                         start_new_session=True, cwd=os.getcwd())
    run.write("process.json", {"pid": p.pid, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "args": cfg.args(),
                               "task": "prepare" if prepare_only else "refine"})
    return {"run": str(run.dir), "pid": p.pid, "running": True, "task": "prepare" if prepare_only else "refine",
            "log": str(run.dir / "run.log"), "next": "poll run_status"}


def stop(run_dir: str) -> dict:
    """Stop a background run. Progress is kept; start it again with the same folder to resume."""
    proc = read(Path(run_dir) / "process.json")
    if not proc or not process.alive(proc["pid"]):
        return {"run": run_dir, "running": False, "note": "not running"}
    os.killpg(os.getpgid(proc["pid"]), signal.SIGTERM)
    process.reap(proc["pid"])
    events.emit(Path(run_dir), "run.failed", task=proc.get("task", ""), error="stopped by user")
    return {"run": run_dir, "running": False, "stopped_pid": proc["pid"]}


def health(run_dir: str) -> dict:
    """Is the run's process alive, and how did it end? Reads process.json and the last event only (milliseconds)."""
    d = Path(run_dir)
    proc = read(d / "process.json")
    last = events.last(d)
    pid = proc.get("pid") if proc else None
    if pid:
        process.reap(pid)
    alive = bool(pid and process.alive(pid))
    ended = last if last and last["type"] in events.TERMINAL else None
    if alive:
        state = "running"
    elif ended:
        state = "done" if ended["type"] == "run.done" else ("stopped" if ended["data"].get("error") == "stopped by user" else "failed")
    else:
        state = "stopped" if proc else "not_started"
    return {"alive": alive, "pid": pid, "state": state, "last_event_seq": (last or {}).get("seq", 0),
            "last_event_at": (last or {}).get("ts"), "error": (ended or {}).get("data", {}).get("error")}


def results_file(run_dir: str) -> Path | None:
    """results.xlsx with its Results sheet holding every column of the original sheet, then the final prompt's output
    (the composed prompt for several metrics, the best version for one). Older runs are brought up to date in place;
    every other sheet is kept. None until the run has finished."""
    from .utils import excel

    d = Path(run_dir)
    path = d / "results.xlsx"
    proc, setup, items = read(d / "process.json"), read(d / "setup/setup.json"), read(d / "setup/items.json")
    if not (path.exists() and proc and setup and items):
        return path if path.exists() else None
    args = proc.get("args", [])
    opt = lambda k: args[args.index(k) + 1] if k in args else None  # noqa: E731
    sheet = excel.read_sheet(Path(opt("--sheet")), opt("--sheet-name"))
    if (d / "composed/final/outputs.json").exists():
        answers = read(d / "composed/final/outputs.json", {})
    else:
        best = (read(d / "state.json") or {}).get("best", "v0")
        answers = read(d / f"versions/{best}/outputs.json", {})
    others = pd.read_excel(path, sheet_name=None)
    excel.write(path, {"Results": excel.results_rows(items, answers, setup, sheet),
                       **{k: v.to_dict("records") for k, v in others.items() if k != "Results"}})
    return path


def report(run_dir: str) -> dict | None:
    """report.json, once the run has written it."""
    return read(Path(run_dir) / "report.json")


def _metric_dir(run_dir: str, metric: str | None) -> tuple[Path, dict, str]:
    d = Path(run_dir)
    setup = read(d / "setup/setup.json")
    if setup is None:
        raise FileNotFoundError("the run has not been prepared yet")
    ms = metrics_of(setup)
    keys = [m["key"] for m in ms]
    key = metric or keys[0]
    if key not in keys:
        raise ValueError(f"unknown metric {key!r}; the run's metrics are {keys}")
    return (d / "metrics" / key if len(ms) > 1 else d), next(m["output"] for m in ms if m["key"] == key), key


def version_report(run_dir: str, metric: str | None = None) -> dict:
    """Every version of a metric (or of every metric): parent, verdict, round, numbers, students moved, change summary."""
    d = Path(run_dir)
    setup = read(d / "setup/setup.json")
    if setup is None:
        return {"run": run_dir, "metrics": {}, "note": "not prepared yet"}
    out = {}
    for key in ([metric] if metric else [m["key"] for m in metrics_of(setup)]):
        mdir, o, key = _metric_dir(run_dir, key)
        st = read(mdir / "state.json") or {}
        rows = rpt.lineage(mdir, o)
        for r in rows:
            c = st.get("changes", {}).get(r["version"], {})
            r.update(summary=c.get("summary", ""), closer=len(c.get("closer", [])), further=len(c.get("further", [])))
        out[key] = {"best": st.get("best", "v0"), "round": st.get("round", 0), "versions": rows}
    return {"run": run_dir, "metrics": out}


def rubric(run_dir: str, metric: str | None, ver: str) -> dict:
    """One version's metric section and its parent's, for a side-by-side diff."""
    mdir, _, key = _metric_dir(run_dir, metric)
    text = rpt.section(mdir, ver)
    if text is None:
        raise FileNotFoundError(f"{key} has no version {ver}")
    parent = ((read(mdir / "state.json") or {}).get("changes", {}).get(ver, {}) or {}).get("parent")
    return {"metric": key, "version": ver, "parent": parent, "text": text,
            "parent_text": rpt.section(mdir, parent) if parent else None}


def _errors(d: Path) -> tuple[dict, str]:
    setup, items = read(d / "setup/setup.json"), read(d / "setup/items.json", [])
    out = setup["output"]
    refs = {it["id"]: v for it in items if (v := reference(it["truth"], out)) is not None}
    return refs, out["type"]


def status(run_dir: str) -> dict:
    """Where a run stands: running or not, round, best version, every version's numbers, the checklist, the last log lines."""
    d = Path(run_dir)
    proc = read(d / "process.json")
    st = read(d / "state.json")
    res: dict[str, Any] = {"run": str(d), "running": bool(proc and process.alive(proc["pid"])), "task": (proc or {}).get("task", "")}
    setup = read(d / "setup/setup.json")
    # fan-out: one sub-run per metric, then the composed prompt; before the sub-runs exist, report the preparation
    if setup and len(metrics_of(setup)) > 1 and (d / "metrics").is_dir():
        subs = {m["key"]: status(str(d / "metrics" / m["key"])) for m in metrics_of(setup)}
        return {**res, "metrics": {k: {x: v for x, v in s.items() if x not in ("running", "task")} for k, s in subs.items()},
                "composed": read(d / "composed.json"), "log_tail": read(d / "run.log", "").splitlines()[-5:],
                "results": str(d / "results.xlsx"), "final_prompt": str(d / "final_prompt.md"),
                "note": "details of one metric: pass its folder, e.g. " + str(d / "metrics" / next(iter(subs)))}
    prep = read(d / "prepare.json")
    if not st:
        if res["running"]:
            stage = "preparing" if res["task"] == "prepare" else "preparing, then scoring and reviewing v0"
        else:
            stage = "prepared" if prep and prep.get("ready") else "needs answers" if prep else "not prepared"
        tail = read(d / "run.log", "").splitlines()[-5:]
        return {**res, "stage": stage, "setup": prep, "log_tail": tail}
    refs, kind = _errors(d)
    rows = []
    for v in st["versions"]:
        sc = read(d / f"versions/{v}/scores.json")
        if sc is None:
            continue
        c = st["changes"].get(v, {})
        rows.append({"version": v, "verdict": c.get("verdict", "baseline"), "from": c.get("parent", ""),
                     **M.alignment(M.item_errors(sc, refs, kind), None, kind)})
    checklist = read(d / "checklist.json", {})
    last = st["rounds"][-1] if st.get("rounds") else {}
    log = read(d / "debug.txt", "").splitlines()
    return {**res, "round": st["round"], "best": st["best"], "rejected_in_a_row": st["fails"], "versions": rows,
            "checklist": [{"id": k, "status": c["status"], "title": c.get("title", ""), "direction": c["direction"], "items": len(c["items"])}
                          for k, c in checklist.items()],
            "locked_flags": last.get("locked", []), "overview": last.get("overview", ""),
            "stopped": next((ln for ln in reversed(log) if ln.startswith("=== STOP")), None),
            "results": str(d / "results.xlsx"), "final_prompt": str(d / "final_prompt.md")}


def checklist(run_dir: str) -> dict:
    """The full issue checklist: root cause, items, clause, fix and the per-round status history of every issue."""
    return read(Path(run_dir) / "checklist.json", {})


def version(run_dir: str, ver: str) -> dict:
    """One version: its numbers, verdict, the full prompt and what changed."""
    d = Path(run_dir)
    sc = read(d / f"versions/{ver}/scores.json")
    if sc is None:
        return {"error": f"{ver} has not been scored"}
    refs, kind = _errors(d)
    st = read(d / "state.json", {"changes": {}})
    c = st["changes"].get(ver, {})
    return {"version": ver, "verdict": c.get("verdict", "baseline"), "from": c.get("parent", ""),
            "metrics": M.alignment(M.item_errors(sc, refs, kind), None, kind),
            "prompt": read(d / f"versions/{ver}/prompt.md", ""), "change": read(d / f"versions/{ver}/change.md", ""),
            "result_xlsx": str(d / f"versions/{ver}/result.xlsx")}


def list_runs(root: str = "runs") -> list[dict]:
    """Every refiner run under `root` (folders with setup/setup.json), newest first."""
    out = []
    for p in Path(root).glob("*/setup/setup.json"):
        d = p.parent.parent
        st = read(d / "state.json") or {}
        proc = read(d / "process.json")
        out.append({"run": str(d), "round": st.get("round"), "best": st.get("best"),
                    "running": bool(proc and process.alive(proc["pid"])), "updated": time.strftime("%Y-%m-%d %H:%M", time.localtime(d.stat().st_mtime))})
    return sorted(out, key=lambda r: r["updated"], reverse=True)
