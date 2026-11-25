# CLAUDE.md — rubric-refiner

This project refines an assessment prompt (a rubric) until a scoring LLM's outputs agree with the reference
judgements people already made on the same submissions. NGOs use it for many different programmes, so nothing in
the code or the prompts may be specific to one programme.

`README.md` explains how it works and how to use it. This file holds the rules for changing it.

## Layout

```
rubric-refiner/
├── CLAUDE.md            this file
├── README.md            how it works and how to use it
├── refiner/             the Python package; every folder has a CLAUDE.md saying what each file does
│   ├── agents/          parser, scorer, judge, generator; layers; math_tool.py; llm.py + models.py;
│   │                    providers/ (anthropic, openai, gemini behind one complete())
│   ├── engine/          items (sheet -> items), split (train/test), loop, fanout (+ composer, polish, test pass), run,
│   │                    report, events
│   ├── mcp/             server.py (12 actions), routes.py (uploads, SSE, health, run files), inspect.py
│   ├── prompts/         every prompt the refiner sends, nothing inline in code: system/, user.py, mcp.py
│   ├── utils/           helpers with no refiner logic: excel, documents, downloads, files, process
│   ├── api.py           public functions: prepare, refine, start, stop, status, checklist, version_report, rubric, report
│   ├── config.py        RunConfig + DEFAULTS + HELP: the one source of options, defaults and help text for the CLI,
│   │                    the API and the MCP server (the CLI builds its flags from it)
│   └── paths.py         refiner-data/ layout and ROOT (the project folder)
├── z_assessment/       programme (NGO) data, one folder per programme: sheets, context, prompts, schemas,
│                        docs/, delivered results (gitignored; never commit anything programme-specific)
├── runs/                one folder per run (gitignored)
├── refiner-data/        chats/<chat_id>/{inputs/, run/}: the server's own files, only it writes there (gitignored;
│                        RUBRIC_REFINER_DATA). A chat's conversation is not here: the Kaapi backend keeps it
├── docs/                architecture.md, database.md (tables, memory, pg_cron heartbeat), transport.md (SSE)
├── cache/files/         downloaded attachments, keyed by link (gitignored)
├── models.yaml          every model: provider, roles, effort options, pricing; served at GET /models for the UI
├── pyproject.toml, uv.lock
├── .mcp.json            the MCP server for Claude Code in this folder
└── .env                 ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY (never print or commit)
```

## Commands

```bash
uv sync                                           # environment from uv.lock
uv run refiner --sheet S.xlsx --prompt v0.md --run runs/NAME [--context C.md] [--schema out.json] \
    [--docs-dir DIR] [--model M] [--effort low|medium|high] [--n N] [--rounds 8] [--split 80/20] [--seed 0] [--budget USD]
uv run refiner ... --prepare                      # setup only: columns, layers, attachments, questions
uv run fastmcp run refiner/mcp/server.py:mcp      # the MCP server by hand (stdio)
uv run refiner-server                             # HTTP on 127.0.0.1:8765, what Kaapi uses
```

Rerunning the same command resumes the run. A cheap smoke test is `--n 6 --rounds 2 --model claude-opus-5-5
--effort low` on a fresh run folder; copy an existing `setup/setup.json` into it to skip the parser call.

## Rules

- **Generic only.** No programme names, metric names, column names or domain examples in code or prompts. The
  parser decides columns and layers; code stays agnostic.
- **Every prompt lives in `refiner/prompts/`**, one file each: an agent's system prompt in `system/`, the message a
  call sends in `user.py` (a template; `agents/` fills its `{placeholders}`), the server's instructions and action
  descriptions in `mcp.py`. Code loads them and never holds
  prompt text itself. Keep them generic and plain.
- **The generator never sees reference values.** It gets the judge's diagnosis, the checklist and a per-item
  table with directions and error sizes only. The judge's prompt forbids leaking reference values.
- **Only the metrics and procedure layers are ever edited.** `metrics` per metric in its own loop; `procedure`
  (shared scoring logic: gates, decision order, tie-breaks) as a whole, before the per-metric loops (fan-out) or in
  the same loop (one metric). Program, notes and output stay word for word; code refuses edits to locked text and
  asserts it unchanged before a candidate is saved.
- **All maths is deterministic Python in `agents/math_tool.py`.** The judge measures nothing: code writes the
  version's numbers into its prompt and, after it names issues, measures each one (`update_checklist`). No tool
  loop, no thresholds in the judge's hands.
- **Agreement with the reference is the target**: MAE, bias, within ±1, within ±2, exact matches. Scatter and
  the flip count between two passes are diagnostics (`volatility`, `diagnose`), never gate criteria.
