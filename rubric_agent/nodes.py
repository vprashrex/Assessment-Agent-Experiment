"""Graph nodes. Each takes RunState, reads/writes files under run_dir, returns a small state update.
Agents: generate (Generator), band + comment (Judge), reflect. Everything else is plain code."""

from __future__ import annotations

import json
import math
import os
import random
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from langgraph.types import interrupt

from . import llm, parser
from .state import Bands, Commentary, GenOut, Reflection, RunState, Setup, get_path

MODELS = {
    "scorer": os.getenv("RUBRIC_SCORER", "claude-sonnet-5"),
    "judge": os.getenv("RUBRIC_JUDGE", "claude-fable-5-1"),
    "judge_fallback": os.getenv("RUBRIC_JUDGE_FALLBACK", "claude-opus-5"),
    "generator": os.getenv("RUBRIC_GENERATOR", "claude-opus-5"),
    "parser": os.getenv("RUBRIC_PARSER", "claude-opus-5"),
    "describe": os.getenv("RUBRIC_DESCRIBE", "claude-sonnet-5"),
}
WORKERS = int(os.getenv("RUBRIC_WORKERS", "8"))
ANCHOR_N, CARRY_CAP, CARRY_RETIRE, LEN_BUDGET, POOL_SHOW = 15, 20, 2, 1.3, 6
N_MAX = int(os.getenv("RUBRIC_N_MAX", "150"))
BAKEOFF_N = int(os.getenv("RUBRIC_BAKEOFF_N", "60"))
PRINCIPLES = Path(__file__).resolve().parents[1] / "memory" / "principles.md"


# --- file helpers -------------------------------------------------------------------


class Run:
    def __init__(self, run_dir: str):
        self.dir = Path(run_dir)
        self._setup: Setup | None = None
        self._rows: dict[str, dict[str, Any]] | None = None

    @property
    def setup(self) -> Setup:
        if self._setup is None:
            self._setup = Setup.model_validate_json((self.dir / "setup.json").read_text())
        return self._setup

    @property
    def rows(self) -> dict[str, dict[str, Any]]:
        if self._rows is None:
            self._rows = {r["cid"]: r for r in json.loads((self.dir / "submissions.json").read_text())}
        return self._rows

    @property
    def metrics(self) -> list[str]:
        return [m.name for m in self.setup.metrics]

    def text(self, name: str) -> str:
        p = self.dir / name
        return p.read_text() if p.exists() else ""

    def json(self, name: str, default: Any) -> Any:
        p = self.dir / name
        return json.loads(p.read_text()) if p.exists() else default

    def write(self, name: str, data: Any) -> None:
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1))

    def append(self, name: str, text: str) -> None:
        p = self.dir / name
        with p.open("a") as f:
            f.write(text.rstrip() + "\n")

    def rubric(self, version: str) -> str:
        return self.text(f"rubric/{version}.md")

    def pool(self) -> set[str]:
        return set(self.json("example_pool.json", []))


def prompt(name: str) -> str:
    return (Path(__file__).parent / "prompts" / f"{name}.md").read_text()


# --- scoring / judging / maths (plain code) ----------------------------------------------


def score_rows(run: Run, rubric_md: str, cids: list[str]) -> dict[str, dict[str, Any]]:
    """Scorer = plain API call: rubric as system prompt, one submission as user, schema-enforced JSON."""
    setup = run.setup

    def one(cid: str) -> tuple[str, dict[str, Any]]:
        try:
            raw, _ = llm.call(MODELS["scorer"], rubric_md, parser.submission_text(run.rows[cid])
                              + "\n\nReturn the JSON object exactly as specified.", setup.score_schema,
                              role="scorer", effort=os.getenv("RUBRIC_SCORER_EFFORT", "medium"), retries=0)
        except Exception as e:
            return cid, {"scores": None, "reasons": {}, "error": f"{type(e).__name__}: {e}"[:200]}
        scores = parser.scores_from(raw, setup.metrics)
        reasons = {m.name: (get_path(raw, m.reason_path) if m.reason_path else "") for m in setup.metrics
                   if not m.reason_path or _has(raw, m.reason_path)}
        return cid, {"scores": scores, "reasons": reasons, "error": None if scores else "schema/range failure"}

    with ThreadPoolExecutor(WORKERS) as ex:
        return dict(ex.map(one, cids))


