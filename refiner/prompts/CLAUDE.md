# prompts/ — every prompt the refiner sends

Every piece of text the refiner sends to a model. Code holds no prompt text: it loads it from here: the system prompts
as `.md` files (`prompts.system()`), everything else as Python constants (`prompts.render()` for user messages).
Change a prompt here and nowhere else.

```
prompts/
├── system/                    system prompt of each agent
│   ├── parser.md              reads the sheet and the rubric: columns, metrics, layers, questions
│   ├── judge.md               two tasks: ITEM (one submission) and SUMMARY (the round)
│   └── generator.md           writes the next version: EDIT (patches) or REWRITE
├── user.py                    USER: the message each call sends, plus every other model-facing string (markers,
│                              overviews, checklist and note formats, the generator's problem messages); {placeholders}
│                              are filled in agents/ and engine/
├── judge_tools.py             JUDGE_TOOLS: descriptions of the judge's 5 measuring tools (bound in agents/judge.py `tools`)
└── mcp.py                     INSTRUCTIONS and TOOLS: what the Chat Agent reads about this server (mcp/server.py)
```

## Who sends what

| Agent / call | System prompt | User message | Fields | Sent from |
|---|---|---|---|---|
| Parser (`parse-sheet`) | `system/parser.md` | `USER["parser"]` | `context`, `rubric` (line-numbered), `schema`, `columns` | `agents/parser.py` |
| Scorer (`score-item`) | **the rubric being refined** | `USER["scorer"]` | `submission` | `agents/scorer.py` |
| Judge, per item (`review-item`) | `system/judge.md` | `USER["judge_item"]` | `rubric`, `submission`, `output`, `reference`, `rationale` (the reviewers' comments, or `USER["judge_no_rationale"]`), `error` | `agents/judge.py` (`review`) |
| Judge, round (`summarise-round`) | `system/judge.md` | `USER["judge_summary"]` | `version`, `rubric`, `versions`, `checklist`, `change`, `notes`, `dialogue` | `agents/judge.py` (`summarise`, + tools below) |
| Generator (`write-candidate`) | `system/generator.md` | `USER["generator"]` | `mode`, `rubric` (annotated), `overview`, `summary`, `checklist`, `table`, `dialogue` | `agents/generator.py` |
| Generator mode | | `USER["generator_mode_edit"]`, `USER["generator_mode_rewrite"]` (`brief`) or `USER["generator_mode_simplify"]`; `USER["generator_length"]` (`words`, `v0_words`) | | `agents/generator.py` |
| Generator retry | `system/generator.md` | `USER["generator_retry"]` | `message` (the first message), `problems` (from `USER["problem_*"]`) | `agents/generator.py` |
| Judge tools | | | | `agents/judge.py` `tools` (`judge_tools.JUDGE_TOOLS`), used by `engine/loop.py` and `engine/fanout.py` |
| Rubric markers | | `USER["marker_editable"]`, `USER["marker_locked"]` | `layer`, `k`, `text` | `agents/layers.py` (`annotated`) |
| Checklist and notes text | | `USER["checklist_empty"]`, `USER["checklist_entry"]`, `USER["judge_note"]`, `USER["judge_verdict_reference"]`, `USER["judge_review_unavailable"]`, `USER["synthetic_review"]` | | `agents/judge.py` |
| The round's overview and last change | | `USER["simplify_overview"]`, `USER["polish_overview"]` (`target`), `USER["last_change"]` (+ `last_change_item`, `last_change_baseline`, `last_change_shared`) | | `engine/loop.py`, `engine/fanout.py` |
| Chat Agent's view of the server | | | | `mcp/server.py` (`mcp.INSTRUCTIONS`, `mcp.TOOLS`) |

## Rules

- Generic only: no programme, metric or column names, and no domain examples.
- Each output schema lives next to its call in `agents/<agent>.py`; when a schema changes, change its system prompt here.
- System prompts are sent exactly as their file holds them.
- Placeholders use `{name}`; a literal brace in a template would need doubling (`{{`), so keep them out.
