# Rubric Improvement Agent

An agent that rewrites an LLM scoring rubric until the scores it produces stop wobbling.

You give it a spreadsheet of submissions and (optionally) the rubric prompt you use today. It scores
every submission **k times with the same rubric**, measures how much those k scores disagree with each
other, rewrites the rubric, and measures again. A revision is kept only when the disagreement shrinks by
more than its own measurement error. The objective is **self-consistency, not agreement with humans** —
the same submission should get the same score every time it is scored.

Everything is provider-agnostic: nothing in the code names a metric, a column, or an organisation. The
parser agent reads your sheet and your context file and works out the columns and the output schema.

---

## 1. Requirements

- Python 3.12
- An Anthropic API key (generator + parser + attachment describer)
- A key for whichever model you use as the scorer — Gemini by default

There is **no `requirements.txt` or lockfile** in this repo yet. Create the environment by hand:

```bash
python3.12 -m venv .venv
.venv/bin/pip install \
  anthropic==1.5.0 \
  langgraph==1.2.11 langgraph-checkpoint-sqlite==3.1.1 \
  langchain==1.4.0 langchain-core==1.6.3 langchain-google-genai==4.4.0 \
  pandas==3.0.5 openpyxl==3.1.5 httpx==0.28.1 pillow==12.3.0 \
  matplotlib==3.11.2 python-dotenv==1.2.3 pydantic==2.13.5
```

Those are the versions the last run was executed on. Swap `langchain-google-genai` for
`langchain-openai` (or another LangChain provider package) if you point the scorer elsewhere.

### API keys

Create `.env` in the repo root — it is gitignored and loaded automatically:

```
CLAUDE_API_KEY=sk-ant-...
GEMINI_API_KEY=...
```

`ANTHROPIC_API_KEY` works in place of `CLAUDE_API_KEY`. The scorer looks for
`GEMINI_API_KEY` or `GOOGLE_API_KEY` for `google_genai`, `OPENAI_API_KEY` for `openai`, and
`ANTHROPIC_API_KEY` or `CLAUDE_API_KEY` for `anthropic`.

---

## 2. Inputs you provide

| File | Required | What it is |
|---|---|---|
| Spreadsheet (`.xlsx`) | yes | One row per submission. Multiple sheets are fine; the parser picks one. |
| `context.md` | yes | Plain-English operator notes: which sheet, which column is the id, which columns to use, which to ignore. |
| Rubric prompt (`.md`) | no | Your current production prompt, used as v0. Omit it and the generator drafts v0 from scratch. |
| Output schema (`.md` or `.json`) | no | The JSON object the scorer must return. Omit it and the parser proposes one and asks you to confirm. |

A minimal `context.md`:

```markdown
# Operator context

## Sheet
File: my_data.xlsx, sheet `Submissions` (ignore the `Reviewers` sheet).
One row = one submission.
- id column: `ID`
- use: `Title`, `Problem`, `Solution`, `Language`, `Attachment Links`
- ignore: `State`, `District`, `Video Link`, and any empty or unnamed columns

Videos are never evaluated. Attachment links are replaced by a neutral text description.

## Task
The rubric being improved is my_prompt.md (v0, currently in production).
The output schema is my_schema.md (frozen). Metrics, scale and meanings come from those two files.
```

Keep the metric definitions in the rubric and the schema, not in `context.md` — restating them in two
places is how they drift apart.

The schema drives everything downstream: any numeric field named `<Metric>_score` (with an optional
`<Metric>_reason` beside it) becomes a tracked metric, and the `minimum`/`maximum` become the scale.

---

## 3. Running it

All commands are `python -m rubric_agent.cli <subcommand>`. Use the venv's interpreter.

### Start a run

```bash
.venv/bin/python -m rubric_agent.cli run \
  --sheet my_data.xlsx \
  --context context.md \
  --run runs/my-run \
  --prompt my_prompt.md \
  --schema my_schema.md \
  --k 4 \
  --rounds 30
```

`--sheet`, `--context` and `--run` are required; everything else has a default.

| Flag | Default | Effect |
|---|---|---|
| `--prompt` | none | Starting rubric (v0). Omitted → the generator drafts v0. |
| `--schema` | none | Output schema. Omitted → the parser proposes one. |
| `--k` | 4 | Times each submission is scored per round. This is the measurement; below 4 the error bars swamp the signal. |
| `--n` | whole sheet | Subsample size. Use a small `--n` for a smoke test. |
| `--rounds` | 30 | Hard ceiling on rounds. A safety net, not the intended stop. |
| `--scorer` | `google_genai:gemini-3.1-flash-lite-preview` | `provider:model` for the scorer. |
| `--scorer-params` | `{}` | JSON kwargs for the scorer model, e.g. `'{"temperature":0}'`. |
| `--max-attachments` | unlimited | Cap on attachments fetched and described. Useful for a first smoke run. |
| `--review` | off | Pause after the parser writes `setup.md` so you can edit it before the loop starts. |

