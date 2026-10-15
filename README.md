# Rubric refiner

Refines an assessment prompt (a rubric) until a scoring model's outputs agree with the reference judgements
people already made on the same submissions. It works for any programme: nothing in the code or the prompts is
specific to one use case.

## How it works

1. **Parser** (once). Reads the sheet, the operator notes, the prompt and an optional output schema. Picks the
   id, input and reference columns and the output field. Cuts the prompt into four layers:
   - **program**: role, persona, programme context. Locked.
   - **metrics**: the criteria, their scales, levels and guidance. The only layer that is ever edited.
   - **notes**: rules that apply across all metrics. Locked.
   - **output**: the answer format. Locked.
   It asks questions instead of guessing when anything is unclear.
2. **Scorer**. The production model scores every submission with the current prompt. PDFs and images go to the
   model as files; DOCX gives its text and embedded images.
3. **Judge**. Reviews every submission on its own: the whole prompt, the text and attachments, the output and
   the reference. Writes notes: what the submission is, what the model responded to, why it differs. Then it reads
   all the notes together, measures with deterministic tools, finds root causes and keeps an issue checklist.
   Issues in a locked layer are flagged for the programme owner, never edited.
4. **Generator**. Never sees reference values. Reads the checklist and the per-item table, and edits the metrics
   layer. Edits are spliced in by code; an edit that touches a locked layer is refused.
5. **Gate**. The candidate is kept only if its MAE beats the best so far. Then the next round starts.

All maths lives in `math_tool.py`: MAE, bias, within ±1 / ±2, the dynamic pattern threshold z·scatter/√n and the
volatility test. Each issue's status (new, open, resolved, reopened, watch) is measured by code every round.

The run stops at the round ceiling, at the target MAE, or after `patience` rejected rounds in a row.

### Several metrics: fan-out

When the rubric scores several metrics and the sheet holds a reference for each, the parser returns one entry per
metric (key, reference column, output field) and tags each metrics section with the metric it scores. The run then:

1. **Splits.** Each metric gets its own sub-run, `metrics/<key>/`, an ordinary run folder. Its prompt is the locked
   layers (program, notes, output) plus that metric's own section; the other metrics' sections are left out.
2. **Refines in parallel.** Every metric runs its own scorer → judge → generator → gate loop at the same time,
   editing only its own section, with its own checklist and stop rules.
3. **Composes.** Code (not a model) puts each metric's best section back into the original prompt, so locked text
   stays word for word, then scores the original v0 and the composed prompt once each, with every metric's field
   together. `results.xlsx` compares, per metric, alone v0 → best and together v0 → final.

One metric runs exactly as before, in the run folder itself.

## Use

Command line:

```bash
python -m refiner --sheet z_assessment/<programme>/sheet.xlsx --context z_assessment/<programme>/context.md \
    --prompt z_assessment/<programme>/v0.md --run runs/my-run --schema z_assessment/<programme>/output_schema.json \
    --docs-dir z_assessment/<programme>/docs --model gpt-6.1-sol --effort high --mode pro
python -m refiner ... --prepare     # setup only: columns, layers, attachments, questions
```

Rerun the same command to resume. The sheet may be `.xlsx` or `.csv`. Keep each programme's inputs (sheet, context,
prompt, schemas, downloaded documents) in `z_assessment/<programme>/`: that folder is gitignored, so programme data
never reaches the repository.

Python:

```python
from refiner import RunConfig, prepare, start, status

cfg = RunConfig(sheet="z_assessment/<programme>/sheet.xlsx", context="z_assessment/<programme>/context.md",
                prompt="z_assessment/<programme>/v0.md", run="runs/my-run")
prepare(cfg)          # review the setup, or answer its questions in the context file
start(cfg)            # background; or refine(cfg) to run in this process
status("runs/my-run")
```

