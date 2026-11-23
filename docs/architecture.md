# Rubric agent: architecture

The rubric agent refines an organisation's assessment prompt (the rubric) until an AI scorer's scores agree with the
scores its own people already gave. A user talks to it in Kaapi's chat; the refinement itself runs for hours in the
background. This page shows the parts, who owns what, and how a chat flows through them. The companion pages go
deeper: [database.md](database.md) (tables, files, heartbeat) and [transport.md](transport.md) (the SSE streams).

## The parts

```
                     Browser (Kaapi chat page)
                       │  REST: /api/agent/*            ▲ SSE: /api/agent/events (one stream per tab)
                       ▼                                │
 ┌──────────────────── Next.js (kaapi-frontend, :3000) ───────────────────────────┐
 │  Chat Agent: Claude via the Anthropic SDK, an MCP client of the refiner        │
 │  control plane: routes, turn queue, run relay, in-process bus, session caches  │
 │  keeps no files                                                                │
 └───────┬──────────────────────────────┬──────────────────────────────┬──────────┘
         │ MCP (/mcp) + HTTP            │ REST + SSE                   │ HTTPS
         ▼                              ▼                              ▼
 ┌─ rubric-refiner (:8765) ─┐   ┌─ kaapi-backend (:8000) ───────┐   Anthropic API
 │ MCP server (FastMCP)     │   │ chat rows, liveness, memory   │   (Chat Agent model;
 │ runs the refinement in   │   │ API; Redis cache              │    the refiner calls
 │ background processes     │   └──────┬────────────────────────┘    Anthropic, OpenAI
 │ owns refiner-data/       │          │ SQL, LISTEN/NOTIFY           and Gemini itself)
 └──────────▲───────────────┘          ▼
            │ GET /health/<id>   ┌─ Postgres ─────────────────────┐
            └────────────────────┤ rubric_agent_chat               │
              every 15 s         │ pg_cron + http: heartbeat ping  │
                                 └─────────────────────────────────┘
```

| Part | Role | Talks to |
|---|---|---|
| **Browser** | The chat page: messages, the run timeline, the version panel, downloads | Next.js only |
| **Next.js** | Runs the **Chat Agent** (a Claude model that talks with the user and calls the refiner's actions) and the control plane around it | refiner, backend, Anthropic |
| **rubric-refiner** | The **MCP server**: reads the uploads, prepares and runs the refinement, scores, writes reports | its own folder; model providers |
| **kaapi-backend** | The chat's **CRUD and memory API**: chat rows, status, the transcript and the Chat Agent's messages | Postgres, Redis, its own folder |
| **Postgres** | Chat rows; a NOTIFY trigger on status changes; the **heartbeat** job (pg_cron + `http`) | the refiner's `/health` |

## Who owns what

Every piece of state has exactly one owner, and no folder is read or written by two services.

| State | Owner | Where | Others reach it through |
|---|---|---|---|
| Uploads and runs (inputs, versions, checklist, run events, results) | refiner | `refiner-data/chats/<chat>/{inputs/, run/}` | MCP actions, `/events`, `/runs/<chat>/…` |
| Chat row (title, status, models, heartbeat, memory paths) | backend | Postgres `rubric_agent_chat` | `/api/v1/rubric-agent/chats…` |
| Transcript (what the chat page shows) | backend | `data/rubric_agent/projects/<p>/chats/<chat>/transcript.jsonl` | `/chats/<chat>/events` |
| Chat Agent memory (what its model reads back) | backend | `…/chats/<chat>/agent/{config.json, messages.jsonl}` | `/chats/<chat>/agent…` |
| Model catalog | refiner | `models.yaml` | `GET /models` |

There are three memories and they never mix: the **refiner's run** (what was done), the **transcript** (what the
user sees) and the **Chat Agent's messages** (what its model was told and answered). The Chat Agent never copies run
state into its own memory; it asks the refiner with an action when it needs to know.

## The Chat Agent

