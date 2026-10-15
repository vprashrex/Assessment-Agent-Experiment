"""Fan-out: a rubric that scores several metrics. Each metric is refined on its own, in parallel, then composed.

runs/<run>/
  setup/              the parser's setup for every metric; items.json holds each item's reference for every metric
  metrics/<key>/      one ordinary run folder per metric (same files as a single-metric run); its prompt is the
                      locked layers plus that metric's own section, so its loop sees and edits nothing else
  composed/baseline/  the original full prompt, scored once with every metric's field together (scores, outputs)
  composed/final/     each metric's best section stitched back into the original layout, scored the same way
  composed.json       per metric: alone v0 → best, together baseline → final; a hash of each scored prompt
  final_prompt.md     composed/final/prompt.md
  results.xlsx        Results (inputs + the composed prompt's full output, one column per key) · Agreement ·
                      Metrics (alone v0 → best, together v0 → final) · Items (reference, v0, final per metric)

The composer is code, not a model: it puts each metric's best section in place of the original one, so the program,
notes and output layers stay word for word, then runs the evaluation once on the whole prompt.
"""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor

from . import agents, excel, tracing
from . import math_tool as M
from .loop import Run, debug, labels, numbers, refine

EDITABLE = agents.EDITABLE


def split(run: Run, setup: dict, items: list[dict], m: dict) -> tuple[Run, dict, list[dict]]:
    """The sub-run for metric `m`: a run folder whose setup, items and v0 prompt hold only that metric."""
    sub = Run(run.dir / "metrics" / m["key"], session=run.session, label=m["key"], parent=run)
    if not sub.read("versions/v0/chunks.json"):
        chunks = [c for c in run.read("setup/baseline/layout.json") if c["layer"] != EDITABLE or c.get("metric") == m["key"]]
        sub.write("setup/setup.json", {**{k: v for k, v in setup.items() if k != "layers"}, "metrics": [m],
                                       "truth_column": m["truth_column"], "output": m["output"],
                                       "output_schema": _without_others(setup.get("output_schema"), setup, m)})
        sub.write("setup/items.json", [{**it, "truth": it["truths"][m["key"]]} for it in items if it["truths"].get(m["key"]) is not None])
        sub.write("setup/baseline/layout.json", chunks)
        sub.write("versions/v0/chunks.json", chunks)
        sub.write("versions/v0/prompt.md", agents.assemble(chunks))
    return sub, sub.read("setup/setup.json"), sub.read("setup/items.json")


def _without_others(schema: dict | None, setup: dict, m: dict) -> dict | None:
    """The operator's output schema minus the other metrics' output fields: a metric's prompt has no rubric for them."""
    if not schema:
        return None
    drop = {x["output"]["field"] for x in agents.metrics_of(setup) if x["key"] != m["key"]}
    return {**schema, "properties": {k: v for k, v in schema.get("properties", {}).items() if k not in drop},
            "required": [k for k in schema.get("required", []) if k not in drop]}


def main(run: Run, a, setup: dict, items: list[dict]) -> None:
    subs = [split(run, setup, items, m) for m in agents.metrics_of(setup)]
    debug(run, f"=== FAN-OUT · {len(subs)} metrics in parallel: " + ", ".join(
        f"{s[0].label} ({s[1]['truth_column']} → {s[1]['output']['field']}, {len(s[2])} items)" for s in subs))
    with ThreadPoolExecutor(len(subs)) as ex:  # one loop per metric, side by side
        list(ex.map(tracing.bind(lambda s: refine(s[0], a, s[1], s[2])), subs))
    compose(run, a, setup, items, [s[0] for s in subs])


