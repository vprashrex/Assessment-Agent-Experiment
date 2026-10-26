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
├── user.py                    USER: the message each call sends; {placeholders} are filled in agents/
├── judge_tools.py             JUDGE_TOOLS: descriptions of the judge's 5 measuring tools (used in engine/loop.py)
└── mcp.py                     INSTRUCTIONS and TOOLS: what the Chat Agent reads about this server (mcp/server.py)
```

## Who sends what

| Agent / call | System prompt | User message | Fields | Sent from |
|---|---|---|---|---|
| Parser (`parse-sheet`) | `system/parser.md` | `USER["parser"]` | `context`, `rubric` (line-numbered), `schema`, `columns` | `agents/parser.py` |
| Scorer (`score-item`) | **the rubric being refined** | `USER["scorer"]` | `submission` | `agents/scorer.py` |
| Judge, per item (`review-item`) | `system/judge.md` | `USER["judge_item"]` | `rubric`, `submission`, `output`, `reference`, `error` | `agents/judge.py` (`review`) |
| Judge, round (`summarise-round`) | `system/judge.md` | `USER["judge_summary"]` | `version`, `rubric`, `versions`, `checklist`, `change`, `notes`, `dialogue` | `agents/judge.py` (`summarise`, + tools below) |
| Generator (`write-candidate`) | `system/generator.md` | `USER["generator"]` | `mode`, `rubric` (annotated), `overview`, `summary`, `checklist`, `table`, `dialogue` | `agents/generator.py` |
| Generator mode | | `USER["generator_mode_edit"]` or `USER["generator_mode_rewrite"]` (`brief`) | | `agents/generator.py` |
| Generator retry | `system/generator.md` | `USER["generator_retry"]` | `message` (the first message), `problems` | `agents/generator.py` |
| Judge tools | | | | `engine/loop.py` (`judge_tools.JUDGE_TOOLS`) |
| Chat Agent's view of the server | | | | `mcp/server.py` (`mcp.INSTRUCTIONS`, `mcp.TOOLS`) |

## Rules

- Generic only: no programme, metric or column names, and no domain examples.
- Each output schema lives next to its call in `agents/<agent>.py`; when a schema changes, change its system prompt here.
- System prompts are sent exactly as their file holds them.
- Placeholders use `{name}`; a literal brace in a template would need doubling (`{{`), so keep them out.