MCP server (FastMCP, stdio), with the tools `prepare_run`, `start_run`, `run_status`, `get_checklist`,
`get_version`, `get_final_prompt`, `list_runs` and `stop_run`. `prepare_run` and `start_run` launch background
processes and return at once; poll `run_status`.

```bash
uv lock                                              # dependencies from pyproject.toml
fastmcp install claude-desktop refiner/mcp_server.py:mcp --name rubric-refiner \
    --project "$PWD" --env REFINER_WORKDIR="$PWD"     # adds it to Claude Desktop's config
uv run fastmcp run refiner/mcp_server.py:mcp         # or run it by hand
```

Claude Desktop starts servers with a short PATH, so use the absolute path to `uv` as the command in
`claude_desktop_config.json`. Restart Claude Desktop after installing. `REFINER_WORKDIR` is the folder that relative
paths resolve against. API keys are read from `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`, or from a `.env` file in
the project.

## Tracing (Langfuse)

`TRACING=true` in `.env` (or the environment) traces every run to Langfuse, with `LANGFUSE_PUBLIC_KEY`,
`LANGFUSE_SECRET_KEY` and `LANGFUSE_BASE_URL` set. Anything else, or no `TRACING`, means off: Langfuse is never imported
and nothing changes. All of it lives in `refiner/tracing.py`. All traces of a run share one session, named after the
run folder.

```
prepare-run       parse-sheet (generation)
refine-round      score-items  > score-item (generation, one per submission)
                  review-items > review-item (generation, one per submission)
                  summarise-round (agent) > summarise-round (generation per turn) · alignment, compare, … (tool)
                  write-candidate (generation)
```

Each model request is its own generation with the model, token usage and thinking, so cost per round and per step
shows in Langfuse. Attached files are recorded as a placeholder (type and size), never uploaded; submission text is
sent as written, so use a Langfuse project you are allowed to hold it in. `LANGFUSE_TRACING_ENVIRONMENT` separates
test runs from real ones.

## Run folder

```
runs/<run>/
├── results.xlsx        Results (id and input columns, then the best prompt's whole answer, one column per output key;
│                       nested keys joined with _) · Agreement (exact, within 1, average gap) · Versions · Rounds ·
│                       Items · Checklist · Judge notes · Edits · Locked flags
├── final_prompt.md     the best version's full prompt
├── debug.txt           per round: numbers, the judge's overview, the checklist, locked flags, tool calls (fan-out: every metric's, prefixed [key])
├── checklist.json      the issue checklist with per-round status
├── dialogue.md         the judge and the generator, round by round
├── state.json          for resuming
├── run.log             output of a background run
├── setup/              setup.json · items.json · baseline/ (the four layers + layout.json)
└── versions/vN/        prompt.md · chunks.json · scores.json · outputs.json · notes.json · change.md · result.xlsx
```

With several metrics the run folder holds `setup/`, one `metrics/<key>/` run folder per metric (laid out as above;
there is no top-level `versions/`), `composed/baseline/` and `composed/final/` (scores.json · outputs.json),
`composed.json`, `final_prompt.md` (the composed prompt) and `results.xlsx` (Results · Agreement · Metrics · Items),
where Results holds the composed prompt's whole answer for every item. `run_status` on the run reports every metric; pass
`runs/<run>/metrics/<key>` for one metric's details.

## Files

| File | What it does |
|---|---|
| `config.py` | `RunConfig`, shared by the CLI, the API and the MCP server |
| `api.py` | public functions |
| `loop.py` | the refinement loop and the checklist |
| `agents.py` | parser, scorer, judge, generator calls; layer split and edit splicing |
| `math_tool.py` | all alignment maths |
| `data.py` | sheet reading, attachments |
| `llm.py` | Anthropic and OpenAI calls, files, tool calling |
| `tracing.py` | Langfuse traces: one per prepare and per round, a generation per model request |
| `excel.py` | the Excel files |
| `mcp_server.py` | the MCP server |
| `prompts/` | one generic prompt per agent: parser, judge, generator |
