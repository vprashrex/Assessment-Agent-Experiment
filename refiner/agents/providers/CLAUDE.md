# agents/providers/ — one interface, three clients, plus the decision APIs

Each provider module has the same function and returns the model's JSON answer as text:

```python
complete(model, system, user, schema, effort, tools, log, files) -> str
```

`llm.call` picks one with `providers.get(model)` (from `models.yaml`) and does the shared work around it: retries,
JSON parsing, the required-keys check. The scorer is the exception: it runs on a decision API (`decisions.py`),
which answers questions with probabilities instead of writing JSON, so `scorer.score_all` calls it directly.

| File | What it does |
|---|---|
| `__init__.py` | `PROVIDERS` (anthropic, openai, google) and `get(model)` |
| `base.py` | what all share: `LLMError`, `Tools`, `Files`, `clean_schema` (drops schema keywords providers reject, keeps property names), `run_tool`, `b64`, and `client(kind)`, one lazily made SDK client per provider. API keys come from the environment; `refiner/paths.py` loads `.env` once |
| `anthropic.py` | Claude: streamed, adaptive thinking at the run's effort, JSON-schema output, client tools, PDFs and images as blocks |
| `openai.py` | GPT: Responses API, reasoning effort, JSON-schema output, function calls, PDFs and images as inputs |
| `gemini.py` | Gemini: `response_json_schema`, thinking level, files as inline parts; no tools |
| `decisions.py` | the scorer's APIs: OpenAI `/v1/decisions` (gpt-6-luna, SDK) and Gemini decisions (gemini-decision-1, REST). `ask(model, rubric, user, files, outs)`: one call per item, one `score` question per number metric (levels = its integer scale) or `choice` per enum; the answer is shaped like a generative scorer's JSON: the most likely level as the value, plus `<field> expected`, `confidence`, `probabilities`. `is_decision(model)`, `levels` (OpenAI: at most 10, lowest merged), `check` (preparation warnings: merged levels, PDFs sent as page images to OpenAI) |

Adding a provider: a new module with `complete`, an entry in `PROVIDERS`, its models in `models.yaml`. Call SDK
clients through `base.client(...)`. The scorer may only use a model whose `completion_type` includes `decision`
(`config.RunConfig` refuses any other); every other model has no `scorer` role in the catalog.
