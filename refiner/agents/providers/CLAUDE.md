# agents/providers/ — one interface, three clients

Each provider module has the same function and returns the model's JSON answer as text:

```python
complete(model, system, user, schema, effort, tools, log, files) -> str
```

`llm.call` picks one with `providers.get(model)` (from `models.yaml`) and does the shared work around it: retries,
JSON parsing, the required-keys check.

| File | What it does |
|---|---|
| `__init__.py` | `PROVIDERS` (anthropic, openai, google) and `get(model)` |
| `base.py` | what all share: `LLMError`, `Tools`, `Files`, `clean_schema` (drops schema keywords providers reject, keeps property names), `run_tool`, `b64`, and `client(kind)`, one lazily made SDK client per provider; loads `.env` |
| `anthropic.py` | Claude: streamed, adaptive thinking at the run's effort, JSON-schema output, client tools, PDFs and images as blocks |
| `openai.py` | GPT: Responses API, reasoning effort, JSON-schema output, function calls, PDFs and images as inputs |
| `gemini.py` | Gemini: `response_json_schema`, thinking level, files as inline parts; no tools, so it is offered as the scorer only |

Adding a provider: a new module with `complete`, an entry in `PROVIDERS`, its models in `models.yaml`. Call SDK
clients through `base.client(...)` so tests can swap them.
