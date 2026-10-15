"""The refinement loop. Every step writes to the run folder first, so a rerun resumes where it stopped.

runs/<run>/
  results.xlsx        Results (inputs + the best prompt's full output, one column per key), Agreement, then Versions,
                      Rounds, Items, Checklist, Judge notes, Edits, Locked flags
  final_prompt.md     the best version's full prompt
  debug.txt           per round: numbers, the judge's overview, the checklist, locked flags, every tool call
  setup/              setup.json, items.json, baseline/ (1_program 2_metrics 3_notes 4_output .md + layout.json)
  versions/vN/        prompt.md, chunks.json, scores.json, outputs.json (the scorer's whole answers), notes.json (judge
                      notes per submission), change.md, result.xlsx
  checklist.json      the issue checklist; each issue's status is measured by code every round
  dialogue.md         the judge and the author, round by round
  state.json          for resuming

Only the metrics layer is ever edited; every version keeps the program, notes and output layers word for word.
With several metrics, `main` hands over to fanout.py: each metric's `refine` runs in its own metrics/<key>/ folder.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from . import agents, excel, tracing
from . import math_tool as M
from .agents import reference
from .data import build_items, read_sheet

ACTIVE = ("new", "open", "reopened")


class Run:
    """A run folder. A metric's sub-run (metrics/<key>/ of a fan-out run) is a run folder too; it shares the parent's
    tracing session and prefixes its progress lines with the metric key."""
    def __init__(self, path: Path, session: str | None = None, label: str = "", parent: "Run | None" = None):
        self.dir = path
        self.dir.mkdir(parents=True, exist_ok=True)
        self.session, self.label, self.parent = session or path.name, label, parent

    def read(self, name: str, default: Any = None) -> Any:
        p = self.dir / name
        if not p.exists():
            return default
        return json.loads(p.read_text()) if p.suffix == ".json" else p.read_text()

    def write(self, name: str, data: Any) -> None:
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1))

    def append(self, name: str, text: str) -> None:
        with (self.dir / name).open("a") as f:
            f.write(text.rstrip() + "\n")


def debug(run: Run, text: str) -> None:
    """The run's debug.txt; a metric's sub-run also writes each entry to the parent's, prefixed with its key."""
    run.append("debug.txt", text)
    if run.parent:
        run.parent.append("debug.txt", "\n".join(f"[{run.label}] {ln}" for ln in text.rstrip().splitlines()))


def numbers(a: dict, out: dict) -> str:
    if not a.get("n"):
        return "no scored items"
    if out["type"] == "enum":
        return f"accuracy {a['accuracy']:.0%} · {a['n']} items"
    return f"MAE {a['mae']:.2f} · bias {a['bias']:+.2f} · within ±1 {a['within1']:.0%} · within ±2 {a['within2']:.0%} · {a['n']} items"


class NeedsAnswers(Exception):
    """The parser or the layer split needs the operator: `questions` lists what to answer in the context file."""
    def __init__(self, questions: list[str]):
        super().__init__("\n- ".join(["The run needs answers — add them to the context file and rerun:"] + questions))
        self.questions = questions


def labels(a, metric: str = "") -> dict:
    """Run settings attached to every trace of the run."""
    return {"model": a.model, "scorer": a.scorer or a.model, "effort": a.effort, "mode": a.mode, **({"metric": metric} if metric else {})}


def setup_run(run: Run, a) -> tuple[dict, list[dict]]:
    df = read_sheet(Path(a.sheet), a.sheet_name)
    v0 = Path(a.prompt).read_text()
    todo = not all(run.read(f) for f in ("setup/setup.json", "setup/items.json", "setup/baseline/layout.json"))
    with (tracing.span("prepare-run", session=run.session, metadata=labels(a), input={"sheet": Path(a.sheet).name, "rows": len(df)})
          if todo else nullcontext()) as t:
        setup, items = _setup(run, a, df, v0)
        t and t.update(output={"items": len(items), "items_with_files": sum(bool(it.get("files")) for it in items),
                                  "metrics": [m["key"] for m in agents.metrics_of(setup)]})
    return setup, items


