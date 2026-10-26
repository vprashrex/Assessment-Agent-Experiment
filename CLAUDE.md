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
│   ├── engine/          items (sheet -> items), loop, fanout (+ composer), report, events
│   ├── mcp/             server.py (12 actions), routes.py (uploads, SSE, health, run files), inspect.py
│   ├── prompts/         every prompt the refiner sends, nothing inline in code: system/, user.py, judge_tools.py, mcp.py
│   ├── utils/           helpers with no refiner logic: excel, documents, downloads, files, process
│   ├── api.py           public functions: prepare, refine, start, stop, status, checklist, version, list_runs
│   ├── config.py        RunConfig, shared by the CLI, the API and the MCP server
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
└── .env                 ANTHROPIC_API_KEY, OPENAI_API_KEY (never print or commit)
```

## Commands

```bash
uv sync                                           # environment from uv.lock
uv run refiner --sheet S.xlsx --context C.md --prompt v0.md --run runs/NAME [--schema out.json] \
    [--docs-dir DIR] [--model gpt-6.1-sol] [--effort low|medium|high] [--n N] [--rounds 8]
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
  call sends in `user.py` (a template; `agents/` fills its `{placeholders}`), the judge's tool descriptions in
  `judge_tools.py`, the server's instructions and action descriptions in `mcp.py`. Code loads them and never holds
  prompt text itself. Keep them generic and plain.
- **The generator never sees reference values.** It gets the judge's diagnosis, the checklist and a per-item
  table with directions and error sizes only. The judge's prompt forbids leaking reference values.
- **Only the metrics layer is ever edited.** Program, notes and output layers stay word for word. Code refuses
  edits to locked text and asserts the locked layers are unchanged before a candidate is saved.
- **All maths is deterministic Python in `agents/math_tool.py`.** The judge measures through tool calls to the same
  functions the gate uses. The judge cannot change thresholds; tool schemas do not expose z or the ratio.
- **No variance or consistency metrics.** The refiner targets agreement with the reference only: MAE, bias,
  within ±1, within ±2.
- **Issue statuses are measured by code** (`update_checklist` in `engine/loop.py`), never declared by the judge.
- **MCP uses the `fastmcp` package** (not the raw `mcp` SDK). Dependencies via uv. Long-running tools start
  background processes and return at once; Claude Desktop times out on long calls.
- **Attachments go to models as files** (PDF and images), not only as extracted text.
- **Programme data stays in `z_assessment/`** (gitignored), never in tracked files: no sheets, contexts, prompts,
  results or programme names in the repo or its docs.
- Submission files in `z_assessment/`, `runs/` and `cache/` are real people's writing. Do not paste their text into chats,
  logs or docs; work with ids, file names and numbers.

## Key facts

- Gate: a candidate is kept only if its MAE is strictly lower than the best's.
- Pattern threshold T(n) = 2 · scatter / √n; a group is real if |mean error| > T(n). Volatile = |bias| ≤ T(N) and
  scatter / sd(reference) ≥ 0.75. Rewrite mode only when volatile and no issue is real.
- Issue status, by code each round: first time real → new, else watch; active and real → open, else resolved;
  resolved and real again → reopened.
- Stop: round ceiling (8), target MAE, or 4 rejected rounds in a row.
- Models lock when refinement starts: `<run>/models.json` (parser, judge, generator, scorer, effort); a resume with
  other models is refused (`api.lock_models`), so every version is scored by the same models. Only the UI's chat
  agent model can change mid-run.
- Kept candidates get full judge notes; rejected ones only for the items they pushed further away.
- Several metrics: each metric's loop sees only the locked layers and its own metrics chunks (tagged `metric`);
  the composer is code, stitching each best section into the original layout, never a model rewriting text.

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
