# refiner/ — the package

The refiner improves a rubric until a scoring model's outputs agree with people's reference scores. Each folder has
its own CLAUDE.md with one line per file; the project rules are in the root CLAUDE.md.

| Folder / file | What it is |
|---|---|
| `agents/` | the four model-backed agents (parser, scorer, judge, generator), the maths, the model call and the providers |
| `engine/` | runs a refinement: sheet → items, the train/test split, the loop per metric, the fan-out and composer, the held-out test pass, run events, the report |
| `mcp/` | the server: MCP actions for the Chat Agent, HTTP routes for uploads, events, health and run files |
| `prompts/` | every piece of text sent to a model; nothing is written inline in code |
| `utils/` | helpers with no refiner logic: spreadsheets, documents, downloads, file reading, processes |
| `api.py` | the public functions (prepare, refine, start, stop, status, checklist, version_report, rubric, report, results_file, health); the CLI and the server call these |
| `config.py` | `RunConfig`: every setting of a run; `DEFAULTS` and `HELP` are the one source of defaults and option text for every surface; `run_models()` for the lock |
| `paths.py` | where the refiner keeps a chat's files (`refiner-data/chats/<id>/{inputs,run}`) and `ROOT`, the project folder |
| `__main__.py` | the CLI: `uv run refiner …`; emits `run.started` / `run.done` / `run.failed` around a run |
| `__init__.py` | re-exports the API: `from refiner import RunConfig, prepare, start, status` |

Dependency direction: `mcp` and `__main__` → `api` → `engine` → `agents` → `prompts`, with `utils` usable from
anywhere and depending on nothing above it. Use `paths.ROOT` for the project folder, never `parents[N]`.
