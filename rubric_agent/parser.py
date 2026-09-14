"""Parser: clean the sheet, pick columns, write setup.md, describe attachments once.
Writes everything the loop needs under run_dir. Idempotent: skips work whose output exists.
Knows nothing about any particular org, column or metric: all of that comes from the inputs."""

from __future__ import annotations

import io
import json
import random
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
from PIL import Image

from . import llm
from .state import ColumnPlan, Constitution, Description, MetricSpec, Setup, get_path

PROMPTS = Path(__file__).parent / "prompts"
DRIVE_ID = re.compile(r"(?:/d/|[?&]id=)([\w-]{20,})")
VIDEO = re.compile(r"youtu\.?be|vimeo|\.mp4\b|\.mov\b", re.I)
MEDIA = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
EXT2MEDIA = {v: k for k, v in MEDIA.items()}
MAX_IMG_BYTES = 4_500_000
MAX_IMG_SIDE = 7500


def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text()


# --- sheet --------------------------------------------------------------------------


def pick_sheet(path: Path, context: str) -> str:
    xls = pd.ExcelFile(path)
    named = [s for s in xls.sheet_names if re.search(rf"(?<!\w){re.escape(s)}(?!\w)", context)]
    return named[0] if named else max(xls.sheet_names, key=lambda s: xls.parse(s).count().sum())


def clean_sheet(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    stats = {"rows_in": len(df), "cols_in": len(df.columns)}
    df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")
    df = df[[c for c in df.columns if not (str(c).startswith("Unnamed") or str(c) in ("None", "nan"))]]
    df.columns = [str(c).strip() for c in df.columns]
    df = df.map(lambda v: v.strip() if isinstance(v, str) else v).replace({"": None}).dropna(axis=0, how="all")
    stats.update(rows_out=len(df), cols_out=len(df.columns))
    return df.reset_index(drop=True), stats


def cell(v: Any) -> Any:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, float) and v == int(v):
        return int(v)
    return v


def links_in(v: Any) -> list[str]:
    return [t for t in re.split(r"[,\s]+", v) if t.startswith("http")] if isinstance(v, str) else []


def is_link_column(series: pd.Series) -> bool:
    vals = [v for v in series if isinstance(v, str)]
    return bool(vals) and sum(1 for v in vals if links_in(v)) >= 0.3 * len(vals)


# --- LLM steps -----------------------------------------------------------------------


def plan_columns(df: pd.DataFrame, context: str, model: str) -> ColumnPlan:
    sample = [{k: (str(v)[:160] if cell(v) is not None else None) for k, v in r.items()} for r in df.head(3).to_dict("records")]
    user = f"OPERATOR CONTEXT:\n{context}\n\nCOLUMNS: {list(df.columns)}\n\nSAMPLE ROWS:\n{json.dumps(sample, ensure_ascii=False, indent=1)}"
    plan, _ = llm.call(model, prompt("parser_columns"), user, ColumnPlan, role="parser", effort="medium")
    missing = [c for c in plan.use + ([plan.id_column] if plan.id_column else []) if c not in df.columns]
    if missing:
        plan.unresolved.append(f"Columns {missing} do not exist; the sheet has {list(df.columns)}.")
    if not plan.use and not plan.unresolved:
        plan.unresolved.append("No columns selected. Which columns hold the submission?")
    return plan


def _schema_paths(schema: dict[str, Any], prefix: str = "") -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for k, v in schema.get("properties", {}).items():
        out[prefix + k] = v
        if isinstance(v, dict) and v.get("type") == "object":
            out.update(_schema_paths(v, prefix + k + "."))
    return out


def write_setup(prompt_md: str, schema: dict[str, Any], context: str, model: str) -> Constitution:
    user = (f"OPERATOR CONTEXT:\n{context}\n\nOUTPUT SCHEMA THE SCORER MUST RETURN:\n{json.dumps(schema, indent=1)}\n\n"
            f"EXISTING RUBRIC PROMPT (v0):\n<<<\n{prompt_md}\n>>>")
    con, _ = llm.call(model, prompt("parser_constitution"), user, Constitution, role="parser", effort="high")
    paths = _schema_paths(schema)
    numeric = lambda p: p in paths and paths[p].get("type") in ("number", "integer")  # noqa: E731
    con.metrics = [m for m in con.metrics if numeric(m.score_path)]
    for m in con.metrics:
        if m.reason_path is not None and m.reason_path not in paths:
            m.reason_path = None
    if not con.metrics:  # fallback: any numeric field named <X>_score
        for p, v in paths.items():
            if p.endswith("_score") and numeric(p):
                n = p[: -len("_score")]
                con.metrics.append(MetricSpec(name=n, score_path=p, reason_path=f"{n}_reason" if f"{n}_reason" in paths else None,
                                              min=int(v.get("minimum", 1)), max=int(v.get("maximum", 10))))
    return con


# --- attachments ----------------------------------------------------------------------


