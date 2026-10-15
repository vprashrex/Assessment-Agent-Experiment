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
from typing import Any

from . import loop
from . import math_tool as M
from .agents import metrics_of, reference
from .config import RunConfig
from .loop import NeedsAnswers, Run


def _read(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text()) if path.suffix == ".json" else path.read_text()


def prepare(cfg: RunConfig) -> dict:
    """Run the parser, cut the prompt into layers and collect every submission with its attachments. No scoring.
    Returns the setup to review, or `questions` the operator must answer in the context file before starting."""
    run = Run(Path(cfg.run))
    try:
        setup, items = loop.setup_run(run, cfg)
    except NeedsAnswers as e:
        res = {"run": str(run.dir), "ready": False, "questions": e.questions}
        run.write("prepare.json", res)
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


def refine(cfg: RunConfig) -> dict:
    """The full loop in this process. Resumes if the run folder already has progress."""
    loop.main(cfg)
    return status(cfg.run)


def start(cfg: RunConfig, prepare_only: bool = False) -> dict:
    """The full loop (or only the preparation) in a detached background process; output goes to <run>/run.log."""
    run = Run(Path(cfg.run))
    st = status(cfg.run)
    if st.get("running"):
        return {**st, "note": "already running"}
    log = (run.dir / "run.log").open("a")
    if prepare_only:
        (run.dir / "prepare.json").unlink(missing_ok=True)
    p = subprocess.Popen([sys.executable, "-m", "refiner", *cfg.args(), *(["--prepare"] if prepare_only else [])], stdout=log, stderr=subprocess.STDOUT,
                         start_new_session=True, cwd=os.getcwd())
    run.write("process.json", {"pid": p.pid, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "args": cfg.args(),
                               "task": "prepare" if prepare_only else "refine"})
    return {"run": str(run.dir), "pid": p.pid, "running": True, "task": "prepare" if prepare_only else "refine",
            "log": str(run.dir / "run.log"), "next": "poll run_status"}


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # a finished child that was never reaped still answers kill(0); check it is not a zombie
        out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        return bool(out) and not out.startswith("Z")
    except Exception:
        return True


def stop(run_dir: str) -> dict:
    """Stop a background run. Progress is kept; start it again with the same folder to resume."""
    proc = _read(Path(run_dir) / "process.json")
    if not proc or not _alive(proc["pid"]):
        return {"run": run_dir, "running": False, "note": "not running"}
    os.killpg(os.getpgid(proc["pid"]), signal.SIGTERM)
    return {"run": run_dir, "running": False, "stopped_pid": proc["pid"]}


def _errors(d: Path) -> tuple[dict, str]:
    setup, items = _read(d / "setup/setup.json"), _read(d / "setup/items.json", [])
    out = setup["output"]
    refs = {it["id"]: v for it in items if (v := reference(it["truth"], out)) is not None}
    return refs, out["type"]


def status(run_dir: str) -> dict:
    """Where a run stands: running or not, round, best version, every version's numbers, the checklist, the last log lines."""
    d = Path(run_dir)
    proc = _read(d / "process.json")
    st = _read(d / "state.json")
    res: dict[str, Any] = {"run": str(d), "running": bool(proc and _alive(proc["pid"])), "task": (proc or {}).get("task", "")}
    setup = _read(d / "setup/setup.json")
    if setup and len(metrics_of(setup)) > 1:  # fan-out: one sub-run per metric, then the composed prompt
        subs = {m["key"]: status(str(d / "metrics" / m["key"])) for m in metrics_of(setup)}
        return {**res, "metrics": {k: {x: v for x, v in s.items() if x not in ("running", "task")} for k, s in subs.items()},
                "composed": _read(d / "composed.json"), "log_tail": _read(d / "run.log", "").splitlines()[-5:],
                "results": str(d / "results.xlsx"), "final_prompt": str(d / "final_prompt.md"),
                "note": "details of one metric: pass its folder, e.g. " + str(d / "metrics" / next(iter(subs)))}
    prep = _read(d / "prepare.json")
    if not st:
        if res["running"]:
            stage = "preparing" if res["task"] == "prepare" else "preparing, then scoring and reviewing v0"
        else:
            stage = "prepared" if prep and prep.get("ready") else "needs answers" if prep else "not prepared"
        tail = _read(d / "run.log", "").splitlines()[-5:]
        return {**res, "stage": stage, "setup": prep, "log_tail": tail}
    refs, kind = _errors(d)
    rows = []
    for v in st["versions"]:
        sc = _read(d / f"versions/{v}/scores.json")
        if sc is None:
            continue
        c = st["changes"].get(v, {})
        rows.append({"version": v, "verdict": c.get("verdict", "baseline"), "from": c.get("parent", ""),
                     **M.alignment(M.item_errors(sc, refs, kind), None, kind)})
    checklist = _read(d / "checklist.json", {})
    last = st["rounds"][-1] if st.get("rounds") else {}
    log = _read(d / "debug.txt", "").splitlines()
    return {**res, "round": st["round"], "best": st["best"], "rejected_in_a_row": st["fails"], "versions": rows,
            "checklist": [{"id": k, "status": c["status"], "title": c.get("title", ""), "direction": c["direction"], "items": len(c["items"])}
                          for k, c in checklist.items()],
            "locked_flags": last.get("locked", []), "overview": last.get("overview", ""),
            "stopped": next((ln for ln in reversed(log) if ln.startswith("=== STOP")), None),
            "results": str(d / "results.xlsx"), "final_prompt": str(d / "final_prompt.md")}


def checklist(run_dir: str) -> dict:
    """The full issue checklist: root cause, items, clause, fix and the per-round status history of every issue."""
    return _read(Path(run_dir) / "checklist.json", {})


def version(run_dir: str, ver: str) -> dict:
    """One version: its numbers, verdict, the full prompt and what changed."""
    d = Path(run_dir)
    sc = _read(d / f"versions/{ver}/scores.json")
    if sc is None:
        return {"error": f"{ver} has not been scored"}
    refs, kind = _errors(d)
    st = _read(d / "state.json", {"changes": {}})
    c = st["changes"].get(ver, {})
    return {"version": ver, "verdict": c.get("verdict", "baseline"), "from": c.get("parent", ""),
            "metrics": M.alignment(M.item_errors(sc, refs, kind), None, kind),
            "prompt": _read(d / f"versions/{ver}/prompt.md", ""), "change": _read(d / f"versions/{ver}/change.md", ""),
            "result_xlsx": str(d / f"versions/{ver}/result.xlsx")}


def list_runs(root: str = "runs") -> list[dict]:
    """Every refiner run under `root` (folders with setup/setup.json), newest first."""
    out = []
    for p in Path(root).glob("*/setup/setup.json"):
        d = p.parent.parent
        st = _read(d / "state.json") or {}
        proc = _read(d / "process.json")
        out.append({"run": str(d), "round": st.get("round"), "best": st.get("best"),
                    "running": bool(proc and _alive(proc["pid"])), "updated": time.strftime("%Y-%m-%d %H:%M", time.localtime(d.stat().st_mtime))})
    return sorted(out, key=lambda r: r["updated"], reverse=True)
