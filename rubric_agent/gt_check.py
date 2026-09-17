"""Offline: each rubric version's mean scores vs production scores on rows humans marked Agree. Never used by the graph."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .core.runio import Run
from .loop.measure import mean, row_stats
from .parser import sheet


def load_gt(gt_path: Path, id_col: str) -> pd.DataFrame:
    xls = pd.ExcelFile(gt_path)
    df = max((xls.parse(s) for s in xls.sheet_names), key=lambda d: d.count().sum())
    df, _ = sheet.clean_sheet(df)
    df["_cid"] = df[id_col].map(lambda v: str(sheet.cell(v)) if sheet.cell(v) is not None else None)
    return df.dropna(subset=["_cid"]).drop_duplicates("_cid").set_index("_cid")


def main(run_dir: Path, gt_path: Path, score_pat: str, label_pat: str) -> None:
    run = Run(str(run_dir))
    gt = load_gt(gt_path, run.setup.columns.id_column or "id")
    versions = run.json("versions.json", {})
    lines = ["| version | round | kept | rows | MAE vs production | ±1 % |", "|---|---|---|---|---|---|"]
    for v, info in sorted(versions.items(), key=lambda kv: kv[1]["round"]):
        rows = row_stats(run.json(f"scores/{v}_r{info['round']}.json", {}), run.metrics)
        errs = []
        for c, r in rows.items():
            if c not in gt.index:
                continue
            for m in run.metrics:
                scol, lcol = score_pat.format(metric=m), label_pat.format(metric=m)
                if scol in gt.columns and lcol in gt.columns and gt.loc[c, lcol] == "Agree" and pd.notna(gt.loc[c, scol]) and r["metrics"][m]["mean"] is not None:
                    errs.append(abs(r["metrics"][m]["mean"] - int(gt.loc[c, scol])))
        if errs:
            lines.append(f"| {v} | {info['round']} | {info.get('kept')} | {len(errs) // len(run.metrics)} | {mean(errs):.2f} | {100 * sum(e <= 1 for e in errs) / len(errs):.0f} |")
    text = "\n".join(lines)
    (run_dir / "gt_report.md").write_text(text + "\n")
    print(text)
