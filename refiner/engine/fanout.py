"""Fan-out: a rubric that scores several metrics. Each metric is refined on its own, in parallel, then composed.

runs/<run>/
  setup/              the parser's setup for every metric; items.json holds each item's reference for every metric;
                      split.json the train/test ids (every stage tunes on train; test is scored once at the end)
  metrics/<key>/      one ordinary run folder per metric (same files as a single-metric run); its prompt is the
                      locked layers plus that metric's own section, so its loop sees and edits nothing else
  composed/baseline/  the original full prompt, scored once with every metric's field together (scores, outputs);
                      scores_test / outputs_test: the same prompt on the held-out items, scored once at the end
  composed/final/     each metric's best section stitched back into the original layout, scored the same way; after
                      polish, the polished layout's held-out scores (scores_test, outputs_test)
  polish/             the composed stage: rounds that edit the weakest target (a metric's section, or the
                      procedure layer every second round) against the WHOLE prompt's score (versions p0, p1, …)
  composed.json       per metric: alone v0 → best, together baseline → final (train), together_test (held out);
                      a hash of each scored prompt
  final_prompt.md     the polish stage's best layout (the composer's, when polish found nothing better)
  results.xlsx        Results (inputs + the composed prompt's full output, one column per key) · Agreement (train,
                      and test once scored) · Metrics (alone v0 → best, together v0 → final) · Items (split,
                      reference, v0, final per metric)

The composer is code, not a model: it puts each metric's best section in place of the original one, so the program,
notes and output layers stay word for word, then runs the evaluation once on the whole prompt.
"""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import agents, prompts
from ..agents import llm, spend
from ..agents import math_tool as M
from ..utils import excel
from ..utils.excel import read_sheet
from . import events, report, split
from .loop import Run, debug, decide, numbers, refine, update_checklist

EDITABLE = agents.EDITABLE

# stage knobs (not RunConfig options yet): the shared stage and the polish stage are short by design
PROCEDURE_ROUNDS = 2   # rounds tuning the shared procedure layer before the per-metric loops
POLISH_ROUNDS = 3      # rounds on the composed prompt after the per-metric loops
STAGE_PATIENCE = 2     # rejected rounds in a row that stop either stage


def base_layout(run: Run) -> list[dict]:
    """The layout the per-metric loops and the composer start from: the procedure stage's best, else the baseline."""
    return run.read("procedure/best_layout.json") or run.read("setup/baseline/layout.json")


def metric_subrun(run: Run, setup: dict, items: list[dict], m: dict) -> tuple[Run, dict, list[dict]]:
    """The sub-run for metric `m`: a run folder whose setup and items hold only that metric. The prompt keeps the
    other metrics' sections in place, retagged `peer` (locked), so the scorer reads the rubric as production
    serves it and the loop still edits only its own section."""
    sub = Run(run.dir / "metrics" / m["key"], label=m["key"], parent=run)
    if not sub.read("versions/v0/chunks.json"):
        chunks = [c if c["layer"] != EDITABLE or c.get("metric") == m["key"] else {**c, "layer": "peer"}
                  for c in base_layout(run)]
        sub.write("setup/setup.json", {**{k: v for k, v in setup.items() if k != "layers"}, "metrics": [m],
                                       "truth_column": m["truth_column"], "output": m["output"],
                                       "output_schema": _without_others(setup.get("output_schema"), setup, m)})
        sub.write("setup/items.json", [{**it, "truth": it["truths"][m["key"]],
                                         "rationale": it.get("rationales", {}).get(m["key"], "")} for it in items if it["truths"].get(m["key"]) is not None])
        sub.write("setup/baseline/layout.json", chunks)
        sub.write("versions/v0/chunks.json", chunks)
        sub.write("versions/v0/prompt.md", agents.assemble(chunks))
    if sub.read(split.FILE) is None and run.read(split.FILE) is not None:  # the same split as the parent run
        sub.write(split.FILE, run.read(split.FILE))
    return sub, sub.read("setup/setup.json"), sub.read("setup/items.json")


def _without_others(schema: dict | None, setup: dict, m: dict) -> dict | None:
    """The operator's output schema minus the other metrics' output fields: a metric's prompt has no rubric for them."""
    if not schema:
        return None
    drop = {x["output"]["field"] for x in agents.metrics_of(setup) if x["key"] != m["key"]}
    return {**schema, "properties": {k: v for k, v in schema.get("properties", {}).items() if k not in drop},
            "required": [k for k in schema.get("required", []) if k not in drop]}