- **Train only, until the end.** The split (`engine/split.py`, `setup/split.json`, drawn once) decides which items
  the loops may touch; scoring, judge notes, the checklist, the gate and the stop rules use train. Test items are
  scored once when everything has stopped (`loop.score_test`, `fanout.test_pass`); `split.guard` refuses them
  before that. Never look at or select on test numbers while tuning — by hand either.
- **Issue statuses are measured by code** (`update_checklist` in `engine/loop.py`), never declared by the judge.
- **MCP uses the `fastmcp` package** (not the raw `mcp` SDK). Dependencies via uv. Long-running tools start
  background processes and return at once; Claude Desktop times out on long calls.
- **Attachments go to models as files** (PDF and images), not only as extracted text.
- **Programme data stays in `z_assessment/`** (gitignored), never in tracked files: no sheets, contexts, prompts,
  results or programme names in the repo or its docs.
- Submission files in `z_assessment/`, `runs/` and `cache/` are real people's writing. Do not paste their text into chats,
  logs or docs; work with ids, file names and numbers.

## Key facts

- Gate (`loop.decide` → `math_tool.keep_candidate`): exact matches decide, measured twice — a first-pass winner
  (more exact, or equal exact and lower MAE) is scored once more and the pooled numbers give the verdict; equal
  accuracy and shorter is kept outright. No word limit or price: length is handled by the shrink loop. `--target`
  is a stop rule (train MAE), not a gate criterion.
- Split: `--split 80/20 --seed 0` by default, stratified by reference score; `100/0` = no holdout. Fixed at
  preparation like `--n`; a resume with other values keeps the stored split (debug.txt says so). Reports carry
  train numbers as `before/after` and the held-out numbers as `test` (`report.json` kpis, `api.status` rows,
  `results.xlsx` Agreement/Items).
- Pattern threshold T(n) = 2 · scatter / √n; a group is real if |mean error| > T(n). Volatile = |bias| ≤ T(N) and
  scatter / sd(reference) ≥ 0.75. Rewrite mode only when volatile and no issue is real.
- Issue status, by code each round: first time real → new, else watch; active and real → open, else resolved;
  resolved and real again → reopened.
- Stop: round ceiling (8), target MAE, 4 rejected rounds in a row, or `--budget` reached (checked at every round
  boundary, in the fan-out stages too). Spend: `agents/spend.py` prices every provider response from `models.yaml`
  (retries and tool turns included), mirrors the ledger to `<run>/spend.json`, and `llm.call` refuses any call above
  1.25 × budget (`BudgetExceeded`). An unpriced model counts as $0 and is named in the SPENT line — add its price.
- Models lock when refinement starts: `<run>/models.json` (parser, judge, generator, scorer, effort); a resume with
  other models is refused (`api.lock_models`), so every version is scored by the same models. Only the UI's chat
  agent model can change mid-run.
- Kept candidates get full judge notes; rejected ones only for the items they pushed further away.
- Several metrics: each metric's loop edits only its own metrics chunks; the other metrics' sections stay in its
  prompt as locked `peer` chunks (the scorer reads the rubric as production serves it). The composer is code,
  stitching each best section into the layout; the `polish` stage then tunes the weakest target against the whole
  prompt's total exact matches (procedure every second round).

## When you change something

- A model (add, remove, defaults, roles) → `models.yaml` only; the refiner and the UI both read it.
- A schema in `agents/<agent>.py` → the matching prompt in `refiner/prompts/system/` (and `prompts/CLAUDE.md`).
- The run folder or Excel sheets → the `engine/loop.py` docstring and `README.md`.
- A file added, moved or renamed → the CLAUDE.md of its folder.
- Maths → the formulas in the `agents/math_tool.py` docstring.

## Gotchas

- `providers/base.clean_schema` strips JSON-schema metadata keys (title, minimum, ...) but must keep property names; a property
  called `title` was once silently dropped.
- The server shares no folder with Kaapi: uploads come in over HTTP (`POST /chats/{id}/inputs`), context notes
  through `add_context_note`. Never read or write a chat's transcript or agent history here.
- `fastmcp run` loads `mcp/server.py` by file path, so the mcp/ files use absolute imports (`from refiner import api`).
- Use `paths.ROOT` for the project folder, never `Path(__file__).parents[N]`: modules sit at different depths.
- Claude Desktop starts servers with a short PATH; its config uses the absolute path to `uv`.
- Items store attachment paths relative to the project root (older runs) or absolute (newer runs); both resolve.
- Run folders from before the split have no `setup/split.json`: every reader treats them as all-train, no test.
- Git history: commits `cb27646`, `591c220`, `9cbe4c4`, `ec16b19`, `dfebfe9` (on `origin/feat/code-update`) carry
  programme prompts and sheets from before the `z_assessment/` rule. HEAD is clean; the history has not been
  rewritten (owner's call). Do not cherry-pick or revive files from those commits.
