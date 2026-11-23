# engine/ — runs a refinement

| File | What it does |
|---|---|
| `items.py` | sheet → items: the input columns as text, linked documents and attachments (PDFs and images kept as files), the reference values |
| `split.py` | the train/test split: `make` (seeded, stratified by reference score, written once to `setup/split.json`), `read` (older runs = all train), `part` / `filter_refs`, and `guard`, which refuses to score a test item while refining |
| `run.py` | `main`: setup, then one loop (or the fan-out), then `report.json`. What `api.refine` calls |
| `loop.py` | `setup_run` / `_setup` (parser, items, split, layers). `refine`: score → review → diagnose → edit → gate, on the train items, until a stop rule fires; then the shrink loop (`simplify`) and the one scoring of the test items (`score_test`). `decide` is the gate measured twice, shared with the fan-out stages. `update_checklist` measures each issue's status. Its docstring describes the run folder |
| `fanout.py` | several metrics: the shared stage (`refine_procedure`: tunes the `procedure` layer against all metric–item pairs, `PROCEDURE_ROUNDS`), one sub-run per metric in parallel (`metric_subrun`: its prompt keeps the other metrics' sections as locked `peer` chunks, so the scorer reads the rubric as production serves it), the composer (`compose`), the composed stage (`polish`: up to `POLISH_ROUNDS` editing the weakest target against the whole prompt's total exact matches), then `test_pass`: the original and the final prompt scored once on the held-out items |
| `report.py` | `report.json`: meta (with the split), before/after numbers on train and on test, version lineage and every version's rubric section, for the UI |
| `events.py` | run events: one JSON line per event in `<run>/events.jsonl`, which the server streams and resumes from |

Rules:
- Every step writes to the run folder first, so a rerun resumes where it stopped.
- Train only, until the end: scoring, judge notes, the checklist, the gate and the stop rules never see a test item
  (`split.guard` asserts it). Test is scored once, after the loop has stopped (`metric.test` / `composed.test`).
- The gate (`loop.decide` → `math_tool.keep_candidate`): exact matches decide, measured twice — a first-pass winner
  is scored once more and the pooled numbers (`math_tool.pool`) give the verdict; equal accuracy and shorter is kept
  outright. Once the loop stops, the shrink loop (`loop.simplify`, MODE: SIMPLIFY, versions `vS`, `vS2`, …)
  compresses the best version pass after pass while the exact matches hold, and `math_tool.diagnose` writes a
  plain-language note (dataset / rubric-context / scorer) with one action, emitted as `metric.diagnosis`.
- Issue statuses are measured by code (`update_checklist`), never declared by the judge.
- Prompt text (overviews, markers, the `last_change` note) comes from `prompts/user.py` through `prompts.render`.
- The run folder or Excel sheets changed → update the `loop.py` / `fanout.py` docstrings and the root README.