def refine_procedure(run: Run, a, setup: dict, items: list[dict]) -> None:
    """The shared stage before the per-metric loops: tune the `procedure` layer (band gates, decision order,
    tie-breaks) as a whole. Each round scores the full prompt once (every metric, as in production), reads the
    misses across all metric–item pairs, and the generator edits only the procedure chunks; the usual gate decides.
    Writes procedure/best_layout.json, which the per-metric loops and the composer then start from."""
    layout = run.read("setup/baseline/layout.json")
    if not any(c["layer"] == agents.PROCEDURE for c in layout):
        return
    sub = Run(run.dir / "procedure", label="procedure", parent=run)
    items = split.part(items, split.read(run)["train"])  # this stage tunes on train only
    ed = (agents.PROCEDURE,)
    outs = {m["key"]: m["output"] for m in agents.metrics_of(setup)}
    kinds = {o["type"] for o in outs.values()}
    kind = "verdict" if setup.get("feedback") else kinds.pop() if len(kinds) == 1 else "number"
    refs_by = agents.refs_by(items, outs)
    n_pairs = sum(len(r) for r in refs_by.values())
    ev = lambda type, **d: events.emit(run.dir, type, "procedure", **d)  # noqa: E731
    V = lambda ver, f: f"versions/{ver}/{f}"  # noqa: E731
    jm, gm = dict(model=a.judge_model, effort=a.effort), dict(model=a.generator_model, effort=a.effort)

    if not sub.read(V("v0", "chunks.json")):
        sub.write(V("v0", "chunks.json"), layout)
        sub.write(V("v0", "prompt.md"), agents.assemble(layout))

    def scored(ver: str, second: bool = False) -> dict:
        name = "scores2.json" if second else "scores.json"
        if sub.read(V(ver, name)) is None:
            sub.write(V(ver, name), agents.score_all(sub.read(V(ver, "prompt.md")), items, outs, a.scorer, a.scorer_effort,
                                                     a.workers, schema=setup.get("output_schema")))
        return sub.read(V(ver, name))

    def errors_of(sc: dict) -> dict:
        return {f"{k}:{i}": e for k in outs for i, e in M.item_errors(sc[k], refs_by[k], agents.kind_of(setup, outs[k])).items()}

    E = lambda ver: errors_of(scored(ver))  # noqa: E731
    mae = lambda ver: M.alignment(E(ver), None, kind).get("mae", 1e9)  # noqa: E731
    N = lambda ver: M.summary(E(ver), kind)  # noqa: E731
    words = lambda ver: agents.editable_words(sub.read(V(ver, "chunks.json")), ed)  # noqa: E731

    st = sub.read("state.json") or {"round": 0, "best": "v0", "fails": 0, "versions": ["v0"], "changes": {}, "sent": False}
    checklist = sub.read("checklist.json", {})
    out_t = {"type": kind}
    rounds = min(PROCEDURE_ROUNDS, a.rounds)  # the polish stage retunes the procedure at the end
    while True:
        best, rnd0 = st["best"], st["round"]
        if not st["sent"]:
            ev("version.scored", version="v0", numbers=N("v0"))
            ev("version.verdict", version="v0", parent=None, verdict="baseline", numbers=N("v0"), best_before=None,
               closer=0, further=0)
            st["sent"] = True
            sub.write("state.json", st)
        over = a.budget is not None and spend.total() >= a.budget
        if rnd0 >= rounds or st["fails"] >= STAGE_PATIENCE or over:
            run.write("procedure/best_layout.json", sub.read(V(best, "chunks.json")))
            ev("metric.stopped", best=best, reason=(f"budget reached — spent ${spend.total():.2f} of ${a.budget:.2f}" if over
                                                    else f"shared stage done after {rnd0} round{'s' * (rnd0 != 1)}"),
               rounds=rnd0, numbers=N(best), spent=spend.total())
            debug(run, f"procedure stage done: best {best} · {words(best)} words")
            return
        errs = E(best)
        reviews = agents.synthetic_reviews(errs)
        summ = agents.summarise(agents.annotated(sub.read(V(best, "chunks.json")), ed), best, st["versions"], reviews,
                                errs, out_t, st.get("last_change", prompts.render("last_change_shared")),
                                numbers(M.alignment(errs, None, kind), out_t), checklist, **jm)
        update_checklist(checklist, summ["issues"], rnd0, best, errs, set(errs) | {p for k in outs for p in
                                                                                   (f"{k}:{i}" for i in refs_by[k])})
        sub.write("checklist.json", checklist)
        ev("judge.done", round=rnd0, version=best, mode="edit", overview=str(summ.get("overview", ""))[:700],
           issues=[{"id": k, "title": c.get("title", ""), "direction": c.get("direction", ""), "status": c["status"],
                    "items": len(c.get("items", []))} for k, c in checklist.items()])
        summ["mode"], summ["checklist"] = "edit", checklist  # the shared stage always edits, never rewrites
        rnd, cand = rnd0 + 1, f"v{rnd0 + 1}"
        ev("round.started", round=rnd, best=best)
        if not sub.read(V(cand, "chunks.json")):
            csv = agents.table(reviews, errs, out_t)
            chunks, gen, problems = agents.generate(sub.read(V(best, "chunks.json")), summ, csv,
                                                    sub.read("dialogue.md", ""), v0_words=words("v0"), editable=ed, **gm)
            locked = [c for c in chunks if c["layer"] not in ed]
            assert locked == [c for c in layout if c["layer"] not in ed], "a locked layer changed in the shared stage"
            sub.write(V(cand, "chunks.json"), chunks)
            sub.write(V(cand, "prompt.md"), agents.assemble(chunks))
            st["changes"][cand] = {"parent": best, "summary": gen["summary"], "edits": gen["edits"], "problems": problems}
            sub.append("dialogue.md", f"\n## {cand} (from {best})\n[author] {gen['summary']}\n")
            ev("candidate.written", version=cand, parent=best, summary=gen["summary"], edits=len(gen["edits"]),
               rewrite=False, problems=problems)
        ec = errors_of(scored(cand))
        ev("version.scored", version=cand, numbers=N(cand))
        mv = M.compare(errs, ec)
        second = lambda: (lambda e2: (M.alignment(e2, None, kind), M.compare(errs, e2)))(errors_of(scored(cand, second=True)))  # noqa: E731
        gate = decide(M.alignment(errs, None, kind).get("exact", 0), mae(best), M.alignment(ec, None, kind), words(best), words(cand), mv, second)
        kept = gate["kept"]
        ev("version.verdict", version=cand, parent=best, verdict="kept" if kept else "rejected", numbers=N(cand),
           best_before={"version": best, "numbers": N(best)}, closer=gate["closer"], further=gate["further"],
           words=words(cand), gain=gate["gain"], reason=gate["reason"])
        # a resumed run may find the candidate's chunks on disk while state.json predates them
        st["changes"].setdefault(cand, {"parent": best, "summary": "", "edits": [], "problems": []})
        st["changes"][cand].update(verdict="KEPT" if kept else "REJECTED", words=words(cand))
        st["last_change"] = f"{cand} was {'KEPT' if kept else 'REJECTED'}" + (f" ({gate['reason']})" if gate["reason"] else "")
        sub.append("dialogue.md", f"[result] {cand} {'KEPT' if kept else 'REJECTED'} · {st['last_change']}\n")
        if cand not in st["versions"]:
            st["versions"].append(cand)
        st["round"], st["fails"] = rnd, (0 if kept else st["fails"] + 1)
        if kept:
            st["best"] = cand
        sub.write("state.json", st)
        debug(run, f"procedure {cand} {'KEPT' if kept else 'REJECTED'} · pairs MAE {M.alignment(ec, None, kind).get('mae')} · "
                   f"{words(cand)} words · moves {gate['closer']}/{gate['further']}")
        print(f"procedure r{rnd:02d} {cand} {'KEPT' if kept else 'REJECTED'}", flush=True)


