# Rubric Consistency Agent — plan

## Goal

Given an organisation's free-text context and a spreadsheet of submissions, produce a rubric prompt whose
scores are **consistent**: the same submission scored k times by the same model lands on the same value,
for every metric, across the whole dataset — while scores still separate strong from weak submissions.
No ground truth, no human labels in the loop. Output: the best rubric, the output schema, a per-submission
consistency graph, and a written guide on how the rubric was made unambiguous.

## Agentic pattern

Two agents. One decides, many measure.

| | Generator | Scorer sub-agents |
|---|---|---|
| role | drafts the rubric prompt and the output schema from the parser's context; reads the consistency graph; revises the rubric; decides when it is consistent | take rubric + schema + one submission, return one score object |
| memory | long-term (`memory/principles.md` across runs) + scratchpad (learnings per round, this run) | none — stateless call, k copies in parallel per submission |
| model | Anthropic (opus-5 default) | any provider, chosen by the user (`provider:model` + params) |
| decides | schema, rubric text, whether scores are consistent, revise / assure / stop | nothing |

Code (not an agent) does the arithmetic and the guards: k-run std/variance per submission, ICC, stability
rate, bootstrap noise bands, keep/revert, collapse guard, ceilings, assurance check.

## Loop

```
parse → design → baseline ─┬→ generate → score(k×N) → measure → gate → assess ─┐
                           │        ↑ assure: same rubric scored again              │
                           └────────┴──────── revise ───────────────────────────────┘
                                                              stop → reflect → handoff
```

1. **parse** — clean the sheet, pick columns (agent), describe attachments once, write `setup.md` +
   `submissions.json`. (Existing `parser/` package, unchanged.)
2. **design** (Generator) — from `setup.md` + operator context: propose the **output schema** (which fields
   are scores, scale, reason fields) and draft **v0**. Operator may override either with `--schema` /
   `--prompt`. Schema is frozen after this step so every round is comparable.
3. **baseline** — score v0 on the whole dataset × k; measure; ledger `r00`; record `baseline_icc`.
4. **generate** (Generator) — brief: per-metric stats (mean within-std, stable %, ICC, unused values,
   pile-ups), the least-stable submissions with their k values and Δstd vs last round, the trend table,
   the graph PNG as an image, scratchpad window, ledger, principles, human comments if any. Writes
   `rubric/vN.md` + scratchpad "Round N — Generator" (change, hypothesis, pitfalls noted).
5. **score** (sub-agents) — vN on all submissions × k, k calls in parallel per submission, stateless,
   schema-enforced JSON. Resume-safe (rows already scored this round are skipped).
6. **measure** (code) — per submission × metric: values, mean, std, stable (std ≤ 0.5); per metric: mean
   within-std, stable %, between-std, ICC, unused values, pile-up; per-row Δstd vs previous round;
   `trend.json`, `rows/round_N.json`, `trend.png` (per-metric trends + per-submission std heatmap).
7. **gate** (code) — KEPT iff (mean within-std falls beyond its bootstrap SE **or** stable % rises beyond
   SE) **and** ICC ≥ best − SE **and** ICC ≥ baseline − SE (collapse guard: a rubric that gives everyone the
   same score is perfectly stable and is rejected). Hill-climb from best. Circuit breaker: `--rounds`
   ceiling, scorer failure rate > 30 %.
8. **assess** (Generator) — reads graph + numbers + scratchpad → `revise | assure | stop` with notes and the
   submissions to focus on. `assure` = score the **best** rubric once more on the same rows; code checks the
   per-row std distribution is unchanged within SE and stable % did not drop → `STOP: success (assured)`;
   otherwise back to revise. `stop` is honoured only after a passed assurance.
9. **reflect** (Generator) — `HOW_TO_WRITE_AN_UNAMBIGUOUS_RUBRIC.md` for this run + ≤ 3 principles to
   `memory/principles.md`. **handoff** — `HANDOFF.md`: best rubric, schema, why it stopped, per-metric
   stable %/ICC, graph, and how to feed human comments back (`cli continue --comments f --rounds N`).

## Consistency maths (code, `loop/measure.py`)

- row × metric: values over k runs, mean, std; **stable** if std ≤ 0.5 (all runs within adjacent values).
- metric: mean within-std (consistency), **stable %**, between-std (discrimination),
  **ICC = between² / (between² + within²)**, unused values, pile-up (> 40 % on one value).
- bootstrap SE over rows for mean within-std, stable %, ICC → the noise band a candidate must beat.
- per row Δstd between rounds → which submissions became more / less consistent (Generator's focus list).

## Scorer provider layer (`scorer/provider.py`)

`RUBRIC_SCORER="provider:model"` (e.g. `anthropic:claude-sonnet-5`, `openai:gpt-4o-mini`,
`google_genai:gemini-…`) and `RUBRIC_SCORER_PARAMS` JSON (temperature, max_tokens, …) → LangChain
`init_chat_model(model, **params).with_structured_output(schema, method="json_schema")`; fallback
`method="function_calling"` where a provider lacks json_schema. Output validated against the frozen schema
(`parser.scores_from`); a failed run counts as unstable. Generator calls stay on `core/llm.py` (Anthropic,
streaming, explicit long `Timeout`, summarized thinking so the stream never goes silent, one retry on timeout).

## Files (every file ≤ 200 LOC)

```
rubric_agent/
  core/      config (scorer spec/params, K, N, ceilings) · llm (Generator calls) · state (Design, Assessment) · runio
  parser/    unchanged (sheet, attachments, columns, setup, build, strip)
  scorer/    provider (any-provider structured call) · score (k fan-out per submission)
  generator/ design · generate · assess · reflect
  loop/      measure · steps (score, measure nodes) · gate · lifecycle (parse, design, baseline) · finish (handoff) · plot
  prompts/   parser_* · generator_design · generator · generator_assess · reflect
  graph.py · cli.py (strip | run | continue | resume | trend | gt report)
```

Knobs: `--scorer`, `--scorer-params`, `--k` (default 4), `--n` (subsample; default whole set), `--rounds`
(ceiling, default 30), `--prompt`, `--schema` (optional overrides).

## Cost / time (whole set, 998 rows)

k = 4 → ≈ 4 000 scorer calls per round. sonnet-5 ≈ $80 and 40–60 min at 16 workers; haiku-4.5 or
gpt-4o-mini ≈ $10–20. Generator ≈ $2 per round. Smoke with `--n 60 --k 3` first; run the whole set with the
scorer the organisation would actually deploy.

## Build order + verification

1. `git init` and commit; add `langchain` + provider packages.
2. `scorer/provider.py` — one validated call each on `anthropic:` and one other provider.
3. `measure` additions — synthetic test: a stable discriminating metric passes, a collapsed metric trips
   the collapse guard, stable % is right.
4. `design` — run on `context.md` alone; inspect proposed schema + `rubric/v0.md`; then with `--schema`.
5. Smoke `run --n 40 --k 3 --rounds 3` — r00 line; Generator's r01 change cites unstable rows; gate line
   shows within-std / stable % / ICC deltas with SEs; assess routes; `trend.png` renders both panels; a long
   Generator call survives.
6. Whole-set run; `continue --comments` after human review; `gt report` offline.

## Later

Sub-agent per metric; human-alignment phase; metamorphic tests; LangGraph `Send` fan-out; dashboard.
