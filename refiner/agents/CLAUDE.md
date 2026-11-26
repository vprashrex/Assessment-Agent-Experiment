# agents/ — the model-backed agents

Everything that talks to a model. `__init__.py` re-exports what the engine uses, so callers write `agents.parse(…)`,
`agents.review(…)`, `agents.metrics_of(…)`.

| File | What it does |
|---|---|
| `parser.py` | once per run: reads the sheet profile and the rubric, returns columns, metrics, layers and questions (`SETUP_SCHEMA`); code then checks every answer against the sheet and the rubric |
| `scorer.py` | per item: the scoring model applies a rubric version, exactly as in production: the rubric as system prompt, a JSON answer (`llm.call`), or, for a decision model (`providers/decisions.py`), the rubric as evidence, one question per metric, probabilities back; `parse_output` validates the value; `score_all` runs its workers in copies of the caller's context (`llm.uncapped`) |
| `judge.py` | per item: why the score differs from the reference (`ITEM_SCHEMA`: direction, clause, comment); per round: the issues (`SUMMARY_SCHEMA`: overview, issues, summary), one call, no tools — code hands it the measured numbers and measures every issue afterwards; `ROUND_DEFAULTS` fills the mode/locked fields the loop still reads; `synthetic_reviews` for the shared stages; the per-item table and the checklist text |
| `generator.py` | per round: the next version, as edits (`replace`, `insert_after`, `delete`) on EDITABLE text or a rewrite of the metrics parts (`GEN_SCHEMA`); no length target — it decides the length and the shrink loop trims afterwards; refuses edits to locked text |
| `layers.py` | shared by all four: the rubric's layers (`LAYERS`, `EDITABLE` per metric, `PROCEDURE` shared and tuned as a whole), `layout` / `assemble` / `annotated` / `numbered`, `metrics_of`, `reference`, `refs_by`, `kind_of` (how an output's errors are measured), an item's attached files (`files_of`) |
| `math_tool.py` | every number: MAE, bias, within ±1/±2, accuracy, exact (`alignment` / `summary` / `agreement`), `compare`, pattern threshold T(n), `volatility`, `diagnose`, the gate `keep_candidate` and `pool` (the two-pass mean). Used by `engine/loop.update_checklist` (issue status) and `engine/loop.decide` (the gate) |
| `llm.py` | `call(model, system, user, schema, …)`: picks the provider, retries transport errors and bad JSON, checks required keys, records tool calls; refuses to start a call above `HARD_CAP` (1.25 × the run's budget), except inside `uncapped()` (the fixed-size end work; a context variable, so the parallel metric loops stay capped) |
| `spend.py` | the run's cost ledger: every provider response is priced from `models.yaml` (`record`), mirrored to `<run>/spend.json` (`attach`), restored on resume (`start`), totalled per model and per role (`role(...)`, a context variable `llm.call` sets from its `role` argument); `total`, `snapshot`, `unpriced`, `BudgetExceeded` |
| `models.py` | reads `models.yaml`: which provider serves a model, its reasoning setting for the run's effort, its output limit |
| `providers/` | one module per provider behind the same `complete` function (see providers/CLAUDE.md) |

Rules:
- Prompt text lives in `refiner/prompts/`; agents only fill templates (`prompts.render`) and load system prompts.
- A schema changed here → change its system prompt in `prompts/system/`.
- The generator never sees reference values or model outputs; only directions and error sizes (`judge.table`).
- All maths stays in `math_tool.py`; the judge measures nothing — code gives it the numbers and verifies its issues.