def _setup(run: Run, a, df, v0: str) -> tuple[dict, list[dict]]:
    if not run.read("setup/setup.json"):
        schema = json.loads(Path(a.schema).read_text()) if a.schema else None
        setup = agents.parse(df, Path(a.context).read_text(), v0, schema, a.model, a.effort, a.mode)
        setup["output_schema"] = schema  # what the scorer answers in, as in production
        if setup["questions"]:
            raise NeedsAnswers(setup["questions"])
        run.write("setup/setup.json", setup)
    setup = run.read("setup/setup.json")
    if not run.read("setup/items.json"):
        items, problems = build_items(df, setup, Path(a.docs_dir) if a.docs_dir else None)
        run.write("setup/items.json", items[: a.n] if a.n else items)
        for p in problems:
            debug(run, f"setup: {p}")
    if not run.read("setup/baseline/layout.json"):
        chunks, problems = agents.layout(v0, setup["layers"])
        if problems:
            raise NeedsAnswers(problems)
        for k, name in enumerate(agents.LAYERS, start=1):
            run.write(f"setup/baseline/{k}_{name}.md", "\n".join(c["text"].rstrip() for c in chunks if c["layer"] == name) + "\n")
        run.write("setup/baseline/layout.json", chunks)
        if len(agents.metrics_of(setup)) == 1:  # with several metrics every version lives in metrics/<key>/
            run.write("versions/v0/chunks.json", chunks)
            run.write("versions/v0/prompt.md", agents.assemble(chunks))
    return setup, run.read("setup/items.json")


def update_checklist(checklist: dict, issues: list[dict], rnd: int, ver: str, errs: dict, known: set[str]) -> None:
    """Merge the judge's issues into the checklist (same id = same issue), then measure EVERY issue on `ver`.
    Status by code: real now → new / open / reopened; not real → resolved (if it was active) / watch (never verified)."""
    nxt = max([int(k[1:]) for k in checklist if k[1:].isdigit()] or [0]) + 1
    mentioned = set()
    for x in issues:
        if x.get("direction") not in ("too_high", "too_low") or not x.get("items"):
            continue
        k = str(x.get("id", "new")).strip().upper()
        if k not in checklist:
            k, nxt = f"I{nxt}", nxt + 1
            checklist[k] = {"opened_round": rnd, "status": None, "history": []}
        if k in mentioned:
            continue
        mentioned.add(k)
        checklist[k].update({f: x.get(f) or checklist[k].get(f) or "" for f in
                             ("title", "root_cause", "what_items", "direction", "clause", "fix", "status_note")},
                            items=[i for i in x["items"] if i in known])
    for k, c in checklist.items():
        c["history"] = [e for e in c["history"] if e["round"] != rnd]
        prev = c["history"][-1]["status"] if c["history"] else None
        pc = M.pattern_check(errs, c["items"])
        real = bool(pc.get("real")) and pc.get("direction") == c["direction"]
        status = (("new" if prev is None else "reopened" if prev == "resolved" else "open") if real
                  else "resolved" if prev in ACTIVE + ("resolved",) else "watch")
        c["status"] = status
        c["history"].append({"round": rnd, "version": ver, "n": pc.get("n", 0), "mean_error": pc.get("mean_error", 0.0),
                             "threshold": pc.get("threshold") or 0.0, "real": real, "status": status, "mentioned": k in mentioned})


def main(a) -> None:
    run = Run(Path(a.run))
    setup, items = setup_run(run, a)
    if len(agents.metrics_of(setup)) > 1:
        from . import fanout
        fanout.main(run, a, setup, items)
    else:
        refine(run, a, setup, items)