def main(run: Run, a, setup: dict, items: list[dict]) -> dict:
    refine_procedure(run, a, setup, items)
    subs = [metric_subrun(run, setup, items, m) for m in agents.metrics_of(setup)]
    debug(run, f"=== FAN-OUT · {len(subs)} metrics in parallel: " + ", ".join(
        f"{s[0].label} ({s[1]['truth_column']} → {s[1]['output']['field']}, {len(s[2])} items)" for s in subs))
    with ThreadPoolExecutor(len(subs)) as ex:  # one loop per metric, side by side
        best = dict(zip([s[0].label for s in subs], ex.map(lambda s: refine(s[0], a, s[1], s[2]), subs)))
    from .run import finish  # the cost line (run.py imports fanout; a lazy import avoids the cycle)
    if any((s[0].read("state.json") or {}).get("paused") for s in subs):  # --pause-after: the loops wait, no end work
        debug(run, f"=== PAUSED after round {a.pause_after}: no composer, polish or test pass; rerun to continue")
        finish(run)
        return best
    with llm.uncapped():  # the loops have stopped: the fixed-size end work runs to completion even past the hard cap
        compose(run, a, setup, items, [s[0] for s in subs])
        polish(run, a, setup, items)  # a loop, but it stops at its next round boundary once over budget
        test_pass(run, a, setup, items)
    finish(run)
    report.write(run, a, setup, items)
    return best