def fetch(url: str, raw_dir: Path) -> tuple[Path, str] | None:
    """Download once. (path, media_type) for images/PDFs; None for videos, HTML or failures."""
    if VIDEO.search(url):
        return None
    m = DRIVE_ID.search(url)
    fid = m.group(1) if m else re.sub(r"\W+", "_", url)[-60:]
    for p in raw_dir.glob(f"{fid}.*"):
        return (p, EXT2MEDIA[p.suffix[1:]]) if p.suffix[1:] in EXT2MEDIA else None
    try:
        r = httpx.get(f"https://drive.google.com/uc?export=download&id={fid}" if m else url, follow_redirects=True, timeout=60)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    data, ctype = r.content, r.headers.get("content-type", "").split(";")[0].strip().lower()
    if data[:4] == b"%PDF":
        ctype = "application/pdf"
    ext = MEDIA.get(ctype)
    if not ext:
        (raw_dir / f"{fid}.skip").write_text(ctype or "unknown")
        return None
    if ext != "pdf":
        data, ctype, ext = _shrink(data, ctype, ext)
    p = raw_dir / f"{fid}.{ext}"
    p.write_bytes(data)
    return p, ctype


def _shrink(data: bytes, ctype: str, ext: str) -> tuple[bytes, str, str]:
    try:
        img = Image.open(io.BytesIO(data))
    except Exception:
        return data, ctype, ext
    if len(data) <= MAX_IMG_BYTES and max(img.size) <= MAX_IMG_SIDE and ext != "gif":
        return data, ctype, ext
    img = img.convert("RGB")
    if max(img.size) > 2000:
        s = 2000 / max(img.size)
        img = img.resize((int(img.width * s), int(img.height * s)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue(), "image/jpeg", "jpg"


def describe(path: Path, media_type: str, model: str, txt_dir: Path) -> dict[str, Any]:
    out = txt_dir / f"{path.stem}.json"
    if out.exists():
        return json.loads(out.read_text())
    kind = "pdf" if media_type == "application/pdf" else "image"
    kw = {"pdfs": [path.read_bytes()]} if kind == "pdf" else {"images": [(media_type, path.read_bytes())]}
    try:
        d, _ = llm.call(model, prompt("parser_describe"), "Describe this attachment.", Description, role="describe", effort="low", **kw)
        rec = {"file_id": path.stem, "type": kind, "description": d.description, "readable": d.readable}
    except Exception as e:  # one bad file must not stop the run
        rec = {"file_id": path.stem, "type": kind, "description": f"[not described: {type(e).__name__}]", "readable": False}
    out.write_text(json.dumps(rec, ensure_ascii=False))
    return rec


# --- orchestration --------------------------------------------------------------------


def load_schema(path: Path) -> dict[str, Any]:
    text = path.read_text()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    return json.loads(m.group(1) if m else text)


def run(context: str, sheet_path: Path, prompt_path: Path, schema_path: Path, run_dir: Path, *, model: str,
        describe_model: str, max_attachments: int | None = None, workers: int = 8,
        pool_size: int = 30) -> tuple[Setup | None, list[str]]:
    """Returns (setup, questions). setup is None when the operator must answer questions first."""
    run_dir.mkdir(parents=True, exist_ok=True)
    if (run_dir / "setup.json").exists():
        return Setup.model_validate_json((run_dir / "setup.json").read_text()), []

    sheet = pick_sheet(sheet_path, context)
    df, stats = clean_sheet(pd.read_excel(sheet_path, sheet_name=sheet))
    plan = plan_columns(df, context, model)
    if plan.unresolved:
        return None, plan.unresolved
    schema = load_schema(schema_path)
    con = write_setup(prompt_path.read_text(), schema, context, model)
    if not con.metrics:
        return None, ["No numeric score field found in the output schema. Which fields are the scores?"]

    # rows: every chosen column as-is; link columns become attachments
    link_cols = [c for c in plan.use if is_link_column(df[c])]
    text_cols = [c for c in plan.use if c not in link_cols and c != plan.id_column]
    rows: list[dict[str, Any]] = []
    for i, r in df.iterrows():
        fields = {c: str(cell(r[c])) for c in text_cols if cell(r[c]) is not None}
        links = [u for c in link_cols for u in links_in(r[c])]
        if not fields and not links:
            continue
        cid = cell(r[plan.id_column]) if plan.id_column else None
        rows.append({"cid": str(cid) if cid is not None else f"row{i}", "fields": fields, "links": links,
                     "attachments": [], "attachments_skipped": []})

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
        "- Attachment text is a neutral description written once by the parser, not by the student.\n"
    )
    (run_dir / "setup.md").write_text(con.setup_md.rstrip() + dataset_md)
    (run_dir / "setup.json").write_text(setup.model_dump_json(indent=1))
    return setup, []


# --- helpers used by the loop -----------------------------------------------------------


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
        parts.append("Attachments (neutral descriptions written by a parser, not by the student):\n"
                     + "\n".join(f"- [{a['type']}] {a['description']}" for a in row["attachments"]))
    else:
        parts.append("Attachments: none")
    return "\n\n".join(parts)
