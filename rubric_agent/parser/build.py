"""Parser duty 3: build submissions.json (every chosen column as-is, link cells -> described attachments),
example pool, v0 copy, setup.json. Idempotent: skips when setup.json exists."""

from __future__ import annotations

import json
import random
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pandas as pd

from ..core.state import MetricSpec, Setup, get_path
from .attachments import VIDEO, describe, fetch
from .columns import plan_columns
from .setup import write_setup
from .sheet import cell, clean_sheet, is_link_column, links_in, load_schema, pick_sheet


def run(context: str, sheet_path: Path, prompt_path: Path, schema_path: Path, run_dir: Path, *, model: str,
        describe_model: str, constitution_path: Path | None = None, max_attachments: int | None = None, workers: int = 8,
        pool_size: int = 30) -> tuple[Setup | None, list[str]]:
    """Returns (setup, questions). setup is None when the operator must answer questions first.
    prompt_path = the starting rubric (v0); constitution_path = the rubric setup.md is written from (default: v0)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    if (run_dir / "setup.json").exists():
        return Setup.model_validate_json((run_dir / "setup.json").read_text()), []
    sheet = pick_sheet(sheet_path, context)
    df, stats = clean_sheet(pd.read_excel(sheet_path, sheet_name=sheet))
    plan = plan_columns(df, context, model)
    if plan.unresolved:
        return None, plan.unresolved
    schema = load_schema(schema_path)
    con = write_setup((constitution_path or prompt_path).read_text(), schema, context, model)
    if not con.metrics:
        return None, ["No numeric score field found in the output schema. Which fields are the scores?"]

    link_cols = [c for c in plan.use if is_link_column(df[c])]
    text_cols = [c for c in plan.use if c not in link_cols and c != plan.id_column]
    rows: list[dict[str, Any]] = []
    for i, r in df.iterrows():
        fields = {c: str(cell(r[c])) for c in text_cols if cell(r[c]) is not None}
        links = [u for c in link_cols for u in links_in(r[c])]
        if not fields and not links:
            continue
        cid = cell(r[plan.id_column]) if plan.id_column else None
        rows.append({"cid": str(cid) if cid is not None else f"row{i}", "fields": fields, "links": links, "attachments": [], "attachments_skipped": []})

    raw_dir, txt_dir = run_dir / "attachments" / "raw", run_dir / "attachments"
    raw_dir.mkdir(parents=True, exist_ok=True)
    jobs = [(row, url) for row in rows for url in row["links"]][: max_attachments if max_attachments is not None else None]
    unfetchable: list[str] = []

    def work(job: tuple[dict[str, Any], str]) -> None:
        row, url = job
        got = fetch(url, raw_dir)
        if got is None:
            row["attachments_skipped"].append(url)
            if not VIDEO.search(url):
                unfetchable.append(url)
        else:
            row["attachments"].append(describe(got[0], got[1], describe_model, txt_dir))

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(work, jobs))
    for row in rows:
        row.pop("links")
    pool = [r["cid"] for r in random.Random(7).sample([r for r in rows if r["fields"]], k=min(pool_size, len(rows)))]

    (run_dir / "rubric").mkdir(exist_ok=True)
    shutil.copy(prompt_path, run_dir / "rubric" / "v0.md")
    (run_dir / "submissions.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    (run_dir / "example_pool.json").write_text(json.dumps(sorted(pool)))
    setup = Setup(metrics=con.metrics, score_schema=schema, columns=plan, n_rows=len(rows))
    dataset_md = (
        "\n\n## Dataset (written by the harness)\n"
        f"- Sheet `{sheet}`: {stats['rows_in']}×{stats['cols_in']} in, {stats['rows_out']}×{stats['cols_out']} after dropping empty "
        f"rows/columns, {stats['rows_out'] - len(rows)} rows dropped for having no content.\n"
        f"- Columns used: {plan.use} (id: {plan.id_column}; attachment links: {link_cols})\n"
        f"- Submissions: {len(rows)}; with described attachments: {sum(1 for r in rows if r['attachments'])}; "
        f"attachments not fetchable: {len(set(unfetchable))} (ignored, never guessed); videos never evaluated.\n"
        f"- Metrics: {[m.name for m in setup.metrics]}, scale {setup.metrics[0].min}–{setup.metrics[0].max}.\n"
        "- Attachment text is a neutral description written once by the parser, not by the submitter.\n"
    )
    (run_dir / "setup.md").write_text(con.setup_md.rstrip() + dataset_md)
    (run_dir / "setup.json").write_text(setup.model_dump_json(indent=1))
    return setup, []


def scores_from(obj: dict[str, Any], metrics: list[MetricSpec]) -> dict[str, int] | None:
    """Integer scores by metric name from a scorer JSON; None if any missing, non-integer or out of range."""
    out: dict[str, int] = {}
    for m in metrics:
        try:
            v = get_path(obj, m.score_path)
        except KeyError:
            return None
        if not isinstance(v, (int, float)) or v != int(v) or not (m.min <= v <= m.max):
            return None
        out[m.name] = int(v)
    return out


def submission_text(row: dict[str, Any]) -> str:
    """Render one submission for the scorer or judge: every field as the sheet had it, then attachments."""
    parts = [f"{k}:\n{v}" for k, v in row["fields"].items()]
    if row["attachments"]:
        parts.append("Attachments (neutral descriptions written by a parser, not by the submitter):\n"
                     + "\n".join(f"- [{a['type']}] {a['description']}" for a in row["attachments"]))
    else:
        parts.append("Attachments: none")
    return "\n\n".join(parts)
