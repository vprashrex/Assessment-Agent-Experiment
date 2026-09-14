"""Offline ground-truth diagnostics. Never imported by the graph; GT never reaches an agent.

preflight: is the Judge a sane target? Band ~100 GT rows (half where humans disagreed with the
           production score, half where they agreed), compare judge agree/disagree with the human
           label per metric (Cohen's kappa), and show the judge's band distribution.
report:    per rubric version, how close its scores sit to human-endorsed production scores.

GT column names are given by patterns so the org's sheet layout stays out of the code:
  --score-pattern "{metric}_score"   production score column per metric
  --label-pattern "{metric}"         human Agree/Disagree column per metric
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pandas as pd

from . import nodes, parser


def load_gt(gt_path: Path, id_col: str) -> pd.DataFrame:
    xls = pd.ExcelFile(gt_path)
    df = max((xls.parse(s) for s in xls.sheet_names), key=lambda d: d.count().sum())
    df, _ = parser.clean_sheet(df)
    df["_cid"] = df[id_col].map(lambda v: str(parser.cell(v)) if parser.cell(v) is not None else None)
    return df.dropna(subset=["_cid"]).drop_duplicates("_cid").set_index("_cid")


def kappa(a: list[bool], b: list[bool]) -> float:
    n = len(a)
    if n == 0:
        return float("nan")
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def preflight(run: nodes.Run, gt: pd.DataFrame, score_pat: str, label_pat: str, n_each: int = 50) -> str:
    metrics = run.metrics
    sc = {m: score_pat.format(metric=m) for m in metrics}
    lb = {m: label_pat.format(metric=m) for m in metrics}
    missing = [c for c in list(sc.values()) + list(lb.values()) if c not in gt.columns]
    if missing:
        return f"GT sheet lacks columns {missing}; adjust --score-pattern / --label-pattern."
    usable = gt[gt[list(sc.values())].notna().all(axis=1) & gt[list(lb.values())].notna().all(axis=1)]
    usable = usable[usable.index.isin(run.rows)]
    dis = usable[(usable[list(lb.values())] == "Disagree").any(axis=1)]
    agr = usable.drop(dis.index)
    rnd = random.Random(11)
    cids = rnd.sample(list(dis.index), min(n_each, len(dis))) + rnd.sample(list(agr.index), min(n_each, len(agr)))
    bands = nodes.band_rows(run, cids)
    lines = [f"# Judge pre-flight — {len(cids)} rows ({len(dis.index)} disagree-rows available, {len(agr.index)} agree-rows)", "",
             "| metric | judge agree% | human agree% | kappa | judge bands lo..hi used |", "|---|---|---|---|---|"]
    for m in metrics:
        j, h, used = [], [], set()
        for c in cids:
            b = bands.get(c, {}).get(m)
            if not b:
                continue
            prod = int(usable.loc[c, sc[m]])
            j.append(b["lo"] <= prod <= b["hi"])
            h.append(usable.loc[c, lb[m]] == "Agree")
            used.update(range(b["lo"], b["hi"] + 1))
        lines.append(f"| {m} | {100 * sum(j) / max(1, len(j)):.0f} | {100 * sum(h) / max(1, len(h)):.0f} | {kappa(j, h):.2f} | {sorted(used)} |")
    served = {b.get("served_by") for c in cids for b in [bands.get(c, {})]}
    lines += ["", f"Judge served by: {sorted(s for s in served if s)}",
              "Read: kappa < 0.2 = judge and humans disagree about what is wrong; fix judge prompt/model before running the loop.",
              "Bands never reaching the top or bottom of the scale = judge shares the production compression."]
    return "\n".join(lines)


def report(run: nodes.Run, gt: pd.DataFrame, score_pat: str, label_pat: str) -> str:
    metrics = run.metrics
    versions = run.json("versions.json", {})
    lines = ["# Rubric versions vs human-endorsed production scores", "",
             "Rows where humans marked Agree: MAE and share within ±1 of the production score (lower MAE / higher ±1 = closer to humans).", "",
             "| version | round | kept | in-loop disagree% | rows | MAE | ±1 % |", "|---|---|---|---|---|---|---|"]
    for v, info in sorted(versions.items(), key=lambda kv: kv[1].get("round", 0)):
        files = sorted(run.dir.glob(f"scores/{v}_*.json"))
        if not files:
            continue
        scores: dict[str, dict] = {}
        for f in files:
            scores.update({c: s for c, s in json.loads(f.read_text()).items() if s.get("scores")})
        errs = []
        for c, s in scores.items():
            if c not in gt.index:
                continue
            for m in metrics:
                scol, lcol = score_pat.format(metric=m), label_pat.format(metric=m)
                if scol in gt.columns and lcol in gt.columns and gt.loc[c, lcol] == "Agree" and pd.notna(gt.loc[c, scol]):
                    errs.append(abs(s["scores"][m] - int(gt.loc[c, scol])))
        if errs:
            lines.append(f"| {v} | {info.get('round')} | {info.get('kept')} | {info.get('overall', float('nan')):.1f} | {len(errs) // len(metrics)} | "
                         f"{sum(errs) / len(errs):.2f} | {100 * sum(e <= 1 for e in errs) / len(errs):.0f} |")
    lines += ["", "Healthy: in-loop disagree% falls AND MAE falls / ±1 rises together. In-loop improving while MAE flat or worse = the",
              "generator is learning the judge, not the rubric."]
    return "\n".join(lines)


def main(mode: str, run_dir: Path, gt_path: Path, score_pat: str = "{metric}_score", label_pat: str = "{metric}") -> None:
    run = nodes.Run(str(run_dir))
    gt = load_gt(gt_path, run.setup.columns.id_column or "id")
    text = preflight(run, gt, score_pat, label_pat) if mode == "preflight" else report(run, gt, score_pat, label_pat)
    out = run_dir / f"gt_{mode}.md"
    out.write_text(text + "\n")
    print(text)
    print(f"\n-> {out}")