def refine(run: Run, a, setup: dict, items: list[dict]) -> None:
    """The loop for one metric: score, review, diagnose, edit, gate — until a stop rule fires."""
    out = setup["output"]
    kind = out["type"]
    truths = {it["id"]: reference(it["truth"], out) for it in items}
    refs = {i: v for i, v in truths.items() if v is not None}
    am = dict(model=a.model, effort=a.effort, mode=a.mode)
    V = lambda ver, f: f"versions/{ver}/{f}"  # noqa: E731

    def scored(ver: str) -> dict:
        if run.read(V(ver, "scores.json")) is None:
            with tracing.span("score-items", input={"version": ver, "items": len(items)}) as s:
                answers: dict = {}
                run.write(V(ver, "scores.json"), agents.score(run.read(V(ver, "prompt.md")), items, out, schema=setup.get("output_schema"),
                                                              raw=answers, model=a.scorer, effort=a.effort,
                                                              mode=a.mode, workers=a.workers))
                run.write(V(ver, "outputs.json"), answers)
                s.update(output=metrics(ver))
        return run.read(V(ver, "scores.json"))

    def reviewed(ver: str, subset: list[dict] | None = None) -> dict:
        if run.read(V(ver, "notes.json")) is None:
            todo, preds = items if subset is None else subset, scored(ver)  # score first: its span is a sibling, not a child
            with tracing.span("review-items", input={"version": ver, "items": len(todo)}) as s:
                run.write(V(ver, "notes.json"), agents.review(agents.annotated(run.read(V(ver, "chunks.json"))), todo,
                                                              preds, truths, out, workers=a.workers, **am))
                dirs = [n["direction"] for n in run.read(V(ver, "notes.json")).values()]
                s.update(output={d: dirs.count(d) for d in ("too_high", "too_low", "aligned")})
        return run.read(V(ver, "notes.json"))

    E = lambda ver: M.item_errors(scored(ver), refs, kind)  # noqa: E731
    metrics = lambda ver: M.alignment(E(ver), None, kind)  # noqa: E731

    ids_prop = {"type": "array", "items": {"type": "string"}}
    tools = {
        "alignment": ("MAE, bias, within ±1, within ±2 (or accuracy) of a rubric version against the reference, over all items "
                      "or the given ids.", {"type": "object", "properties": {"version": {"type": "string"}, "ids": ids_prop},
                                            "required": ["version"]},
                      lambda version, ids=None: M.alignment(E(version), ids, kind)),
        "item_errors": ("Per item error (output − reference) for a version, optionally only some ids.",
                        {"type": "object", "properties": {"version": {"type": "string"}, "ids": ids_prop}, "required": ["version"]},
                        lambda version, ids=None: {i: x for i, x in E(version).items() if not ids or i in ids}),
        "compare": ("Items that moved closer to / further from the reference between two versions, with the size of each move.",
                    {"type": "object", "properties": {"old": {"type": "string"}, "new": {"type": "string"}}, "required": ["old", "new"]},
                    lambda old, new: M.compare(E(old), E(new))),
        "pattern_check": ("Is a group of items a real pattern? Compares the group's mean error with the dynamic threshold "
                          "z·scatter/√n (n = group size). Returns real true/false and direction.",
                          {"type": "object", "properties": {"version": {"type": "string"}, "ids": ids_prop}, "required": ["version", "ids"]},
                          lambda version, ids: M.pattern_check(E(version), ids)),
        "volatility": ("Are the misses scattered rather than systematic? volatile = no overall direction beyond the threshold "
                       "AND scatter ≥ ratio × the references' own spread.",
                       {"type": "object", "properties": {"version": {"type": "string"}}, "required": ["version"]},
                       lambda version: M.volatility(E(version), refs)),
    }

    st = run.read("state.json") or {"round": 0, "best": "v0", "fails": 0, "versions": ["v0"], "by_item": {},
                                     "last_change": "(baseline — no edit yet)", "rounds": [], "changes": {}}
    checklist = run.read("checklist.json", {})

    def version_row(ver: str) -> dict:
        c = st["changes"].get(ver, {})
        return {"version": ver, "verdict": c.get("verdict", "baseline"), "from": c.get("parent", ""), **metrics(ver),
                "closer": len(c.get("closer", [])), "further": len(c.get("further", [])),
                "words": len(run.read(V(ver, "prompt.md")).split())}

    def write_version_excel(ver: str) -> None:
        excel.write(run.dir / V(ver, "result.xlsx"),
                    excel.version_sheets(ver, version_row(ver), items, scored(ver), refs, E(ver), run.read(V(ver, "notes.json"), {}),
                                         run.read(V(ver, "chunks.json")), st["changes"].get(ver)))

    def write_run_excel() -> None:
        vs = [v for v in st["versions"] if run.read(V(v, "scores.json")) is not None]
        excel.write(run.dir / "results.xlsx",
                    {"Results": excel.results_rows(items, run.read(V(st["best"], "outputs.json"), {}), setup),
                     "Agreement": excel.agreement_rows([(out["field"], M.agreement(E(st["best"]), kind))]),
                     **excel.run_sheets([version_row(v) for v in vs], items, refs, {v: scored(v) for v in vs}, st["best"], E(st["best"]),
                                     {v: run.read(V(v, "notes.json"), {}) for v in vs}, checklist, st["rounds"], st["changes"])})
        run.write("final_prompt.md", run.read(V(st["best"], "prompt.md")))

    while True:
        best, rnd0 = st["best"], st["round"]
        with tracing.span("refine-round", session=run.session, metadata=labels(a, run.label), input={"round": rnd0 + 1, "best": best}) as rt:
            rv = reviewed(best)
            errs = E(best)
            if not (run.dir / V(best, "result.xlsx")).exists():
                write_version_excel(best)

            # ---- judge: holistic diagnosis + checklist ----
            tool_log: list = []
            summ = agents.summarise(agents.annotated(run.read(V(best, "chunks.json"))), best, st["versions"], rv, errs, out,
                                    st["last_change"], run.read("dialogue.md", ""), checklist, tools, tool_log, **am)
            bad = [x for x in summ["issues"] if not x.get("title")]
            if bad:
                debug(run, f"judge returned {len(bad)} issue(s) without all fields: {json.dumps(bad)[:400]}")
            update_checklist(checklist, summ["issues"], rnd0, best, errs, set(refs))
            run.write("checklist.json", checklist)
            active = {k: c for k, c in checklist.items() if c["status"] in ACTIVE}
            if summ["mode"] == "rewrite" and active:  # rewrite only when no issue is measured as real
                summ["mode"] = "edit"
            summ["checklist"] = checklist
            st["rounds"] = [r for r in st["rounds"] if r["round"] != rnd0] + [
                {"round": rnd0, "best": best, "mode": summ["mode"], "overview": summ["overview"], "summary": summ["summary"],
                 "locked": summ["locked"]}]

            run.append("dialogue.md", f"\n## after round {rnd0} (best {best}) · mode {summ['mode']}\n[reviewer] {summ['overview']}\n"
                       f"[reviewer] {summ['summary']}\n"
                       + (f"  rewrite brief: {summ['rewrite_brief']}\n" if summ["mode"] == "rewrite" else "")
                       + "".join(f"  - [{k}] {c['status']} · {c['title']} · items {c['items']} · cause: {c['root_cause']} → {c['fix']}\n"
                                 for k, c in checklist.items())
                       + "".join(f"  - LOCKED ({x['layer']}) not edited, for the program owner: {x['clause'][:160]} · items {x['items']} · {x['why']}\n"
                                 for x in summ["locked"]))
            debug(run, f"=== round {rnd0} · best {best} · {numbers(metrics(best), out)} · mode {summ['mode']}\n"
                  f"overview: {summ['overview']}\njudge: {summ['summary']}\n"
                  + (f"rewrite brief: {summ['rewrite_brief']}\n" if summ["mode"] == "rewrite" else "")
                  + "checklist:\n"
                  + "".join(f"  [{k}] {c['status'].upper():9} {c['title']} [{c['direction']}] · mean error {c['history'][-1]['mean_error']:+.2f} "
                            f"vs {c['history'][-1]['threshold']:.2f} · items {', '.join(c['items'])}\n"
                            f"      cause: {c['root_cause']}\n      clause: {' '.join(c['clause'].split())[:160]}\n      fix: {c['fix']}\n"
                            f"      judge: {c.get('status_note', '')}\n" for k, c in checklist.items())
                  + "".join(f"LOCKED FLAG ({x['layer']}, for the program owner) · items {', '.join(x['items'])}\n"
                            f"   clause: {' '.join(x['clause'].split())[:160]}\n   why: {x['why']}\n" for x in summ["locked"])
                  + "".join(f"tool: {t['tool']}({json.dumps(t['args'])}) → {json.dumps(t['result'])[:300]}\n" for t in tool_log))
            run.write("state.json", st)
            write_run_excel()

            mae_best = metrics(best).get("mae", 1e9)
            why = (f"ceiling — {a.rounds} rounds" if rnd0 >= a.rounds
                   else f"target reached — MAE {mae_best} ≤ {a.target}" if a.target is not None and mae_best <= a.target
                   else f"no improvement in {a.patience} rounds" if st["fails"] >= a.patience else None)
            if why:
                rt.update(output={"stopped": why, "best": best})
                break

            # ---- author: next candidate ----
            rnd = rnd0 + 1
            cand = f"v{rnd}"
            if not run.read(V(cand, "chunks.json")):
                issues_of: dict[str, list[str]] = {}
                for k, c in checklist.items():
                    for i in c["items"]:
                        issues_of.setdefault(i, []).append(k)
                csv = agents.table(rv, errs, out, {i: " | ".join(h) for i, h in st["by_item"].items()}, issues_of)
                chunks, gen, problems = agents.generate(run.read(V(best, "chunks.json")), summ, csv, run.read("dialogue.md", ""), **am)
                locked = [c for c in chunks if c["layer"] != agents.EDITABLE]
                assert locked == [c for c in run.read("setup/baseline/layout.json") if c["layer"] != agents.EDITABLE], "locked layer changed"
                run.write(V(cand, "chunks.json"), chunks)
                run.write(V(cand, "prompt.md"), agents.assemble(chunks))
                st["changes"][cand] = {"parent": best, "realisation": gen["realisation"], "summary": gen["summary"],
                                       "edits": gen["edits"] if summ["mode"] == "edit" else [],
                                       "rewrite": gen["rewrite"] if summ["mode"] == "rewrite" else [], "problems": problems}
                run.write("state.json", st)
                run.append("dialogue.md", f"\n## {cand} (from {best})\n[author] realisation: {gen['realisation']}\n[author] change: {gen['summary']}\n"
                           + "".join(f"  - {e['issue']}: “{e['old_text'][:120]}” → “{e['new_text'][:400]}”\n" for e in st["changes"][cand]["edits"])
                           + (f"  (rewrote the {len(gen['rewrite'])} editable part(s) of the metrics layer)\n" if st["changes"][cand]["rewrite"] else "")
                           + (f"  (edits not applied: {'; '.join(problems)})\n" if problems else ""))
                debug(run, f"--- {cand} written from {best}: {gen['summary']}\nrealisation: {gen['realisation']}"
                      + (f"\nedits not applied: {'; '.join(problems)}" if problems else ""))

            ec = E(cand)
            kept = metrics(cand).get("mae", 1e9) < mae_best
            mv = M.compare(errs, ec)
            verdict = "KEPT" if kept else "REJECTED"
            # kept: review everything (it is next round's best); rejected: only what it pushed further away
            notes = reviewed(cand, None if kept else [it for it in items if it["id"] in set(mv["further"])])
            notes = {i: notes.get(i, {}) for i in mv["further"]}
            tag = f"{cand} {verdict.lower()}"
            for i in mv["closer"]:
                st["by_item"].setdefault(i, []).append(f"{tag}: closer")
            for i in mv["further"]:
                n = notes.get(i, {})
                st["by_item"].setdefault(i, []).append(f"{tag}: further — {n.get('comment', '')[:200]} (clause: {n.get('clause', '')[:120]})")
            st["last_change"] = (f"{cand} (edited from {best}) was {verdict}. Use the tools to measure it against {best}.\n"
                                 f"Items this edit pushed further from the reference, with the reason:\n"
                                 + "\n".join(f"  [{i}] {n.get('direction', '')} — clause: {n.get('clause', '')[:160]} — {n.get('comment', '')}"
                                             for i, n in notes.items()))
            st["changes"].setdefault(cand, {"parent": best, "realisation": "", "summary": "", "edits": [], "rewrite": [], "problems": []})
            st["changes"][cand].update(verdict=verdict, closer=list(mv["closer"]), further=list(mv["further"]))
            run.write(V(cand, "change.md"), f"# {cand} · {verdict} · from {best}\n\n{numbers(metrics(cand), out)}\n\n"
                      f"closer: {', '.join(mv['closer']) or '-'}\nfurther: {', '.join(mv['further']) or '-'}\n\n"
                      f"## realisation\n{st['changes'][cand]['realisation']}\n\n## change\n{st['changes'][cand]['summary']}\n\n"
                      + "".join(f"## edit · {e['issue']}\nOLD:\n{e['old_text']}\n\nNEW:\n{e['new_text']}\n\n" for e in st["changes"][cand]["edits"])
                      + "".join(f"## rewrite part {k}\n{t}\n\n" for k, t in enumerate(st["changes"][cand]["rewrite"], 1))
                      + (f"## not applied\n{'; '.join(st['changes'][cand]['problems'])}\n" if st["changes"][cand]["problems"] else ""))
            if cand not in st["versions"]:
                st["versions"].append(cand)
            st["round"], st["fails"] = rnd, (0 if kept else st["fails"] + 1)
            if kept:
                st["best"] = cand
            run.write("state.json", st)
            write_version_excel(cand)
            run.append("dialogue.md", f"[result] {cand} {verdict}; closer {list(mv['closer'])}; further {list(mv['further'])}")
            debug(run, f"--- {cand} {verdict} · {numbers(metrics(cand), out)} · closer {', '.join(mv['closer']) or '-'} · "
                       f"further {', '.join(mv['further']) or '-'}")
            rt.update(output={"candidate": cand, "verdict": verdict, **metrics(cand)})
            print(f"{run.label + ' ' if run.label else ''}r{rnd:02d} {cand} {verdict} · {numbers(metrics(cand), out)}", flush=True)

    write_run_excel()
    debug(run, f"=== STOP: {why} · best {st['best']} → {run.dir / 'final_prompt.md'}\n")
    print(f"{run.label + ' ' if run.label else ''}STOP: {why} · best {st['best']} · {run.dir / 'results.xlsx'}")