**Start small.** The first run on a new dataset should be `--n 40 --k 4 --rounds 3`. A full run on ~1000
rows at k=4 is roughly 4,000 scorer calls *per round*.

### Long runs

A round takes minutes, a full run hours. Run it detached and watch the log:

```bash
mkdir -p runs/my-run
nohup .venv/bin/python -m rubric_agent.cli run \
  --sheet my_data.xlsx --context context.md --run runs/my-run \
  --prompt my_prompt.md --schema my_schema.md \
  > runs/my-run/run.log 2>&1 &

tail -f runs/my-run/run.log
```

### Answering the parser

If the parser cannot work out a column or the schema, the graph pauses and prints its questions. Reply:

```bash
.venv/bin/python -m rubric_agent.cli answer --run runs/my-run "ID is the id column; ignore Reviewer Notes"
```

### After a crash

State is checkpointed to SQLite in the run directory, so a run resumes where it stopped:

```bash
.venv/bin/python -m rubric_agent.cli resume --run runs/my-run
```

Parsing, attachment description and each round's scores are all written to disk and reused, so a resume
does not re-pay for completed work.

### Feeding in human feedback

Once a run has finished, hand it human comments and let it continue from the best rubric:

```bash
.venv/bin/python -m rubric_agent.cli continue --run runs/my-run --comments comments.md --rounds 5
```

`comments.md` is free text — whatever your reviewers said about the scores.

### Other subcommands

```bash
# strip a mature prompt back to a bare rubric, to start honest rather than pre-guided
.venv/bin/python -m rubric_agent.cli strip --prompt my_prompt.md --out prompt_v0.md

# redraw the trend charts from an existing run
.venv/bin/python -m rubric_agent.cli trend --run runs/my-run

# split every round's move in overall std across the metrics that caused it
.venv/bin/python -m rubric_agent.cli contrib --run runs/my-run

# compare a finished run against human ground truth (operator-only, never seen by any agent)
.venv/bin/python -m rubric_agent.cli gt --run runs/my-run --gt ground-truth.xlsx
```

`gt` takes `--score-pattern` (default `{metric}_score`) and `--label-pattern` (default `{metric}`) to
match your ground-truth sheet's column names.

---

## 4. Tuning without touching the code

Environment variables, all optional:

| Variable | Default | What it sets |
|---|---|---|
| `RUBRIC_GENERATOR` | `claude-opus-5` | Writes and assesses the rubric. |
| `RUBRIC_PARSER` | `claude-opus-5` | Reads the sheet, proposes the schema, writes `setup.md`. |
| `RUBRIC_DESCRIBE` | `claude-sonnet-5` | Describes attachments. |
| `RUBRIC_SCORER` | `google_genai:gemini-3.1-flash-lite-preview` | The model under test. |
| `RUBRIC_SCORER_PARAMS` | `{}` | JSON kwargs for the scorer. |
| `RUBRIC_K` | `4` | Scores per submission per round. |
| `RUBRIC_K_ASSURE` | same as `RUBRIC_K` | Scores per submission on the assurance round. |
| `RUBRIC_WORKERS` | `16` | Parallel scorer threads. Lower it if you hit rate limits. |
| `RUBRIC_ATTACH_CACHE` | `cache/attachments` | Shared attachment cache. Point several runs at one directory. |

`--scorer`, `--scorer-params` and `--k` on the command line just set the matching variable.

**The scorer's sampling temperature is not pinned.** With `RUBRIC_SCORER_PARAMS` empty, the Gemini client
sends its own default of `temperature=0.7` and no thinking configuration. Since the whole run measures
consistency, that temperature is part of what you are measuring — the resulting numbers describe *rubric
+ model + temperature together*, not the rubric alone. Pass `--scorer-params '{"temperature":0}'` if you
want the rubric isolated.

---

## 5. What comes out

Everything lands in the `--run` directory:

| Path | Contents |
|---|---|
| `ledger.md` | **Read this first.** One line per round with every metric's numbers and the gate's verdict, plus the generator's full reasoning for each decision. |
| `rubric/v0.md`, `v1.md`, … | Every rubric version written. |
| `HANDOFF.md` | Final summary: best rubric, why the loop stopped, trend table, embedded charts. |
| `HOW_TO_WRITE_AN_UNAMBIGUOUS_RUBRIC.md` | Generalised lessons from the run. |
| `versions.json` | Per version: parent, kept/rejected, and the deltas that decided it. |
| `trend.json` | Per round: overall and per-metric numbers. Machine-readable. |
| `contributions.md` | Per round: which metric moved the overall std, and by how much. See below. |
| `setup.md` / `setup.json` | What the parser concluded, and the frozen schema and metrics. |
| `submissions.json` | The parsed rows, with attachment descriptions inlined. |
| `scores/`, `stats/` | Raw k scores and computed statistics per round. |
| `trend_*.png`, `rows.png` | Trend charts, a per-submission consistency heatmap, and `trend_contrib.png` (per-metric contribution to each round's move in overall std). |
| `checkpoints.sqlite` | Graph state, used by `resume`. |

The four numbers that matter, all per metric and overall:

- **stable %** — submissions whose k scores all fall within 1 point
- **within-std** — average spread across the k repeats
- **severe flips** — submissions whose k scores span 2 points or more
- **ICC** — guards against the degenerate win where every submission gets the same score; a rubric that
  collapses the scale looks perfectly "consistent" but has stopped discriminating

### Which metric moved the number

Overall within-std is the **unweighted mean** of the per-metric within-std. So

    Δ_overall = (1/M) · Σ_m Δ_metric

holds *exactly* — no interaction term, no residual, and every metric carries weight `1/M` no matter how
noisy it is. `contributions.md` (written every round, and rebuildable with `cli contrib`) is that identity
term by term: each metric's `Δ`, its contribution in the units the gate reads, and its share of the move.
It is also fed to the generator, so a revision can be aimed at the metric that actually cost something.

Four ways the shares mislead, all of them flagged in the table:

- **A share is not evidence.** The yardstick for a per-metric Δ is a re-score of the *same* rubric, which
  is what the assurance round is. The noise floor is read off those rounds. Before one exists the fallback
  is an analytic SE, `sqrt((var − within²)/n)`, which understates the real floor by roughly an order of
  magnitude — the rows are held fixed between rounds, so scorer stochasticity dominates, not row sampling.
- **Shares are signed and need not land in [0, 100].** When metrics move in opposite directions the
  denominator is a near-cancellation, so one metric can read 227% while another reads −55%. The `churn`
  column (`|Δ|` over `Σ|Δ|`) stays bounded and shows the offsetting movement the signed share hides.
- **Mean-of-std is not variance-additive.** `var` is. The `by variance` column is the same split computed
  on the additive aggregate; when the two orderings disagree the table says so, and the std ranking is the
  weaker claim. On both recorded runs they disagree in most rounds.
- **A falling std can just be a shrinking scale.** Push scores down the 1–10 range and per-row std falls
  mechanically. `within/between = sqrt((1−ICC)/ICC)` is invariant to rescaling, so a metric whose raw std
  fell while that ratio did not has not become more consistent. The gate never looks at the score mean.

---

## 6. How the loop decides things

```
parse → design → baseline → [ generate → score → measure → gate → assess ]* → reflect → handoff
```

**The gate is code, not a model.** A revision is kept only when within-std drops by more than its
bootstrap standard error, or stable % rises by more than its SE, *and* nothing else got materially worse,
*and* ICC did not collapse, *and* it did not **trade one metric against another**. Marginal wins are
rejected on purpose.

The trade guard exists because the aggregate is a *mean*: one large improvement can pay for several
regressions and still read as progress. `bootstrap_se` now returns a per-metric SE alongside the
aggregates (`"<metric>.within"`, `.stable_pct`, `.icc`, `.severe` — same resamples, so they are mutually
consistent), and each metric's tolerance is `max(2 × bootstrap SE, re-score noise floor)`. A regression
past that tolerance does **not** by itself block — the best revision on both recorded runs regressed one
metric while fixing three. What blocks is a regression whose win does not survive **leave-one-out**:
delete the single metric contributing most of the gain, and if the remaining mean Δ is no longer negative,
the win lived entirely in one metric and the revision is rejected with `TRADED` in the ledger.

Backtested on the two recorded runs it changes **1 of 11** decisions: it newly rejects `test-maverick`'s
`v1` (whose overall −0.018 is inside that run's own ±0.022 noise floor), keeps every genuine win, and
catches `test-agent-1`'s `v2` — Sustainability −0.177 against three metrics regressing — on its own
merits rather than relying on stable % happening to move the right way.

**The generator decides when to stop.** When it judges the numbers have plateaued it asks for an
*assurance* round: the best rubric is re-scored unchanged. If all four aggregates reproduce within 2 SE,
the run ends successfully — the plateau is confirmed rather than assumed. If they don't reproduce, every
single-round delta so far was noise and the loop continues.

Code stops the run only on circuit breakers: the `--rounds` ceiling, four consecutive rejections, or more
than 30% of scorer calls failing.

---

## 7. Things that will bite you

**Ground truth is operator-only.** `ground-truth.xlsx` and the `gt` subcommand exist to check the result
afterwards. Ground truth never enters any agent's context, and tuning against it defeats the point.

**`memory/principles.md` carries across runs.** After each run the generator appends up to three durable
principles there, and future runs read them. That is usually what you want; delete the file for a
genuinely clean-slate run.

**The attachment cache is shared and large.** Descriptions are written once per file and reused across
runs, which saves a lot of time and money. Deleting `cache/attachments` means re-downloading and
re-describing everything.

**Attachments that can't be fetched are ignored, never guessed**, and videos are never evaluated.

**Unpinned scorer temperature** — see the warning in section 4.

**Rubric length is not free.** Across runs, the repeated finding is that stacking categorical overrides or
first-match ladders onto a rubric makes scores *less* consistent, including on the metric the edit
targeted: each override is a competing route to a band, so raters split on which rule fires instead of on
the submission. Scope every rule to the metric it was written for.