- **Model:** chosen per chat in the Models dialog (`agent` role in `models.yaml`), default Claude Opus 5.5, adaptive
  thinking with summarized reasoning shown to the user.
- **Tools:** the refiner's MCP actions (`inspect_inputs`, `prepare_run`, `start_run`, `run_status`, `get_report`,
  `add_context_note`, …). The control plane adds the chat id and the chosen models to every call itself, so the model
  never sees or sets them.
- **One turn at a time per chat:** a per-chat queue in Next.js; a user message and a run update never run at once.
- **Memory rules:** the system prompt and tools are frozen at the chat's first turn; messages are append-only and
  saved before each next step; requests are prompt-cached; on-demand compaction summarizes long chats on models
  that support it ([database.md](database.md#chat-agent-memory)).
- **Side writers:** short single calls (chat titles, one-line plain-language notes, version briefs) run beside the
  conversation, have no memory and write only to the transcript.

## A chat, end to end

```
 1. User sends a message with files ──▶ Next.js forwards the files to the refiner (POST /chats/<id>/inputs)
                                        and records "file.uploaded" + "user.message" in the transcript
 2. Chat Agent turn ──▶ inspect_inputs (a preview of each file) ──▶ replies with what it found, asks to confirm
 3. User confirms ──▶ prepare_run: the refiner starts a background process; chat status → active
 4. Run events flow refiner ──SSE──▶ Next.js relay ──▶ transcript (backend) + browsers (bus)
 5. "run.done" (prepare) ──▶ Next.js gives the Chat Agent a [Run update]; it explains and asks to start
 6. start_run: models lock for the run; the refinement runs for hours; every version appears in the timeline
 7. "run.done" (refine) ──▶ status → done; the Chat Agent writes the summary; downloads come from the refiner
```

While a run is going, Postgres checks the refiner every 15 seconds and marks the chat `failed` if its process is gone
([database.md](database.md#heartbeat-pg_cron--http)), and the refiner's own stream sends a heartbeat every 10 seconds
that drives the live "✻ Refining…" line ([transport.md](transport.md)).

## Rules the design keeps

- **No shared folder.** Files reach the refiner only through its HTTP and MCP endpoints; chat memory reaches the
  backend only through its API. Next.js keeps nothing on disk.
- **Paths, not blobs, in the database.** The chat row keeps relative paths to its memory files; large data never goes
  into JSONB columns.
- **Run models lock when the refinement starts** (recorded in `run/models.json` and in the `run.started` event); only
  the Chat Agent's own model can change mid-run.
- **Generic code.** Nothing in the code or prompts names a programme, metric or column; the parser decides those from
  the uploads.
- **Real people's writing stays local.** Uploads, runs and chat memory are gitignored and never copied into docs or
  logs.

## Where the code is

| Concern | Code |
|---|---|
| Chat Agent turn, tools, system prompt | `kaapi-frontend/app/lib/rubricAgent/server/agent.ts` |
| Chat memory clients and compaction | `kaapi-frontend/app/lib/rubricAgent/server/memory/` |
| Run relay, status stream | `kaapi-frontend/app/lib/rubricAgent/server/registry.ts` |
| Browser stream and bus | `kaapi-frontend/app/api/agent/events/route.ts`, `…/server/bus.ts` |
| Refiner MCP server and HTTP routes | `rubric-refiner/refiner/mcp/` (`server.py`, `routes.py`) |
| Refiner folder layout | `rubric-refiner/refiner/paths.py` |
| Chat CRUD and memory API | `kaapi-backend/backend/app/api/routes/rubric_agent.py` |
| Memory files, Redis cache | `kaapi-backend/backend/app/services/rubric_agent/{memory,cache}.py` |
| Status stream (LISTEN) | `kaapi-backend/backend/app/services/rubric_agent/status.py` |
| Trigger and heartbeat function | `kaapi-backend/backend/app/alembic/versions/087_add_rubric_agent_chat.py` |