def polish(run: Run, a, setup: dict, items: list[dict], rounds: int = POLISH_ROUNDS) -> None:
    """The composed stage after the composer: what a section loses inside the full prompt is re-earned here.
    Each round scores the whole prompt (every metric together, as in production), picks the weakest target —
    the metric with the lowest share of exact matches, or the procedure layer — and the generator edits only
    that target's text. The usual gate decides on the TOTAL exact matches over all metric–item pairs, measured
    twice. The best layout becomes final_prompt.md."""
    sub = Run(run.dir / "polish", label="polish", parent=run)
    layout = run.read("composed/final/layout.json")
    if not layout:
        return
    items = split.part(items, split.read(run)["train"])  # the composed stage tunes on train only
    outs = {m["key"]: m["output"] for m in agents.metrics_of(setup)}
    kinds = {o["type"] for o in outs.values()}
    kind = "verdict" if setup.get("feedback") else kinds.pop() if len(kinds) == 1 else "number"
    refs_by = agents.refs_by(items, outs)
    ev = lambda type, **d: events.emit(run.dir, type, "polish", **d)  # noqa: E731
    V = lambda ver, f: f"versions/{ver}/{f}"  # noqa: E731
    gm = dict(model=a.generator_model, effort=a.effort)
    has_proc = any(c["layer"] == agents.PROCEDURE for c in layout)

    if not sub.read(V("p0", "chunks.json")):
        sub.write(V("p0", "chunks.json"), layout)
        sub.write(V("p0", "prompt.md"), agents.assemble(layout))
        if run.read("composed/final/scores.json") is not None:  # the composer already scored this exact prompt
            sub.write(V("p0", "scores.json"), run.read("composed/final/scores.json"))

    def scored(ver: str, second: bool = False) -> dict:
        name = "scores2.json" if second else "scores.json"
        if sub.read(V(ver, name)) is None:
            sub.write(V(ver, name), agents.score_all(sub.read(V(ver, "prompt.md")), items, outs, a.scorer, a.scorer_effort,
                                                     a.workers, schema=setup.get("output_schema")))
        return sub.read(V(ver, name))

    kd = lambda k: agents.kind_of(setup, outs[k])  # noqa: E731

    def by_metric(sc: dict) -> dict:
        return {k: M.alignment(M.item_errors(sc[k], refs_by[k], kd(k)), None, kd(k)) for k in outs}

    def errors_of(sc: dict) -> dict:
        return {f"{k}:{i}": e for k in outs for i, e in M.item_errors(sc[k], refs_by[k], kd(k)).items()}

    total = lambda sc: sum(x.get("exact", 0) for x in by_metric(sc).values())  # noqa: E731
    words = lambda ver: agents.editable_words(sub.read(V(ver, "chunks.json")), (EDITABLE, agents.PROCEDURE))  # noqa: E731

    st = sub.read("state.json") or {"round": 0, "best": "p0", "fails": 0, "sent": False}
    while True:
        best, rnd0 = st["best"], st["round"]
        if not st["sent"]:
            e0 = errors_of(scored(best))
            ev("version.scored", version="p0", numbers=M.summary(e0, kind))
            ev("version.verdict", version="p0", parent=None, verdict="baseline", numbers=M.summary(e0, kind),
               best_before=None, closer=0, further=0)
            st["sent"] = True
            sub.write("state.json", st)
        over = a.budget is not None and spend.total() >= a.budget
        if rnd0 >= rounds or st["fails"] >= STAGE_PATIENCE or over:
            run.write("final_prompt.md", agents.assemble(sub.read(V(best, "chunks.json"))))
            run.write("composed/final/layout.json", sub.read(V(best, "chunks.json")))
            ev("metric.stopped", best=best, reason=(f"budget reached — spent ${spend.total():.2f} of ${a.budget:.2f}" if over
                                                    else f"polish done after {rnd0} round{'s' * (rnd0 != 1)}"),
               rounds=rnd0, numbers=M.summary(errors_of(scored(best)), kind), spent=spend.total())
            debug(run, f"polish done: best {best} · total exact {total(scored(best))}")
            return
        sc = scored(best)
        per = by_metric(sc)
        # the weakest target: the metric with the lowest share of exact matches; every second round the
        # procedure layer, when there is one, so the shared rules get their late tuning too
        worst = min(outs, key=lambda k: per[k].get("exact", 0) / max(per[k].get("n", 1), 1))
        target = agents.PROCEDURE if has_proc and rnd0 % 2 == 1 else worst
        ed = (agents.PROCEDURE,) if target == agents.PROCEDURE else (EDITABLE,)
        rnd, cand = rnd0 + 1, f"p{rnd0 + 1}"
        ev("round.started", round=rnd, best=best)
        if not sub.read(V(cand, "chunks.json")):
            base = sub.read(V(best, "chunks.json"))
            # the generator may only touch the target: other metrics' sections ride along as locked peers
            view = ([c for c in base] if target == agents.PROCEDURE
                    else [c if c["layer"] != EDITABLE or c.get("metric") == target else {**c, "layer": "peer"}
                          for c in base])
            errs = {p: e for p, e in errors_of(sc).items()
                    if target == agents.PROCEDURE or p.startswith(f"{target}:")}
            reviews = agents.synthetic_reviews(errs)
            summ = {"mode": "edit", "rewrite_brief": "", "checklist": {}, "summary": "",
                    "overview": prompts.render("polish_overview", target=target)}
            chunks, gen, problems = agents.generate(view, summ, agents.table(reviews, errs, {"type": kind}),
                                                    sub.read("dialogue.md", ""), v0_words=words("p0"), editable=ed, **gm)
            chunks = [{**c, "layer": EDITABLE} if c["layer"] == "peer" else c for c in chunks]
            locked = [c["text"] for c in chunks if c["layer"] not in ed or
                      (target != agents.PROCEDURE and c.get("metric") != target)]
            held = [c["text"] for c in base if c["layer"] not in ed or
                    (target != agents.PROCEDURE and c.get("metric") != target)]
            assert locked == held, "polish touched text outside its target"
            sub.write(V(cand, "chunks.json"), chunks)
            sub.write(V(cand, "prompt.md"), agents.assemble(chunks))
            sub.append("dialogue.md", f"\n## {cand} (from {best}, target {target})\n[author] {gen['summary']}\n")
            ev("candidate.written", version=cand, parent=best, summary=f"[{target}] {gen['summary']}",
               edits=len(gen["edits"]), rewrite=False, problems=problems)
        ec = scored(cand)
        e_best, e_cand = errors_of(sc), errors_of(ec)
        ev("version.scored", version=cand, numbers=M.summary(e_cand, kind))
        mv = M.compare(e_best, e_cand)
        # the gate here counts exact matches over every metric–item pair (the whole prompt), MAE over the pairs
        first = {"exact": total(ec), "mae": M.alignment(e_cand, None, kind).get("mae", 1e9)}

        def second_pass() -> tuple[dict, dict]:
            sc2 = scored(cand, second=True)
            e2 = errors_of(sc2)
            return {"exact": total(sc2), "mae": M.alignment(e2, None, kind).get("mae", 1e9)}, M.compare(e_best, e2)

        gate = decide(total(sc), M.alignment(e_best, None, kind).get("mae", 1e9), first, words(best), words(cand), mv, second_pass)
        kept = gate["kept"]
        ev("version.verdict", version=cand, parent=best, verdict="kept" if kept else "rejected",
           numbers=M.summary(errors_of(ec), kind), best_before={"version": best, "numbers": M.summary(e_best, kind)},
           closer=gate["closer"], further=gate["further"], words=words(cand), gain=gate["gain"], reason=gate["reason"])
        sub.append("dialogue.md", f"[result] {cand} {'KEPT' if kept else 'REJECTED'}"
                                  + (f" ({gate['reason']})" if gate["reason"] else "") + "\n")
        st["round"], st["fails"] = rnd, (0 if kept else st["fails"] + 1)
        if kept:
            st["best"] = cand
        sub.write("state.json", st)
        debug(run, f"polish {cand} ({target}) {'KEPT' if kept else 'REJECTED'} · total exact {total(ec)} vs {total(sc)}")
        print(f"polish r{rnd:02d} {cand} ({target}) {'KEPT' if kept else 'REJECTED'}", flush=True)


