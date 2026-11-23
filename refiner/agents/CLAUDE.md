# agents/ — the model-backed agents

Everything that talks to a model. `__init__.py` re-exports what the engine uses, so callers write `agents.parse(…)`,
`agents.review(…)`, `agents.metrics_of(…)`.

| File | What it does |
|---|---|
| `parser.py` | once per run: reads the sheet profile and the rubric, returns columns, metrics, layers and questions (`SETUP_SCHEMA`); code then checks every answer against the sheet and the rubric |
| `scorer.py` | per item: the scoring model applies a rubric version, exactly as in production (its system prompt is the rubric); `parse_output` validates the value |
| `judge.py` | per item: why the score differs from the reference (`ITEM_SCHEMA`); per round: the issues, measured with the maths tools (`SUMMARY_SCHEMA`); `tools(E, refs, kind)` builds the judge's five measuring tools for a loop (schemas here, descriptions in `prompts/judge_tools.py`); `synthetic_reviews` for the shared stages; the per-item table and the checklist text |
| `generator.py` | per round: the next version, as edits (`replace`, `insert_after`, `delete`) on EDITABLE text or a rewrite of the metrics parts (`GEN_SCHEMA`); no length target — it decides the length and the shrink loop trims afterwards; refuses edits to locked text |
| `layers.py` | shared by all four: the rubric's layers (`LAYERS`, `EDITABLE` per metric, `PROCEDURE` shared and tuned as a whole), `layout` / `assemble` / `annotated` / `numbered`, `metrics_of`, `reference`, `refs_by`, `kind_of` (how an output's errors are measured), an item's attached files (`files_of`) |
| `math_tool.py` | every number: MAE, bias, within ±1/±2, accuracy, exact (`alignment` / `summary` / `agreement`), `compare`, pattern threshold T(n), `volatility`, `diagnose`, the gate `keep_candidate` and `pool` (the two-pass mean). Used by the judge's tools and by `engine/loop.decide` |
| `llm.py` | `call(model, system, user, schema, …)`: picks the provider, retries transport errors and bad JSON, checks required keys, records tool calls |
| `models.py` | reads `models.yaml`: which provider serves a model, its reasoning setting for the run's effort, its output limit |
| `providers/` | one module per provider behind the same `complete` function (see providers/CLAUDE.md) |

Rules:
- Prompt text lives in `refiner/prompts/`; agents only fill templates (`prompts.render`) and load system prompts.
- A schema changed here → change its system prompt in `prompts/system/`.
- The generator never sees reference values or model outputs; only directions and error sizes (`judge.table`).
- All maths stays in `math_tool.py`; the judge measures through tools whose schemas do not expose z or the ratio.
