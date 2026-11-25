"""The refinement loop. Every step writes to the run folder first, so a rerun resumes where it stopped.

runs/<run>/
  results.xlsx        Results (inputs + the best prompt's full output, one column per key), Agreement (train, and
                      test once scored), then Versions, Rounds, Items (with a split column), Checklist, Judge notes,
                      Edits, Locked flags
  final_prompt.md     the best version's full prompt
  debug.txt           per round: numbers, the judge's overview, the checklist, locked flags, every tool call
  setup/              setup.json, items.json, split.json (train/test ids, drawn once), baseline/ (1_program 2_metrics
                      3_notes 4_output .md + layout.json)
  models.json         the models and effort the refinement started with; a resume must match them
  spend.json          USD and tokens per model so far (agents/spend.py), updated after every model call
  versions/vN/        prompt.md, chunks.json, scores.json and outputs.json (train items; outputs = the scorer's whole
                      answers), scores2.json (the gate's second pass), notes.json (judge notes per submission),
                      change.md, result.xlsx; v0 and the best version also get scores_test.json / outputs_test.json,
                      the one scoring of the held-out items once the loop has stopped
  checklist.json      the issue checklist; each issue's status is measured by code every round
  dialogue.md         the judge and the author, round by round
  state.json          for resuming

Only the metrics layer is ever edited; every version keeps the program, notes and output layers word for word.
Every number the loop uses — scores, judge notes, the checklist, the gate, the stop rules — comes from the train
items; the test items are scored once at the end (`metric.test` event, `state.json` train/test).
With several metrics, `run.main` hands over to fanout.py: each metric's `refine` runs in its own metrics/<key>/ folder.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .. import agents, prompts
from ..agents import llm, spend
from ..agents import math_tool as M
from ..agents import reference
from ..utils import excel
from ..utils.excel import read_sheet
from ..utils.files import read as read_file
from . import events, split
from .items import build_items

ACTIVE = ("new", "open", "reopened")
SHRINK_PASSES = 5  # most passes of the shrink loop once refinement stops; it usually fails before this


class Run:
    """A run folder. A metric's sub-run (metrics/<key>/ of a fan-out run) is a run folder too; it prefixes its
    progress lines with the metric key."""
    def __init__(self, path: Path, label: str = "", parent: "Run | None" = None):
        self.dir = path
        self.dir.mkdir(parents=True, exist_ok=True)
        self.label, self.parent = label, parent

    def read(self, name: str, default: Any = None) -> Any:
        return read_file(self.dir / name, default)

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


def setup_event(setup: dict, items: list[dict], chunks: list[dict], sp: dict | None = None) -> dict:
    """The data of the setup.ready event: what the parser decided, in plain fields."""
    sp = sp or {}
    return {"id_column": setup.get("id_column"), "inputs": setup.get("input_columns", []),
            "metrics": [{"key": m["key"], "reference": m["truth_column"], "field": m["output"]["field"], "type": m["output"]["type"],
                         "min": m["output"].get("min"), "max": m["output"].get("max"), "values": m["output"].get("values")}
                        for m in agents.metrics_of(setup)],
            "items": len(items), "items_with_files": sum(bool(it.get("files")) for it in items),
            "split": {"spec": sp.get("spec"), "seed": sp.get("seed"), "train": len(sp.get("train", [])), "test": len(sp.get("test", []))},
            "layers": [{"layer": c["layer"], "metric": c.get("metric"), "lines": c["text"].count("\n"),
                        "starts": c["text"].strip().splitlines()[0][:100] if c["text"].strip() else ""} for c in chunks]}


def setup_run(run: Run, a) -> tuple[dict, list[dict]]:
    df = read_sheet(Path(a.sheet), a.sheet_name)
    v0 = Path(a.prompt).read_text()
    todo = not all(run.read(f) for f in ("setup/setup.json", "setup/items.json", "setup/baseline/layout.json", split.FILE))
    setup, items = _setup(run, a, df, v0)
    if todo:
        events.emit(run.dir, "setup.ready", **setup_event(setup, items, run.read("setup/baseline/layout.json"), run.read(split.FILE)))
    return setup, items


def _setup(run: Run, a, df, v0: str) -> tuple[dict, list[dict]]:
    if not run.read("setup/setup.json"):
        schema = json.loads(Path(a.schema).read_text()) if a.schema else None
        setup = agents.parse(df, Path(a.context).read_text() if a.context else "", v0, schema, a.parser_model, a.effort)
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
    # the train/test split, drawn once; a resume keeps it even when --split or --seed differ
    sp = run.read(split.FILE)
    if sp is None:
        sp = {"spec": a.split, "seed": a.seed, **split.make(run.read("setup/items.json"), a.split, a.seed)}
        run.write(split.FILE, sp)
        debug(run, f"setup: split {a.split} seed {a.seed} → {len(sp['train'])} train, {len(sp['test'])} test (held out)")
    elif (sp.get("spec"), sp.get("seed")) != (a.split, a.seed):
        debug(run, f"setup: split stays {sp.get('spec')} seed {sp.get('seed')} (stored at preparation; {a.split} / {a.seed} ignored)")
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


def decide(exact_best: float, mae_best: float, first: dict, words_best: int, words_cand: int, mv: dict,
           second: Callable[[], tuple[dict, dict]]) -> dict:
    """The gate, measured twice (math_tool.keep_candidate): `first` is the candidate's alignment from one scoring
    pass; a first-pass win only makes it borderline, then `second()` scores once more and returns (alignment,
    compare) of that pass, and the pooled numbers (math_tool.pool) give the verdict. Used by the per-metric loop
    and by both fan-out stages."""
    gate = M.keep_candidate(exact_best, first.get("exact", 0), mae_best, first.get("mae", 1e9), words_best, words_cand,
                            len(mv["closer"]), len(mv["further"]))
    if gate["borderline"]:
        a2, mv2 = second()
        gate = M.keep_candidate(exact_best, M.pool(first.get("exact", 0), a2.get("exact", 0)), mae_best,
                                M.pool(first.get("mae", 1e9), a2.get("mae", 1e9)), words_best, words_cand,
                                len(mv["closer"]) + len(mv2["closer"]), len(mv["further"]) + len(mv2["further"]), confirm=True)
    return gate


def simplify(run: Run, a, st: dict, checklist: dict, score_items, out: dict, editable: tuple[str, ...], words, metrics, N, ev, gm) -> str | None:
    """The shrink loop once refinement stops: the generator only merges and shortens the best version's editable
    text (MODE: SIMPLIFY), pass after pass, and each shorter version is kept while the exact matches hold. It
    stops the first time compression costs accuracy — the sweet point is measured, not set. Returns the new best,
    or None."""
    if st["best"] == "v0" or st.get("simplified"):
        return None
    st["simplified"] = True
    V = lambda ver, f: f"versions/{ver}/{f}"  # noqa: E731
    won = None
    for i in range(1, SHRINK_PASSES + 1):  # a safety bound, not a target: shrinking usually fails before this
        best = st["best"]
        cand = "vS" if i == 1 else f"vS{i}"
        if not run.read(V(cand, "chunks.json")):
            summ = {"mode": "simplify", "rewrite_brief": "", "checklist": checklist, "summary": "",
                    "overview": prompts.render("simplify_overview")}
            chunks, gen, problems = agents.generate(run.read(V(best, "chunks.json")), summ, "(none)",
                                                    run.read("dialogue.md", ""), v0_words=words("v0"), editable=editable, **gm)
            if problems:
                debug(run, f"--- simplify pass skipped: {'; '.join(problems)}")
                break
            run.write(V(cand, "chunks.json"), chunks)
            run.write(V(cand, "prompt.md"), agents.assemble(chunks))
            st["changes"][cand] = {"parent": best, "realisation": "", "summary": gen["summary"], "edits": gen["edits"],
                                   "rewrite": [], "problems": []}
        if run.read(V(cand, "scores.json")) is None:
            run.write(V(cand, "scores.json"), score_items(run.read(V(cand, "prompt.md"))))
        # shorter is kept while the exact matches hold (and the gap does not slip)
        kept = (metrics(cand).get("exact", 0) >= metrics(best).get("exact", 0)
                and metrics(cand).get("mae", 1e9) <= metrics(best).get("mae", 1e9) and words(cand) < words(best))
        ev("version.scored", version=cand, numbers=N(cand))
        ev("version.verdict", version=cand, parent=best, verdict="kept" if kept else "rejected", numbers=N(cand),
           best_before={"version": best, "numbers": N(best)}, closer=0, further=0, words=words(cand),
           reason="shrink pass: same accuracy, fewer words" if kept else "shrink pass cost accuracy or was not shorter")
        # a resumed run may find the candidate's chunks on disk while state.json predates them
        st["changes"].setdefault(cand, {"parent": best, "realisation": "", "summary": "", "edits": [],
                                        "rewrite": [], "problems": []})
        st["changes"][cand].update(verdict="KEPT" if kept else "REJECTED", words=words(cand))
        if cand not in st["versions"]:
            st["versions"].append(cand)
        if kept:
            st["best"] = cand
            won = cand
        run.write("state.json", st)
        debug(run, f"--- {cand} (shrink {i}) {'KEPT' if kept else 'REJECTED'} · {numbers(metrics(cand), out)} · "
                   f"{words(cand)} words (best had {words(best)})")
        if not kept:
            break
    run.write("state.json", st)
    return won


def refine(run: Run, a, setup: dict, items: list[dict], editable: tuple[str, ...] = (agents.EDITABLE,)) -> str:
    """The loop for one metric: score, review, diagnose, edit, gate — until a stop rule fires, then one simplify
    pass. `editable` names the layers this loop may change. Returns the best version."""
    out = setup["output"]
    kind = agents.kind_of(setup, out)  # feedback mode: errors measure verdict satisfaction
    truths = {it["id"]: reference(it["truth"], out) for it in items}
    refs = {i: v for i, v in truths.items() if v is not None}
    # the split: everything below — scoring, notes, checklist, gate, stop rules — sees train only. Test items are
    # scored once at the very end (score_test) and never before; score_items refuses them.
    sp = split.read(run)
    train, test = split.part(items, sp["train"]), split.part(items, sp["test"])
    test_ids = {it["id"] for it in test}
    refs_train, refs_test = split.filter_refs(refs, sp["train"]), split.filter_refs(refs, sp["test"])
    jm = dict(model=a.judge_model, effort=a.effort)
    gm = dict(model=a.generator_model, effort=a.effort)
    mkey = run.label or agents.metrics_of(setup)[0]["key"]
    ev = lambda type, **d: events.emit((run.parent or run).dir, type, mkey, **d)  # noqa: E731  events go to the chat's run
    V = lambda ver, f: f"versions/{ver}/{f}"  # noqa: E731

    def score_items(prompt: str, subset: list[dict] | None = None, raw: dict | None = None) -> dict:
        """Score train items (or a subset of them) with a prompt; a test item here is a bug."""
        subset = train if subset is None else subset
        split.guard(subset, test_ids)
        return agents.score(prompt, subset, out, schema=setup.get("output_schema"), raw=raw, model=a.scorer,
                            effort=a.scorer_effort, workers=a.workers)

    def scored(ver: str) -> dict:
        if run.read(V(ver, "scores.json")) is None:
            answers: dict = {}
            run.write(V(ver, "scores.json"), score_items(run.read(V(ver, "prompt.md")), raw=answers))
            run.write(V(ver, "outputs.json"), answers)
        return run.read(V(ver, "scores.json"))

    def reviewed(ver: str, subset: list[dict] | None = None) -> dict:
        if run.read(V(ver, "notes.json")) is None:
            todo, preds = train if subset is None else subset, scored(ver)  # score first
            run.write(V(ver, "notes.json"), agents.review(agents.annotated(run.read(V(ver, "chunks.json")), editable), todo,
                                                          preds, truths, out, workers=a.workers, **jm))
        return run.read(V(ver, "notes.json"))

    words = lambda ver: agents.editable_words(run.read(V(ver, "chunks.json")), editable)  # noqa: E731  this loop's text
    E = lambda ver: M.item_errors(scored(ver), refs_train, kind)  # noqa: E731  train errors
    metrics = lambda ver: M.alignment(E(ver), None, kind)  # noqa: E731
    N = lambda ver: M.summary(E(ver), kind)  # noqa: E731  the numbers in every version event (train)

    def score_test(versions: list[str]) -> dict[str, dict]:
        """The one scoring of the held-out items, after the loop has stopped: v0 and the best version, each once.
        Writes versions/<v>/scores_test.json and outputs_test.json; returns version -> numbers on test."""
        numbers_of = {}
        for ver in versions:
            if run.read(V(ver, "scores_test.json")) is None:
                answers: dict = {}
                run.write(V(ver, "scores_test.json"), agents.score(run.read(V(ver, "prompt.md")), test, out, schema=setup.get("output_schema"),
                                                                   raw=answers, model=a.scorer, effort=a.scorer_effort, workers=a.workers))
                run.write(V(ver, "outputs_test.json"), answers)
            numbers_of[ver] = M.summary(M.item_errors(run.read(V(ver, "scores_test.json")), refs_test, kind), kind)
        return numbers_of


    st = run.read("state.json") or {"round": 0, "best": "v0", "fails": 0, "versions": ["v0"], "by_item": {},
                                     "last_change": prompts.render("last_change_baseline"), "rounds": [], "changes": {}}
    checklist = run.read("checklist.json", {})

    def version_row(ver: str) -> dict:
        c = st["changes"].get(ver, {})
        return {"version": ver, "verdict": c.get("verdict", "baseline"), "from": c.get("parent", ""), **metrics(ver),
                "closer": len(c.get("closer", [])), "further": len(c.get("further", [])),
                "words": len(run.read(V(ver, "prompt.md")).split()), "metric_words": words(ver)}

    part_of = {it["id"]: ("test" if it["id"] in test_ids else "train") for it in items}
    both = lambda ver, name: {**run.read(V(ver, name), {}), **run.read(V(ver, name.replace(".json", "_test.json")), {})}  # noqa: E731

    def write_version_excel(ver: str) -> None:
        excel.write(run.dir / V(ver, "result.xlsx"),
                    excel.version_sheets(ver, version_row(ver), train, scored(ver), refs_train, E(ver), run.read(V(ver, "notes.json"), {}),
                                         run.read(V(ver, "chunks.json")), st["changes"].get(ver)))

    def write_run_excel() -> None:
        vs = [v for v in st["versions"] if run.read(V(v, "scores.json")) is not None]
        best = st["best"]
        agreement = [(f"{out['field']} · train", M.agreement(E(best), kind))]
        if run.read(V(best, "scores_test.json")) is not None:
            agreement.append((f"{out['field']} · test (held out)", M.agreement(M.item_errors(run.read(V(best, "scores_test.json")), refs_test, kind), kind)))
        excel.write(run.dir / "results.xlsx",
                    {"Results": excel.results_rows(items, both(best, "outputs.json"), setup, read_sheet(Path(a.sheet), a.sheet_name)),
                     "Agreement": excel.agreement_rows(agreement),
                     **excel.run_sheets([version_row(v) for v in vs], items, refs, {v: both(v, "scores.json") for v in vs}, best,
                                        M.item_errors(both(best, "scores.json"), refs, kind),
                                        {v: run.read(V(v, "notes.json"), {}) for v in vs}, checklist, st["rounds"], st["changes"], part_of)})
        run.write("final_prompt.md", run.read(V(best, "prompt.md")))

    while True:
        best, rnd0 = st["best"], st["round"]
        if not st.get("baseline_sent"):
            ev("version.scored", version="v0", numbers=N("v0"))
            ev("version.verdict", version="v0", parent=None, verdict="baseline", numbers=N("v0"), best_before=None,
               closer=0, further=0)
            st["baseline_sent"] = True
        rv = reviewed(best)
        errs = E(best)
        if not (run.dir / V(best, "result.xlsx")).exists():
            write_version_excel(best)

        # ---- judge: holistic diagnosis + checklist ----
        summ = agents.summarise(agents.annotated(run.read(V(best, "chunks.json")), editable), best, st["versions"], rv, errs, out,
                                st["last_change"], numbers(metrics(best), out), checklist, **jm)
        bad = [x for x in summ["issues"] if not x.get("title")]
        if bad:
            debug(run, f"judge returned {len(bad)} issue(s) without all fields: {json.dumps(bad)[:400]}")
        update_checklist(checklist, summ["issues"], rnd0, best, errs, set(refs_train))
        run.write("checklist.json", checklist)
        ev("judge.done", round=rnd0, version=best, mode=summ["mode"], overview=str(summ.get("overview", ""))[:700],
           issues=[{"id": k, "title": c.get("title", ""), "direction": c.get("direction", ""), "status": c["status"],
                    "items": len(c.get("items", []))} for k, c in checklist.items()])
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
                        f"   clause: {' '.join(x['clause'].split())[:160]}\n   why: {x['why']}\n" for x in summ["locked"]))
        run.write("state.json", st)
        write_run_excel()

        mae_best = metrics(best).get("mae", 1e9)
        over = a.budget is not None and spend.total() >= a.budget
        why = (f"ceiling — {a.rounds} round{'s' * (a.rounds != 1)}" if rnd0 >= a.rounds
               else f"target reached — MAE {mae_best} ≤ {a.target}" if a.target is not None and mae_best <= a.target
               else f"no improvement in {a.patience} rounds" if st["fails"] >= a.patience
               else f"budget reached — spent ${spend.total():.2f} of ${a.budget:.2f}" if over
               else None)
        if why:
            if over:  # the shrink loop is more rounds of model calls; over budget, the best version stands as it is
                debug(run, f"--- shrink loop skipped: budget reached (${spend.total():.2f} of ${a.budget:.2f})")
            best = (None if over else simplify(run, a, st, checklist, score_items, out, editable, words, metrics, N, ev, gm)) or best
            # why the loop stopped where it did, in plain language, measured by code (math_tool.diagnose)
            flips = flip_n = 0
            for v in st["versions"]:
                s2 = run.read(V(v, "scores2.json"))
                if s2 is not None:
                    e1, e2 = E(v), M.item_errors(s2, refs_train, kind)
                    shared = set(e1) & set(e2)
                    flips += sum(1 for i in shared if e1[i] != e2[i])
                    flip_n += len(shared)
            diag = M.diagnose(E(st["best"]), refs_train, metrics("v0").get("exact", 0), metrics(st["best"]).get("exact", 0),
                              rnd0, sum(1 for c in st["changes"].values() if c.get("verdict") == "KEPT"),
                              flips if flip_n else None, flip_n)
            st["diagnosis"] = diag
            run.write("state.json", st)
            ev("metric.diagnosis", note=diag["note"], action=diag["action"], signals=diag["signals"])
            debug(run, f"--- diagnosis: {diag['note']}")
            ev("metric.stopped", best=best, reason=why, rounds=rnd0, numbers=N(best), spent=spend.total())
            # the held-out items, scored once now that the rubric is final: the out-of-sample numbers
            if test:
                with llm.uncapped():  # fixed-size end work: runs to completion even past the hard cap
                    t = score_test(sorted({"v0", st["best"]}))
                st["train"] = {"v0": N("v0"), st["best"]: N(st["best"])}
                st["test"] = t
                run.write("state.json", st)
                ev("metric.test", best=st["best"], train=st["train"], test=t, n_train=len(train), n_test=len(test))
                debug(run, f"--- held-out test ({len(test)} items): v0 {numbers(t['v0'], out)} → {st['best']} {numbers(t[st['best']], out)}"
                           f" · train: v0 {numbers(N('v0'), out)} → {st['best']} {numbers(N(st['best']), out)}")
            break

        # ---- author: next candidate ----
        rnd = rnd0 + 1
        cand = f"v{rnd}"
        ev("round.started", round=rnd, best=best)
        if not run.read(V(cand, "chunks.json")):
            issues_of: dict[str, list[str]] = {}
            for k, c in checklist.items():
                for i in c["items"]:
                    issues_of.setdefault(i, []).append(k)
            csv = agents.table(rv, errs, out, {i: " | ".join(h) for i, h in st["by_item"].items()}, issues_of)
            chunks, gen, problems = agents.generate(run.read(V(best, "chunks.json")), summ, csv, run.read("dialogue.md", ""),
                                                    v0_words=words("v0"), editable=editable, **gm)
            locked = [c for c in chunks if c["layer"] not in editable]
            assert locked == [c for c in run.read("setup/baseline/layout.json") if c["layer"] not in editable], "locked layer changed"
            run.write(V(cand, "chunks.json"), chunks)
            run.write(V(cand, "prompt.md"), agents.assemble(chunks))
            st["changes"][cand] = {"parent": best, "realisation": gen["realisation"], "summary": gen["summary"],
                                   "edits": gen["edits"] if summ["mode"] == "edit" else [],
                                   "rewrite": gen["rewrite"] if summ["mode"] == "rewrite" else [], "problems": problems}
            run.write("state.json", st)
            run.append("dialogue.md", f"\n## {cand} (from {best})\n[author] realisation: {gen['realisation']}\n[author] change: {gen['summary']}\n"
                       + "".join(f"  - {e['issue']} {e.get('op', 'replace')}: “{e['old_text'][:120]}” → “{e['new_text'][:400]}”\n"
                                 for e in st["changes"][cand]["edits"])
                       + (f"  (rewrote the {len(gen['rewrite'])} editable part(s) of the metrics layer)\n" if st["changes"][cand]["rewrite"] else "")
                       + (f"  (edits not applied: {'; '.join(problems)})\n" if problems else ""))
            debug(run, f"--- {cand} written from {best}: {gen['summary']}\nrealisation: {gen['realisation']}"
                  + (f"\nedits not applied: {'; '.join(problems)}" if problems else ""))
            ev("candidate.written", version=cand, parent=best, summary=gen["summary"],
               edits=len(st["changes"][cand]["edits"]), rewrite=bool(st["changes"][cand]["rewrite"]), problems=problems)

        ec = E(cand)
        ev("version.scored", version=cand, numbers=N(cand))
        # the gate (math_tool.keep_candidate): exact matches decide, measured twice — a first-pass winner is
        # scored once more and the pooled numbers (mean of both passes) give the verdict.
        mv = M.compare(errs, ec)

        def second_pass() -> tuple[dict, dict]:
            debug(run, f"--- {cand} ahead on the first pass: scoring once more to confirm")
            if run.read(V(cand, "scores2.json")) is None:
                run.write(V(cand, "scores2.json"), score_items(run.read(V(cand, "prompt.md"))))
            e2 = M.item_errors(run.read(V(cand, "scores2.json")), refs_train, kind)
            return M.alignment(e2, None, kind), M.compare(errs, e2)

        gate = decide(metrics(best).get("exact", 0), mae_best, metrics(cand), words(best), words(cand), mv, second_pass)
        kept = gate["kept"]
        verdict = "KEPT" if kept else "REJECTED"
        ev("version.verdict", version=cand, parent=best, verdict=verdict.lower(), numbers=N(cand), spent=spend.total(),
           best_before={"version": best, "numbers": N(best)}, closer=gate["closer"], further=gate["further"],
           words=words(cand), gain=gate["gain"], reason=gate["reason"])
        # kept: review everything (it is next round's best); rejected: only what it pushed further away
        notes = reviewed(cand, None if kept else [it for it in train if it["id"] in set(mv["further"])])
        notes = {i: notes.get(i, {}) for i in mv["further"]}
        tag = f"{cand} {verdict.lower()}"
        for i in mv["closer"]:
            st["by_item"].setdefault(i, []).append(f"{tag}: closer")
        for i in mv["further"]:
            n = notes.get(i, {})
            st["by_item"].setdefault(i, []).append(f"{tag}: further — {n.get('comment', '')[:200]} (clause: {n.get('clause', '')[:120]})")
        st["last_change"] = prompts.render(
            "last_change", cand=cand, best=best, verdict=verdict, reason=f" ({gate['reason']})" if gate["reason"] else "",
            words=words(cand), best_words=words(best), v0_words=words("v0"),
            items="\n".join(prompts.render("last_change_item", id=i, direction=n.get("direction", ""), clause=n.get("clause", "")[:160],
                                           comment=n.get("comment", "")) for i, n in notes.items()))
        st["changes"].setdefault(cand, {"parent": best, "realisation": "", "summary": "", "edits": [], "rewrite": [], "problems": []})
        st["changes"][cand].update(verdict=verdict, closer=list(mv["closer"]), further=list(mv["further"]), words=words(cand),
                                   gate=gate)
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
        debug(run, f"--- {cand} {verdict}{' (' + gate['reason'] + ')' if gate['reason'] else ''} · {numbers(metrics(cand), out)} · "
                   f"{words(cand)} words (+{gate['added_words']}), gain {gate['gain']}, moves {gate['closer']}/{gate['further']} · "
                   f"closer {', '.join(mv['closer']) or '-'} · further {', '.join(mv['further']) or '-'}")
        print(f"{run.label + ' ' if run.label else ''}r{rnd:02d} {cand} {verdict} · {numbers(metrics(cand), out)} · spent ${spend.total():.2f}", flush=True)

    write_run_excel()
    debug(run, f"=== STOP: {why} · best {st['best']} · spent ${spend.total():.2f} → {run.dir / 'final_prompt.md'}\n")
    print(f"{run.label + ' ' if run.label else ''}STOP: {why} · best {st['best']} · spent ${spend.total():.2f} · {run.dir / 'results.xlsx'}")
    return st["best"]