def compose(run: Run, a, setup: dict, items: list[dict], subs: list[Run]) -> dict:
    """Stitch every metric's best section into the original layout and score the whole prompt once, against v0."""
    ms = agents.metrics_of(setup)
    outs = {m["key"]: m["output"] for m in ms}
    sp = split.read(run)
    train, test_ids = split.part(items, sp["train"]), set(sp["test"])
    refs = agents.refs_by(train, outs)
    layout = base_layout(run)
    best, parts = {}, {}
    for sub in subs:
        best[sub.label] = sub.read("state.json")["best"]
        chunks = sub.read(f"versions/{best[sub.label]}/chunks.json")
        assert [c for c in chunks if c["layer"] not in (EDITABLE, "peer")] == \
               [c for c in layout if c["layer"] != EDITABLE], "locked layer changed"
        peers = [c["text"] for c in chunks if c["layer"] == "peer"]  # older sub-runs carry no peer chunks
        assert not peers or peers == [c["text"] for c in layout if c["layer"] == EDITABLE
                                      and c.get("metric") != sub.label], "a peer section changed"
        parts[sub.label] = iter([c for c in chunks if c["layer"] == EDITABLE])
    final = [next(parts[c["metric"]]) if c["layer"] == EDITABLE else c for c in layout]

    scored_with = (run.read("composed.json") or {}).get("prompt_sha", {})
    kind_of = lambda k: agents.kind_of(setup, outs[k])  # noqa: E731

    def measure(name: str, chunks: list[dict]) -> dict:
        d, prompt = f"composed/{name}", agents.assemble(chunks)
        sha = hashlib.sha256(prompt.encode()).hexdigest()
        if scored_with.get(name) != sha or run.read(f"{d}/scores.json") is None:  # the prompts live in setup/ and final_prompt.md
            scored_with[name] = sha
            answers: dict = {}
            split.guard(train, test_ids)
            run.write(f"{d}/scores.json", agents.score_all(prompt, train, outs, schema=setup.get("output_schema"), model=a.scorer, effort=a.scorer_effort,
                                                           workers=a.workers, raw=answers))
            run.write(f"{d}/outputs.json", answers)
        sc = run.read(f"{d}/scores.json")
        return {k: M.summary(M.item_errors(sc[k], refs[k], kind_of(k)), kind_of(k)) for k in outs}

    together = {"baseline": measure("baseline", layout), "final": measure("final", final)}

    summary, rows = [], {}
    for sub in subs:
        k = sub.label
        alone = lambda v: M.alignment(M.item_errors(sub.read(f"versions/{v}/scores.json"), refs[k], kind_of(k)), None, kind_of(k))  # noqa: E731
        st = sub.read("state.json")
        row = {"metric": k, "field": outs[k]["field"], "rounds": st["round"], "best": best[k]}
        for label, x in (("alone v0", alone("v0")), ("alone best", alone(best[k])), ("together v0", together["baseline"][k]),
                         ("together final", together["final"][k])):
            row.update({f"{label} · {n}": v for n, v in x.items() if n not in ("n", "exact")})
        summary.append(row)
    sc = {n: run.read(f"composed/{n}/scores.json") for n in together}
    for it in items:
        rows[it["id"]] = {"id": it["id"], "split": "test" if it["id"] in test_ids else "train", **{f"{k} · {col}": v for k in outs for col, v in
                                            (("reference", refs[k].get(it["id"])), ("v0", sc["baseline"][k].get(it["id"])),
                                             ("final", sc["final"][k].get(it["id"])))}}
    run.write("final_prompt.md", agents.assemble(final))
    run.write("composed/final/layout.json", final)
    run.write("composed.json", {"best": best, "together": together, "prompt_sha": scored_with})
    fin = run.read("composed/final/scores.json")
    excel.write(run.dir / "results.xlsx", {
        "Results": excel.results_rows(items, run.read("composed/final/outputs.json", {}), setup, read_sheet(Path(a.sheet), a.sheet_name)),
        "Agreement": excel.agreement_rows([(f"{outs[k]['field']} · train", M.agreement(M.item_errors(fin[k], refs[k], kind_of(k)), kind_of(k)))
                                           for k in outs]),
        "Metrics": summary, "Items": list(rows.values())})
    for k in outs:
        line = f"{k}: together v0 {numbers(together['baseline'][k], outs[k])} → final {numbers(together['final'][k], outs[k])}"
        debug(run, "=== COMPOSED " + line)
        print("COMPOSED " + line, flush=True)
    events.emit(run.dir, "composed", metrics={k: {"before": together["baseline"][k], "after": together["final"][k]} for k in outs})
    return together