def _has(obj: Any, path: str) -> bool:
    try:
        get_path(obj, path)
        return True
    except KeyError:
        return False


def band_rows(run: Run, cids: list[str], cache: str = "bands.json") -> dict[str, dict[str, Any]]:
    """Judge-A: fix a fair band per metric from setup.md + submission only. Cached per row for the run."""
    bands = run.json(cache, {})
    todo = [c for c in cids if c not in bands]
    spec = run.setup.metrics
    width = max(1, round(0.2 * (spec[0].max - spec[0].min)))
    system = prompt("judge_band") + "\n\n# SETUP\n" + run.text("setup.md")
    names = ", ".join(m.name for m in spec)

    def one(cid: str) -> tuple[str, dict[str, Any]]:
        user = (f"Metrics (use these exact names): {names}. Scale {spec[0].min}–{spec[0].max}. "
                f"Band width: hi - lo <= {width}.\n\nSUBMISSION {cid}:\n{parser.submission_text(run.rows[cid])}")
        try:
            out, meta = llm.call(MODELS["judge"], system, user, Bands, role="judge_band",
                                 effort="high", fallback=MODELS["judge_fallback"])
        except llm.Refusal as e:
            return cid, {"error": str(e)}
        rec: dict[str, Any] = {"served_by": meta["served_by"]}
        for m in spec:
            b = out.get(m.name)
            if b is None:
                continue
            lo = max(m.min, min(m.max, b.lo)); hi = max(lo, min(m.max, b.hi, lo + width))
            rec[m.name] = {"lo": lo, "hi": hi, "evidence": b.evidence}
        return cid, rec

    if todo:
        with ThreadPoolExecutor(WORKERS) as ex:
            bands.update(dict(ex.map(one, todo)))
        run.write(cache, bands)
    return bands


