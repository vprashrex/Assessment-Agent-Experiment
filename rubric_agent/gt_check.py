"""Offline ground-truth diagnostics. Never imported by the graph; GT never reaches an agent.

preflight: is the Judge a sane QA target? Feed ~100 GT rows' PRODUCTION scores (half where humans disagreed,
           half where they agreed) to the Judge review as if they were k=1 scorer runs; compare Judge
           agree/disagree with the human label per metric (Cohen's kappa).
report:    per rubric version, how close its held-out mean scores sit to human-endorsed production scores.

GT column names are given by patterns so the org's sheet layout stays out of the code:
  --score-pattern "{metric}_score"   production score column per metric
  --label-pattern "{metric}"         human Agree/Disagree column per metric
"""

from __future__ import annotations

import random
from pathlib import Path

import pandas as pd

from .core.runio import Run
from .judge.review import review_rows
from .loop.measure import mean, row_stats
from .parser import sheet


def load_gt(gt_path: Path, id_col: str) -> pd.DataFrame:
    xls = pd.ExcelFile(gt_path)
    df = max((xls.parse(s) for s in xls.sheet_names), key=lambda d: d.count().sum())
    df, _ = sheet.clean_sheet(df)
    df["_cid"] = df[id_col].map(lambda v: str(sheet.cell(v)) if sheet.cell(v) is not None else None)
    return df.dropna(subset=["_cid"]).drop_duplicates("_cid").set_index("_cid")


def kappa(a: list[bool], b: list[bool]) -> float:
    n = len(a)
    if n == 0:
        return float("nan")
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def preflight(run: Run, gt: pd.DataFrame, score_pat: str, label_pat: str, n_each: int = 50) -> str:
    metrics = run.metrics
    sc, lb = {m: score_pat.format(metric=m) for m in metrics}, {m: label_pat.format(metric=m) for m in metrics}
    missing = [c for c in list(sc.values()) + list(lb.values()) if c not in gt.columns]
    if missing:
        return f"GT sheet lacks columns {missing}; adjust --score-pattern / --label-pattern."
    usable = gt[gt[list(sc.values())].notna().all(axis=1) & gt[list(lb.values())].notna().all(axis=1)]
    usable = usable[usable.index.isin(run.rows)]
    dis = usable[(usable[list(lb.values())] == "Disagree").any(axis=1)]
    agr = usable.drop(dis.index)
    rnd = random.Random(11)
    cids = rnd.sample(list(dis.index), min(n_each, len(dis))) + rnd.sample(list(agr.index), min(n_each, len(agr)))
    reason_col = {m: f"{m}_reason" for m in metrics}
    scores = {c: {"runs": [{"scores": {m: int(usable.loc[c, sc[m]]) for m in metrics},
                             "reasons": {m: str(usable.loc[c, reason_col[m]]) if reason_col[m] in usable.columns else "" for m in metrics},
                             "error": None}]} for c in cids}
    rv = review_rows(run, scores, cids)
    run.write("judge/gt_preflight.json", rv)
    lines = [f"# Judge pre-flight — {len(cids)} rows ({len(dis.index)} disagree-rows available, {len(agr.index)} agree-rows)", "",
             "| metric | judge agree% | human agree% | kappa | judge issues |", "|---|---|---|---|---|"]
    for m in metrics:
        v = {r["cid"]: r for r in rv["rows"] if r["metric"] == m}
        j = [v[c]["agree"] for c in cids if c in v]
        h = [usable.loc[c, lb[m]] == "Agree" for c in cids if c in v]
        issues = {i: sum(1 for r in v.values() if r["issue"] == i) for i in ("too_high", "too_low", "reason_unsupported")}
        lines.append(f"| {m} | {100 * sum(j) / max(1, len(j)):.0f} | {100 * sum(h) / max(1, len(h)):.0f} | {kappa(j, h):.2f} | {issues} |")
    lines += ["", "Read: kappa < 0.2 = judge and humans disagree about what is wrong; fix the judge prompt before running the loop.",
              "Note: with k=1 there is no consistency signal here; this measures the QUALITY half of the Judge only."]
    return "\n".join(lines)


def report(run: Run, gt: pd.DataFrame, score_pat: str, label_pat: str) -> str:
    metrics = run.metrics
    lines = ["# Rubric versions vs human-endorsed production scores (held-out rows)", "",
             "Rows where humans marked Agree: MAE of the version's mean score vs production, and share within ±1.", "",
             "| version | rows | MAE | ±1 % |", "|---|---|---|---|"]
    for f in sorted(run.dir.glob("scores/*_test.json")):
        v = f.name.split("_test")[0]
        rows = row_stats(run.json(f"scores/{v}_test.json", {}), metrics)
        errs = []
        for c, r in rows.items():
            if c not in gt.index:
                continue
            for m in metrics:
                scol, lcol = score_pat.format(metric=m), label_pat.format(metric=m)
                if scol in gt.columns and lcol in gt.columns and gt.loc[c, lcol] == "Agree" and pd.notna(gt.loc[c, scol]) and r["metrics"][m]["mean"] is not None:
                    errs.append(abs(r["metrics"][m]["mean"] - int(gt.loc[c, scol])))
        if errs:
            lines.append(f"| {v} | {len(errs) // len(metrics)} | {mean(errs):.2f} | {100 * sum(e <= 1 for e in errs) / len(errs):.0f} |")
    lines += ["", "Healthy: ICC rises in the loop AND MAE falls / ±1 rises here. ICC rising while MAE worsens = consistent but drifting from humans."]
    return "\n".join(lines)


def main(mode: str, run_dir: Path, gt_path: Path, score_pat: str = "{metric}_score", label_pat: str = "{metric}") -> None:
    run = Run(str(run_dir))
    gt = load_gt(gt_path, run.setup.columns.id_column or "id")
    text = preflight(run, gt, score_pat, label_pat) if mode == "preflight" else report(run, gt, score_pat, label_pat)
    out = run_dir / f"gt_{mode}.md"
    out.write_text(text + "\n")
    print(text)
    print(f"\n-> {out}")