def compose(run: Run, a, setup: dict, items: list[dict], subs: list[Run]) -> dict:
    """Stitch every metric's best section into the original layout and score the whole prompt once, against v0."""
    ms = agents.metrics_of(setup)
    outs = {m["key"]: m["output"] for m in ms}
    refs = {m["key"]: {it["id"]: v for it in items if (v := agents.reference(it["truths"].get(m["key"]), m["output"])) is not None}
            for m in ms}
    layout = run.read("setup/baseline/layout.json")
    best, parts = {}, {}
    for sub in subs:
        best[sub.label] = sub.read("state.json")["best"]
        chunks = sub.read(f"versions/{best[sub.label]}/chunks.json")
        assert [c for c in chunks if c["layer"] != EDITABLE] == [c for c in layout if c["layer"] != EDITABLE], "locked layer changed"
        parts[sub.label] = iter([c for c in chunks if c["layer"] == EDITABLE])
    final = [next(parts[c["metric"]]) if c["layer"] == EDITABLE else c for c in layout]

    scored_with = (run.read("composed.json") or {}).get("prompt_sha", {})

    def measure(name: str, chunks: list[dict]) -> dict:
        d, prompt = f"composed/{name}", agents.assemble(chunks)
        sha = hashlib.sha256(prompt.encode()).hexdigest()
        if scored_with.get(name) != sha or run.read(f"{d}/scores.json") is None:  # the prompts live in setup/ and final_prompt.md
            scored_with[name] = sha
            answers: dict = {}
            with tracing.span("score-items", input={"version": name, "items": len(items)}):
                run.write(f"{d}/scores.json", agents.score_all(prompt, items, outs, schema=setup.get("output_schema"), model=a.scorer, effort=a.effort, mode=a.mode,
                                                               workers=a.workers, raw=answers))
            run.write(f"{d}/outputs.json", answers)
        sc = run.read(f"{d}/scores.json")
        return {k: M.alignment(M.item_errors(sc[k], refs[k], outs[k]["type"]), None, outs[k]["type"]) for k in outs}

    with tracing.span("compose-run", session=run.session, metadata=labels(a), input={"best": best}) as t:
        together = {"baseline": measure("baseline", layout), "final": measure("final", final)}
        t.update(output={k: {"baseline": together["baseline"][k], "final": together["final"][k]} for k in outs})

    summary, rows = [], {}
    for sub in subs:
        k, kind = sub.label, outs[sub.label]["type"]
        alone = lambda v: M.alignment(M.item_errors(sub.read(f"versions/{v}/scores.json"), refs[k], kind), None, kind)  # noqa: E731
        st = sub.read("state.json")
        row = {"metric": k, "field": outs[k]["field"], "rounds": st["round"], "best": best[k]}
        for label, x in (("alone v0", alone("v0")), ("alone best", alone(best[k])), ("together v0", together["baseline"][k]),
                         ("together final", together["final"][k])):
            row.update({f"{label} · {n}": v for n, v in x.items() if n != "n"})
        summary.append(row)
    sc = {n: run.read(f"composed/{n}/scores.json") for n in together}
    for it in items:
        rows[it["id"]] = {"id": it["id"], **{f"{k} · {col}": v for k in outs for col, v in
                                            (("reference", refs[k].get(it["id"])), ("v0", sc["baseline"][k].get(it["id"])),
                                             ("final", sc["final"][k].get(it["id"])))}}
    run.write("final_prompt.md", agents.assemble(final))
    run.write("composed.json", {"best": best, "together": together, "prompt_sha": scored_with})
    fin = run.read("composed/final/scores.json")
    excel.write(run.dir / "results.xlsx", {
        "Results": excel.results_rows(items, run.read("composed/final/outputs.json", {}), setup),
        "Agreement": excel.agreement_rows([(outs[k]["field"], M.agreement(M.item_errors(fin[k], refs[k], outs[k]["type"]), outs[k]["type"]))
                                           for k in outs]),
        "Metrics": summary, "Items": list(rows.values())})
    for k in outs:
        line = f"{k}: together v0 {numbers(together['baseline'][k], outs[k])} → final {numbers(together['final'][k], outs[k])}"
        debug(run, "=== COMPOSED " + line)
        print("COMPOSED " + line, flush=True)
    return together
