"""Excel views of a run. Pure formatting: every number here was already computed by math_tool.

versions/vN/result.xlsx   one version: Metrics, Items (output, error, judge notes), Prompt (layer by layer), Change
results.xlsx              the whole run: Results (inputs + the final prompt's full output, one column per key),
                          Agreement, then Versions, Rounds, Items, Checklist, Judge notes, Edits, Locked flags
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

MAX_CELL = 32000  # Excel's limit is 32767 characters per cell


def _clean(v: Any) -> Any:
    if isinstance(v, (list, tuple)):
        v = ", ".join(map(str, v))
    return v[:MAX_CELL] if isinstance(v, str) else v


def write(path: Path, sheets: dict[str, list[dict]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, rows in sheets.items():
            df = pd.DataFrame([{k: _clean(v) for k, v in r.items()} for r in rows] or [{"": "(none)"}])
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            ws.freeze_panes = "B2"
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in col[:50])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)


def flatten(answer: dict, prefix: str = "") -> dict[str, Any]:
    """A structured answer as flat columns: nested keys joined with '_' (e.g. "section_field")."""
    out: dict[str, Any] = {}
    for k, v in (answer or {}).items():
        key = f"{prefix}_{k}" if prefix else k
        out.update(flatten(v, key) if isinstance(v, dict) else {key: v})
    return out


def results_rows(items: list[dict], answers: dict[str, dict], setup: dict) -> list[dict]:
    """One row per item: its id and input columns as they are in the sheet, then every key of the scorer's answer."""
    cols = [c for c in [setup.get("id_column"), *(x["name"] for x in setup["input_columns"])] if c]
    return [{**{c: it.get("fields", {}).get(c, it["id"] if c == setup.get("id_column") else "") for c in cols},
             **flatten(answers.get(it["id"], {}))} for it in items]


def agreement_rows(rows: list[tuple[str, dict]]) -> list[dict]:
    """(output field, math_tool.agreement) -> the plain-language agreement table."""
    return [{"Score": f, "Matched the reference exactly": f"{a['exact']} / {a['n']}",
             **({"Within 1 point": f"{a['within1']} / {a['n']}"} if "within1" in a else {}),
             "Average gap": f"{a['mae']:.2f}"} for f, a in rows if a.get("n")]


def version_sheets(ver: str, metrics: dict, items: list[dict], scores: dict, refs: dict, errs: dict, notes: dict,
                   chunks: list[dict], change: dict | None) -> dict[str, list[dict]]:
    rows = []
    for it in items:
        i, n = it["id"], notes.get(it["id"], {})
        rows.append({"id": i, "reference": refs.get(i), "output": scores.get(i), "error": errs.get(i),
                     "direction": n.get("direction", ""), "observations": n.get("observations", ""),
                     "model_reasoning": n.get("model_reasoning", ""), "clause": n.get("clause", ""),
                     "comment": n.get("comment", ""), "files": it.get("files", [])})
    sheets = {"Metrics": [{"version": ver, **metrics}], "Items": rows,
              "Prompt": [{"part": k, "layer": c["layer"], "editable": c["layer"] == "metrics", "text": c["text"]}
                         for k, c in enumerate(chunks, start=1)]}
    if change:
        sheets["Change"] = ([{"field": "verdict", "value": change.get("verdict", "")},
                             {"field": "from", "value": change.get("parent", "")},
                             {"field": "realisation", "value": change.get("realisation", "")},
                             {"field": "summary", "value": change.get("summary", "")},
                             {"field": "closer", "value": change.get("closer", [])},
                             {"field": "further", "value": change.get("further", [])},
                             {"field": "not applied", "value": change.get("problems", [])}]
                            + [{"field": f"edit · {e['issue']}", "value": f"OLD: {e['old_text']}\n\nNEW: {e['new_text']}"}
                               for e in change.get("edits", [])]
                            + [{"field": f"rewrite part {k}", "value": t} for k, t in enumerate(change.get("rewrite", []), 1)])
    return sheets


def run_sheets(versions: list[dict], items: list[dict], refs: dict, scores: dict[str, dict], best: str,
               errs_best: dict, notes: dict[str, dict], checklist: dict, rounds: list[dict],
               changes: dict[str, dict]) -> dict[str, list[dict]]:
    vs = [v["version"] for v in versions]
    item_rows = []
    for it in items:
        i = it["id"]
        n = notes.get(best, {}).get(i, {})
        item_rows.append({"id": i, "reference": refs.get(i), **{v: scores.get(v, {}).get(i) for v in vs},
                          f"error ({best})": errs_best.get(i), "direction": n.get("direction", ""), "comment": n.get("comment", "")})
    rnds = sorted({e["round"] for x in checklist.values() for e in x["history"]})
    check_rows = [{"id": k, "title": x["title"], "status": x["status"], "direction": x["direction"], "items": x["items"],
                   "root_cause": x["root_cause"], "clause": x["clause"], "fix": x["fix"],
                   **{f"r{r}": next((f"{e['status']} ({e['mean_error']:+.2f})" for e in x["history"] if e["round"] == r), "")
                      for r in rnds}} for k, x in checklist.items()]
    note_rows = [{"version": v, "id": i, **{k: n.get(k, "") for k in ("direction", "observations", "model_reasoning", "clause", "comment")}}
                 for v in vs for i, n in sorted(notes.get(v, {}).items())]
    edit_rows = [{"version": v, "verdict": c.get("verdict", ""), "from": c.get("parent", ""), "issue": e["issue"],
                  "old_text": e["old_text"], "new_text": e["new_text"]}
                 for v, c in changes.items() for e in c.get("edits", [])]
    edit_rows += [{"version": v, "verdict": c.get("verdict", ""), "from": c.get("parent", ""), "issue": "(rewrite)",
                   "old_text": "", "new_text": "\n\n".join(c["rewrite"])} for v, c in changes.items() if c.get("rewrite")]
    locked_rows = [{"round": r["round"], "best": r["best"], "layer": x["layer"], "clause": x["clause"], "items": x["items"], "why": x["why"]}
                   for r in rounds for x in r.get("locked", [])]
    round_rows = [{"round": r["round"], "best": r["best"], "mode": r["mode"], "overview": r["overview"], "summary": r["summary"]}
                  for r in rounds]
    return {"Versions": versions, "Rounds": round_rows, "Items": item_rows, "Checklist": check_rows, "Judge notes": note_rows,
            "Edits": edit_rows, "Locked flags": locked_rows}