def verdicts(run: Run, scores: dict[str, dict[str, Any]], bands: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """agree iff score inside band. Per row: disagree count; per metric: rate; plus score distribution."""
    metrics, spec = run.metrics, run.setup.metrics
    rows: dict[str, dict[str, Any]] = {}
    per_metric = {m: [0, 0] for m in metrics}
    dist = {m: Counter() for m in metrics}
    for cid, s in scores.items():
        b = bands.get(cid, {})
        r: dict[str, Any] = {}
        for m in metrics:
            if m not in b:
                continue
            per_metric[m][1] += 1
            if s["scores"] is None:
                r[m] = {"agree": False, "severity": spec[0].max - spec[0].min, "score": None}
                per_metric[m][0] += 1
                continue
            v = s["scores"][m]
            dist[m][v] += 1
            sev = max(0, b[m]["lo"] - v, v - b[m]["hi"])
            r[m] = {"agree": sev == 0, "severity": sev, "score": v, "band": [b[m]["lo"], b[m]["hi"]]}
            per_metric[m][0] += sev > 0
        rows[cid] = {"metrics": r, "disagree": sum(1 for x in r.values() if not x["agree"]),
                     "severity": sum(x["severity"] for x in r.values())}
    rate = {m: (100 * d / n if n else float("nan")) for m, (d, n) in per_metric.items()}
    lo, hi = spec[0].min, spec[0].max
    table = {}
    for m in metrics:
        n = sum(dist[m].values()) or 1
        top = dist[m].most_common(1)[0] if dist[m] else (None, 0)
        table[m] = {"counts": {str(v): dist[m].get(v, 0) for v in range(lo, hi + 1)},
                    "unused": [v for v in range(lo, hi + 1) if dist[m].get(v, 0) == 0],
                    "pileup": f"{top[0]} ({100 * top[1] // n}%)" if top[1] / n > 0.4 else None}
    overall = 100 * sum(r["disagree"] for r in rows.values()) / max(1, len(rows) * len(metrics))
    return {"rows": rows, "per_metric": rate, "overall": overall, "distribution": table}


def paired(v_cand: dict[str, Any], v_best: dict[str, Any], cids: list[str]) -> tuple[float, float, int]:
    """Mean per-row difference in disagree count (cand - best) and its standard error, over shared rows."""
    d = [v_cand["rows"][c]["disagree"] - v_best["rows"][c]["disagree"] for c in cids
         if c in v_cand["rows"] and c in v_best["rows"]]
    n = len(d)
    if n < 2:
        return (d[0] if d else 0.0), float("inf"), n
    mean = sum(d) / n
    se = math.sqrt(sum((x - mean) ** 2 for x in d) / (n - 1)) / math.sqrt(n)
    return mean, se, n


def noise_floor(a: dict[str, Any], b: dict[str, Any], cids: list[str], metrics: list[str]) -> float:
    """% of (row, metric) cells where two independent Judge bandings do not overlap = the instrument's own noise."""
    tot = off = 0
    for c in cids:
        for m in metrics:
            x, y = a.get(c, {}).get(m), b.get(c, {}).get(m)
            if x and y:
                tot += 1
                off += x["hi"] < y["lo"] or y["hi"] < x["lo"]
    return 100 * off / tot if tot else 0.0


def fmt_rates(rates: dict[str, float]) -> str:
    return " ".join(f"{m[:4]} {r:.0f}" for m, r in rates.items())


# --- nodes ---------------------------------------------------------------------------


def parse(state: RunState) -> dict[str, Any]:
    run = Run(state["run_dir"])
    context = state["context"] + "".join(f"\n\nOPERATOR ANSWER: {a}" for a in state.get("operator_answers", []))
    setup, questions = parser.run(context, Path(state["sheet_path"]), Path(state["prompt_path"]), Path(state["schema_path"]),
                                  run.dir, model=MODELS["parser"], describe_model=MODELS["describe"],
                                  max_attachments=state.get("max_attachments"), workers=WORKERS)
    return {"needs_input": questions}


def ask_operator(state: RunState) -> dict[str, Any]:
    answer = interrupt({"questions": state["needs_input"]})
    return {"operator_answers": state.get("operator_answers", []) + [str(answer)], "needs_input": []}


def review_setup(state: RunState) -> dict[str, Any]:
    if not state.get("review"):
        return {}
    run = Run(state["run_dir"])
    edited = interrupt({"review": "setup.md — return 'approve' or the full edited text", "setup_md": run.text("setup.md")})
    if isinstance(edited, str) and edited.strip() and edited.strip().lower() != "approve":
        run.write("setup.md", edited)
    return {}


def _draw(run: Run, k: int, exclude: set[str], seed: str) -> list[str]:
    cids = [c for c in run.rows if c not in exclude and run.rows[c]["fields"]]
    return random.Random(seed).sample(cids, k=min(k, len(cids)))


def baseline(state: RunState) -> dict[str, Any]:
    """Round 0: score v0, band the sample, and measure the Judge's noise floor by banding the anchor twice."""
    run = Run(state["run_dir"])
    anchor = _draw(run, ANCHOR_N, run.pool(), "anchor")
    n = state.get("n_random") or 60
    sample = anchor + _draw(run, n, run.pool() | set(anchor), "r0")
    scores = score_rows(run, run.rubric("v0"), sample)
    run.write("scores/v0_r0.json", scores)
    bands = band_rows(run, sample)
    v = verdicts(run, scores, bands)
    run.write("judge/round_0_verdicts.json", {"v0": v})
    floor = noise_floor(bands, band_rows(run, anchor, cache="bands_repeat.json"), anchor, run.metrics)
    target = state.get("target") or round(floor + state.get("margin", 5.0), 1)
    line = (f"r00 | v0 baseline | n={n}+{len(anchor)}a | disagree% {fmt_rates(v['per_metric'])} | overall {v['overall']:.1f} | BEST"
            f" | judge noise floor {floor:.1f}% -> success target {target:.1f}%")
    run.append("ledger.md", line)
    run.write("versions.json", {"v0": {"round": 0, "base": None, "overall": v["overall"], "kept": True, "summary": "baseline"}})
    run.append("scratchpad.md", f"## Round 0 — Judge\nBaseline v0 on {len(sample)} rows. Overall disagree {v['overall']:.1f}%. "
               f"Per metric: {fmt_rates(v['per_metric'])}.\nDistribution: {json.dumps(v['distribution'])}\n")
    carry = [c for c, r in v["rows"].items() if r["disagree"] and c not in anchor][:CARRY_CAP]
    reason = ("circuit breaker: max rounds" if state.get("max_rounds", 0) <= 0
              else f"success: v0 already {v['overall']:.1f}% <= target {target:.1f}%" if v["overall"] <= target else None)
    if reason:
        run.append("ledger.md", f"STOP: {reason}")
    return {"round": 0, "best": "v0", "best_round": 0, "anchor": anchor, "carry": carry, "carry_count": {c: 1 for c in carry},
            "consecutive_fail": 0, "ledger": [line], "noise_floor": floor, "target": target, "retest": False,
            "stop": reason is not None, "stop_reason": reason or ""}


def _window(scratch: str, rounds: set[int]) -> str:
    parts = re.split(r"(?m)^(?=## Round \d+ — )", scratch)
    keep = [p for p in parts if (m := re.match(r"## Round (\d+)", p)) and int(m.group(1)) in rounds]
    return "\n".join(keep) if keep else "(none yet)"


def generate(state: RunState) -> dict[str, Any]:
    run = Run(state["run_dir"])
    rnd, best = state["round"] + 1, state["best"]
    v0, best_md = run.rubric("v0"), run.rubric(best)
    last = run.json(f"judge/round_{state['round']}_verdicts.json", {})
    stats = last.get(state.get("candidate") if state["round"] else "v0") or last.get(best) or {}
    pool_rows = [run.rows[c] for c in random.Random(f"pool{rnd}").sample(sorted(run.pool() & set(run.rows)), k=min(POOL_SHOW, len(run.pool())))]
    budget = int(LEN_BUDGET * len(v0))
    user = (
        f"# SETUP.MD\n{run.text('setup.md')}\n\n# CURRENT BEST RUBRIC ({best}, {len(best_md)} chars; budget {budget} chars)\n<<<\n{best_md}\n>>>\n\n"
        f"# STATS FOR THE LAST EVALUATED VERSION\nper-metric disagree%: {json.dumps(stats.get('per_metric', {}))}\n"
        f"overall: {stats.get('overall', 'n/a')}\ndistribution (counts per score, unused values, pile-ups): {json.dumps(stats.get('distribution', {}))}\n\n"
        f"# JUDGE NOTES (scratchpad window)\n{_window(run.text('scratchpad.md'), {state['round'], state['round'] - 1, state['best_round']})}\n\n"
        f"# LEDGER\n{run.text('ledger.md')}\n\n# PRINCIPLES FROM EARLIER RUNS\n{PRINCIPLES.read_text() if PRINCIPLES.exists() else '(none)'}\n\n"
        f"# EXAMPLE POOL (the only rows you may use as worked examples)\n"
        + "\n\n".join(f"[{r['cid']}]\n{parser.submission_text(r)[:700]}" for r in pool_rows)
        + f"\n\n# CONSTRAINTS\n- Every metric name must appear: {run.metrics}\n- rubric_md <= {budget} chars\n- n_random in [20,150]"
    )
    out, _ = llm.call(MODELS["generator"], prompt("generator"), user, GenOut, role="generator", effort="high")
    problems = [f"metric name '{m}' missing" for m in run.metrics if m not in out.rubric_md]
    if len(out.rubric_md) > budget:
        problems.append(f"rubric is {len(out.rubric_md)} chars, budget {budget}")
    if problems:
        out, _ = llm.call(MODELS["generator"], prompt("generator"), user + "\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED: "
                          + "; ".join(problems) + ". Fix and return again.", GenOut, role="generator", effort="high")
    cand = f"v{rnd}"
    run.write(f"rubric/{cand}.md", out.rubric_md)
    run.append("scratchpad.md", f"## Round {rnd} — Generator\n{cand} from {best}. Change: {out.change_summary}\nHypothesis: {out.hypothesis}\n"
               + (f"Generator declares converged: {out.converged_reason}\n" if out.converged else ""))
    versions = run.json("versions.json", {})
    versions[cand] = {"round": rnd, "base": best, "summary": out.change_summary, "kept": False}
    run.write("versions.json", versions)
    return {"round": rnd, "candidate": cand, "n_random": max(20, min(N_MAX, out.n_random)), "converged": out.converged}


def sample(state: RunState) -> dict[str, Any]:
    run = Run(state["run_dir"])
    anchor, carry = state["anchor"], state.get("carry", [])
    rnd = _draw(run, state["n_random"], run.pool() | set(anchor) | set(carry), f"r{state['round']}")
    return {"sample": anchor + rnd + carry}


def score(state: RunState) -> dict[str, Any]:
    """Score candidate and best on the same rows; rows already scored this round are not repeated."""
    run = Run(state["run_dir"])
    for v in (state["candidate"], state["best"]):
        f = f"scores/{v}_r{state['round']}.json"
        have = run.json(f, {})
        todo = [c for c in state["sample"] if c not in have]
        if todo:
            have.update(score_rows(run, run.rubric(v), todo))
            run.write(f, have)
    return {}


def band(state: RunState) -> dict[str, Any]:
    run = Run(state["run_dir"])
    band_rows(run, state["sample"])
    return {}


def verdict(state: RunState) -> dict[str, Any]:
    run = Run(state["run_dir"])
    bands = run.json("bands.json", {})
    out = {v: verdicts(run, run.json(f"scores/{v}_r{state['round']}.json", {}), bands) for v in (state["candidate"], state["best"])}
    run.write(f"judge/round_{state['round']}_verdicts.json", out)
    return {}


def comment(state: RunState) -> dict[str, Any]:
    """Judge-B: explain disagreements of the candidate, find patterns. Anchor rows are masked for the Generator."""
    if state.get("retest"):  # commentary was written on the first pass of this round
        return {}
    run = Run(state["run_dir"])
    rnd, cand = state["round"], state["candidate"]
    v = run.json(f"judge/round_{rnd}_verdicts.json", {})[cand]
    scores = run.json(f"scores/{cand}_r{rnd}.json", {})
    items = []
    for cid, r in v["rows"].items():
        for m, x in r["metrics"].items():
            if not x["agree"]:
                items.append({"cid": cid, "metric": m, "band": x.get("band"), "band_evidence": run.json("bands.json", {})[cid][m]["evidence"],
                              "score": x["score"], "reason": scores[cid]["reasons"].get(m, scores[cid].get("error")),
                              "submission": parser.submission_text(run.rows[cid])[:1500]})
    if not items:
        run.append("scratchpad.md", f"## Round {rnd} — Judge\n{cand}: no disagreements on {len(v['rows'])} rows.\n")
        return {}
    user = (f"SETUP.MD:\n{run.text('setup.md')}\n\nROWS WHERE THE SCORE FELL OUTSIDE THE BAND ({len(items)} of "
            f"{len(v['rows']) * len(run.metrics)} cells):\n{json.dumps(items, ensure_ascii=False)}\n\n"
            f"DISTRIBUTION TABLE:\n{json.dumps(v['distribution'])}")
    try:
        c, _ = llm.call(MODELS["judge"], prompt("judge_comment"), user, Commentary, role="judge_comment",
                        effort="high", fallback=MODELS["judge_fallback"])
    except llm.Refusal as e:
        run.append("scratchpad.md", f"## Round {rnd} — Judge\nJudge refused commentary: {e}\n")
        return {}
    run.write(f"judge/round_{rnd}.json", c.model_dump())
    anchor = set(state["anchor"])
    mask = lambda cid: "(anchor)" if cid in anchor else cid  # noqa: E731
    lines = [f"## Round {rnd} — Judge", f"{cand}: overall disagree {v['overall']:.1f}% | {fmt_rates(v['per_metric'])}", c.summary, "",
             "Patterns (support >= 3):"]
    lines += [f"- {p.metric}: {p.pattern} [{p.support}: {', '.join(mask(x) for x in p.cids)}]" for p in c.patterns if p.support >= 3]
    lines += ["", "Rows:"] + [f"- {mask(r.cid)} / {r.metric}: {r.comment} {r.defects}" for r in c.rows]
    run.append("scratchpad.md", "\n".join(lines) + "\n")
    return {}


def gate(state: RunState) -> dict[str, Any]:
    """Plain code, never skippable. Paired test of candidate vs best on anchor + random rows, then the three breaks:
    circuit breaker (rounds ceiling, scorer failures), fail break (3 conclusive failures), success break (target)."""
    run = Run(state["run_dir"])
    rnd, cand, best = state["round"], state["candidate"], state["best"]
    v = run.json(f"judge/round_{rnd}_verdicts.json", {})
    gate_rows = [c for c in state["sample"] if c not in set(state.get("carry", []))]
    delta, se, n = paired(v[cand], v[best], gate_rows)

    # two-stage test: promising but inside noise -> one re-test on more fresh rows before it counts as a failure
    if delta < 0 and abs(delta) < se and not state.get("retest"):
        extra = _draw(run, 2 * state["n_random"], run.pool() | set(state["sample"]), f"r{rnd}x")
        run.append("ledger.md", f"r{rnd:02d} | {cand} inconclusive: paired Δ {delta:+.2f} (SE {se:.2f}) on n={n} -> re-test on +{len(extra)} rows")
        return {"retest": True, "sample": state["sample"] + extra}

    kept = delta < -se
    worse = [m for m in run.metrics if v[cand]["per_metric"][m] > v[best]["per_metric"][m] + 100 * se / max(1, len(run.metrics))]
    versions = run.json("versions.json", {})
    versions[cand].update(overall=v[cand]["overall"], kept=kept, delta=delta, se=se, n=n)
    run.write("versions.json", versions)
    line = (f"r{rnd:02d} | {cand} ← {best} \"{versions[cand]['summary']}\" | n={n} (+{len(state.get('carry', []))} carry)"
            + (" retested" if state.get("retest") else "") + f" | disagree% {fmt_rates(v[cand]['per_metric'])} | overall "
            f"{v[cand]['overall']:.1f} vs best {v[best]['overall']:.1f} | paired Δ {delta:+.2f} rows (SE {se:.2f})"
            + (f" | worse: {worse}" if worse else "") + f" | {'KEPT' if kept else 'NOT KEPT'}")
    run.append("ledger.md", line)

    # carry-over: rows the candidate got wrong, retired after CARRY_RETIRE consecutive carries
    counts = dict(state.get("carry_count", {}))
    carry = []
    for c, r in v[cand]["rows"].items():
        if r["disagree"] and c not in state["anchor"]:
            counts[c] = counts.get(c, 0) + 1
            if counts[c] > CARRY_RETIRE:
                run.append("unresolved.md", f"{c}: disagreed {counts[c]} rounds running (last {cand})")
            else:
                carry.append(c)
    carry = carry[:CARRY_CAP]

    fail = 0 if kept else state.get("consecutive_fail", 0) + 1
    best_now = v[cand]["overall"] if kept else v[best]["overall"]
    sc = run.json(f"scores/{cand}_r{rnd}.json", {})
    err = sum(1 for x in sc.values() if not x.get("scores")) / max(1, len(sc))
    target = state.get("target", 0.0)
    reason = (f"circuit breaker: {err:.0%} of scorer calls failed" if err > 0.3
              else "circuit breaker: max rounds" if rnd >= state["max_rounds"]
              else f"success: best {best_now:.1f}% <= target {target:.1f}%" if target and best_now <= target
              else "fail break: 3 conclusive failures in a row" if fail >= 3
              else "fail break: generator declared converged after a failed attempt" if state.get("converged") and fail >= 1
              else None)
    if reason:
        run.append("ledger.md", f"STOP: {reason}")
    return {"best": cand if kept else best, "best_round": rnd if kept else state["best_round"], "consecutive_fail": fail,
            "carry": carry, "carry_count": {c: counts[c] for c in carry}, "ledger": state["ledger"] + [line],
            "retest": False, "stop": reason is not None, "stop_reason": reason or ""}


def bakeoff(state: RunState) -> dict[str, Any]:
    """Fresh sample, every candidate scored against the same cached bands; lowest disagreement wins."""
    run = Run(state["run_dir"])
    versions = run.json("versions.json", {})
    ranked = sorted((v for v in versions if v != "v0" and "overall" in versions[v]), key=lambda v: versions[v]["overall"])
    cands = ["v0"] + ranked[:3]
    fresh = state["anchor"] + _draw(run, BAKEOFF_N, run.pool() | set(state["anchor"]), "bakeoff")
    bands = band_rows(run, fresh)
    results = {}
    for v in cands:
        s = score_rows(run, run.rubric(v), fresh)
        run.write(f"scores/{v}_bakeoff.json", s)
        vd = verdicts(run, s, bands)
        results[v] = (vd["overall"], sum(r["severity"] for r in vd["rows"].values()), len(run.rubric(v)), vd["per_metric"])
    winner = min(cands, key=lambda v: results[v][:3])
    run.write("rubric/best.md", run.rubric(winner))
    line = "bakeoff | " + " ; ".join(f"{v} {results[v][0]:.1f}% sev {results[v][1]}" for v in cands) + f" | WINNER {winner}"
    run.append("ledger.md", line)
    run.write("bakeoff.json", {v: {"overall": r[0], "severity": r[1], "chars": r[2], "per_metric": r[3]} for v, r in results.items()} | {"winner": winner})
    return {"best": winner, "ledger": state["ledger"] + [line]}


def reflect(state: RunState) -> dict[str, Any]:
    run = Run(state["run_dir"])
    user = f"SCRATCHPAD:\n{run.text('scratchpad.md')[-30000:]}\n\nLEDGER:\n{run.text('ledger.md')}"
    try:
        out, _ = llm.call(MODELS["generator"], prompt("reflect"), user, Reflection, role="reflect", effort="medium")
    except llm.LLMError:
        return {}
    if out.principles:
        PRINCIPLES.parent.mkdir(exist_ok=True)
        tag = f"[run={run.dir.name} judge={MODELS['judge']} setup={abs(hash(run.text('setup.md'))) % 10**8:08d}]"
        with PRINCIPLES.open("a") as f:
            f.writelines(f"- {p.strip()} {tag}\n" for p in out.principles[:3])
        lines = PRINCIPLES.read_text().splitlines()
        if len(lines) > 40:
            PRINCIPLES.write_text("\n".join(lines[-40:]) + "\n")
    return {}
