# engine/ — runs a refinement

| File | What it does |
|---|---|
| `items.py` | sheet → items: the input columns as text, linked documents and attachments (PDFs and images kept as files), the reference values |
| `loop.py` | `main`: setup, then one loop per metric (or the fan-out). `refine`: score → review → diagnose → edit → gate, until a stop rule fires. `update_checklist` measures each issue's status. Its docstring describes the run folder |
| `fanout.py` | several metrics: one sub-run each (`metrics/<key>/`), in parallel; then the composer stitches each best section into the original layout and scores the whole prompt once |
| `report.py` | `report.json`: meta, before/after numbers, version lineage and every version's rubric section, for the UI |
| `events.py` | run events: one JSON line per event in `<run>/events.jsonl`, which the server streams and resumes from |

Rules:
- Every step writes to the run folder first, so a rerun resumes where it stopped.
- The gate keeps a candidate only if its MAE is strictly lower than the best's.
- Issue statuses are measured by code (`update_checklist`), never declared by the judge.
- The run folder or Excel sheets changed → update the `loop.py` docstring and the root README.