def test_pass(run: Run, a, setup: dict, items: list[dict]) -> dict | None:
    """The one scoring of the held-out items, after every stage has stopped: the original prompt and the final
    layout (polished), each once, on test. Writes composed/{baseline,final}/scores_test.json (+ outputs_test.json),
    `together_test` into composed.json, the test rows of the Agreement sheet and the final test scores into Items,
    and emits `composed.test`. Nothing before this call ever scored a test item."""
    sp = split.read(run)
    test = split.part(items, sp["test"])
    if not test:
        return None
    ms = agents.metrics_of(setup)
    outs = {m["key"]: m["output"] for m in ms}
    kind_of = lambda k: agents.kind_of(setup, outs[k])  # noqa: E731
    refs = agents.refs_by(test, outs)
    composed = run.read("composed.json") or {}
    shas = composed.setdefault("prompt_sha", {})
    layouts = {"baseline": base_layout(run), "final": run.read("composed/final/layout.json")}

    def measure(name: str) -> dict:
        prompt = agents.assemble(layouts[name])
        sha = hashlib.sha256(prompt.encode()).hexdigest()
        d = f"composed/{name}"
        if shas.get(f"{name}_test") != sha or run.read(f"{d}/scores_test.json") is None:
            shas[f"{name}_test"] = sha
            answers: dict = {}
            run.write(f"{d}/scores_test.json", agents.score_all(prompt, test, outs, schema=setup.get("output_schema"), model=a.scorer,
                                                                effort=a.scorer_effort, workers=a.workers, raw=answers))
            run.write(f"{d}/outputs_test.json", answers)
        sc = run.read(f"{d}/scores_test.json")
        return {k: M.summary(M.item_errors(sc[k], refs[k], kind_of(k)), kind_of(k)) for k in outs}

    together_test = {name: measure(name) for name in layouts}
    composed["together_test"] = together_test
    composed["n"] = {"train": len(sp["train"]), "test": len(test)}
    run.write("composed.json", composed)

    # results.xlsx: Agreement gets the test rows, Items the final prompt's test scores; the other sheets stay
    path = run.dir / "results.xlsx"
    if path.exists():
        import pandas as pd
        sheets = {k: v.to_dict("records") for k, v in pd.read_excel(path, sheet_name=None).items()}
        fin_train, fin_test = run.read("composed/final/scores.json", {}), run.read("composed/final/scores_test.json", {})
        refs_train = agents.refs_by(items, outs, sp["train"])
        sheets["Agreement"] = excel.agreement_rows(
            [(f"{outs[k]['field']} · train", M.agreement(M.item_errors(fin_train.get(k, {}), refs_train[k], kind_of(k)), kind_of(k))) for k in outs]
            + [(f"{outs[k]['field']} · test (held out)", M.agreement(M.item_errors(fin_test[k], refs[k], kind_of(k)), kind_of(k))) for k in outs])
        base_test = run.read("composed/baseline/scores_test.json", {})
        for row in sheets.get("Items", []):
            if row.get("split") == "test":
                for k in outs:
                    row[f"{k} · v0"] = base_test.get(k, {}).get(row["id"])
                    row[f"{k} · final"] = fin_test.get(k, {}).get(row["id"])
        excel.write(path, sheets)

    for k in outs:
        line = f"{k}: held-out test ({len(test)} items) v0 {numbers(together_test['baseline'][k], outs[k])} → final {numbers(together_test['final'][k], outs[k])}"
        debug(run, "=== TEST " + line)
        print("TEST " + line, flush=True)
    events.emit(run.dir, "composed.test", n_train=len(sp["train"]), n_test=len(test),
                metrics={k: {"before": together_test["baseline"][k], "after": together_test["final"][k]} for k in outs})
    return together_test
