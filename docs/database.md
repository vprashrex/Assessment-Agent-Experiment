# Rubric agent: database and chat memory

What the rubric agent keeps in Kaapi's database, what it keeps in files, and how Postgres itself checks that a
running chat is still alive. Architecture overview: [architecture.md](architecture.md).

## The table: `rubric_agent_chat`

One row per chat. Created by migration 087, memory paths added by migration 088.

| Column | Type | Meaning |
|---|---|---|
| `id` | uuid PK | the chat id; also the folder name on both sides and the `/health/<id>` the heartbeat calls |
| `project_id` | int FK → project (cascade) | owner project; every query is scoped by it |
| `organization_id` | int FK → organization (cascade) | owner organization |
| `title` | varchar(200) | shown in Recents; written by the Chat Agent's title call or the user |
| `status` | varchar(16), check `idle/active/done/failed` | lifecycle, see below |
| `last_heartbeat_at` | timestamptz | last time the refiner answered the heartbeat for this chat |
| `failure_reason` | text | why it failed; null unless `failed` |
| `models` | jsonb | the small model choice per role: `{agent, parser, judge, generator, scorer, effort}` |
| `transcript_path` | varchar(255) | `projects/<p>/chats/<id>/transcript.jsonl` |
| `agent_config_path` | varchar(255) | `projects/<p>/chats/<id>/agent/config.json` |
| `agent_messages_path` | varchar(255) | `projects/<p>/chats/<id>/agent/messages.jsonl` |
| `inserted_at`, `updated_at` | timestamp (UTC) | `updated_at` orders Recents |
| `deleted_at` | timestamp | soft delete |

Index `(project_id, updated_at)` serves the Recents list; `organization_id` has its own index.

The paths are relative to `RUBRIC_AGENT_DATA_DIR`. **The row keeps paths only, never the data itself**: the transcript
and the Chat Agent's messages grow to megabytes and are appended to many times a minute, which JSONB columns handle
badly (each change rewrites the whole value and the row).

## Chat status

```
            prepare_run / start_run accepted, or run.started relayed
   idle ─────────────────────────────────────────────▶ active
                                                        │
       run.done relayed, or the heartbeat sees "done"   ├──────▶ done
       run.failed relayed, or the heartbeat finds the   │
       process gone / unreachable for 60 s              └──────▶ failed (failure_reason)
   done / failed ──▶ active again when a new preparation or refinement starts
```

- Next.js sets `active` (`PATCH`) when an action starts a background process, and `done` / `failed` (`POST /finish`)
  when it relays the run's final event.
- The heartbeat job sets `done` / `failed` on its own when Next.js is not around to do it (below).
- The API applies the 60-second rule at read time too (`to_public_chat`): an `active` chat with no heartbeat for 60 s
  is reported as `failed` ("no pong for 60 s") even before the job writes it, so the UI never shows a dead run as
  running.

## Status changes as events: the NOTIFY trigger

Trigger `rubric_agent_chat_status_notify` runs after every `INSERT`, and after an `UPDATE` of `status` or
`failure_reason` that actually changes `status`. It sends:

```sql
pg_notify('rubric_agent_status',
          '{"chat_id": "...", "status": "failed", "failure_reason": "no pong for 60 s", "project_id": 1}')
```

Whoever changed the row (the API, the heartbeat job, a manual `UPDATE`), every listener hears it. The backend's
`/status-stream` listens on this channel ([transport.md](transport.md#2-backend--nextjs-chat-status)).

## Heartbeat: pg_cron + http

The database checks every running chat itself, so a crashed refiner or a killed run process is noticed even when no
browser and no Next.js server is watching.

```
 every 15 s  pg_cron job "rubric-agent-ping"
     │       SELECT rubric_agent_ping()
     ▼
 for each chat WHERE status = 'active' AND deleted_at IS NULL:
     http_get(<rubric_agent.server_url>/health/<chat id>)      timeout 1 s (CURLOPT_TIMEOUT_MS)
     │
     ├─ 200, state = "done"        → status = done
     ├─ 200, state = "failed"      → status = failed, failure_reason = the run's error
     ├─ 200, alive = true          → last_heartbeat_at = now()          (the "pong")
     ├─ 200, not alive, not ended  → status = failed, "process not running"
     └─ no answer / error          → if last_heartbeat_at is older than 60 s (or never set):
                                       status = failed, "no pong for 60 s"
     every UPDATE re-checks status = 'active', so it never overwrites a concurrent /finish
     every status change fires the NOTIFY trigger above
```

**What the refiner answers** (`GET /health/<chat id>`, milliseconds, reads only `run/process.json` and the last line of
`run/events.jsonl`):

```json
{"alive": true, "pid": 22846, "state": "running", "last_event_seq": 72,
 "last_event_at": "2026-10-26T10:31:47.375+00:00", "error": null}
```

`state` is `running` (process up), `done` / `failed` / `stopped` (the last event says how it ended), or
`not_started`.

**The pieces:**

| Piece | What it does |
|---|---|
| `pg_cron` | runs `SELECT rubric_agent_ping()` every 15 seconds (job `rubric-agent-ping`, in the app database) |
| `http` (pgsql-http) | `http_get()` makes the call from inside Postgres; `http_set_curlopt('CURLOPT_TIMEOUT_MS', '1000')` caps it at 1 s |
| `rubric_agent_ping()` | plpgsql, created by migration 087; the loop above |
| `rubric_agent.server_url` | database setting with the refiner's address; default `http://127.0.0.1:8765` |

Both extensions are a one-time manual install per Postgres server: `backend/scripts/setup_rubric_agent_pg.md`. The
migration runs without them: it schedules the job only if pg_cron exists, and plpgsql resolves `http_get` only when
the function runs. Until both are there, nothing moves chats to `done` / `failed` in the database, but the read-time
60-second rule still reports dead chats correctly.

**Check it:**

```sql
SELECT jobname, schedule, command FROM cron.job WHERE jobname = 'rubric-agent-ping';
SELECT status, return_message, start_time FROM cron.job_run_details
 WHERE jobid = (SELECT jobid FROM cron.job WHERE jobname = 'rubric-agent-ping')
 ORDER BY start_time DESC LIMIT 5;
SELECT id, status, last_heartbeat_at, failure_reason FROM rubric_agent_chat WHERE status = 'active';
```

### pg_net instead of http?

The ping uses **pgsql-http**, which is synchronous: `http_get()` returns the response inside the same function call,
so one plpgsql loop can call and decide. **pg_net** (Supabase's extension) is asynchronous: `net.http_get()` only
queues the request and returns an id; the response lands later in `net._http_response`, written by a background
worker. Moving to pg_net would split the ping into two steps:

1. every 15 s: queue one `net.http_get` per active chat and remember the request id per chat;
2. a second job (or the next run of the same one): read the answers from `net._http_response` and apply the same
   rules, treating a missing or timed-out answer as "no pong".

pg_net is worth it where pgsql-http is not offered (it ships with Supabase and some managed Postgres services) or when
there are many active chats, since requests no longer run one after another inside the cron job. For one refiner on
localhost, with calls that answer in milliseconds, pgsql-http is simpler and the current choice.

## Chat memory: files on the backend

```
RUBRIC_AGENT_DATA_DIR/                      default backend/data/rubric_agent/ (gitignored)
└── projects/<project_id>/chats/<chat_id>/
    ├── transcript.jsonl                    UI events, one JSON per line, seq 1, 2, 3 …
    └── agent/
        ├── config.json                     the Chat Agent's system prompt + tools, frozen at its first turn
        ├── .config.lock                    lock for writing config.json once
        └── messages.jsonl                  the Chat Agent's messages, one per line, append-only
```

`backend/app/services/rubric_agent/memory.py` is the only code that reads or writes these files.

### Transcript

What the chat page shows: user messages, the agent's replies and reasoning, steps, every run event, status changes,
plain-language notes. A line:

```json
{"seq": 146, "type": "version.verdict", "metric": "novelty", "runSeq": 72, "ts": "2026-10-26T10:31:47Z", "data": {…}}
```

`seq` is the chat's own order; `runSeq` is the refiner's seq for relayed run events (where relaying resumes). An append
must continue the file: the batch's first `seq` is the last one + 1, checked under a file lock, else 409.

### Chat Agent memory

- `config.json`: written once, on the chat's first turn. The same config again is a no-op; a different one is a 409.
  Freezing it keeps every later request's prefix byte-identical, which the model's signed thinking and the prompt
  cache both depend on.
- `messages.jsonl`: every message exactly as the Anthropic API returned or received it, thinking blocks and tool
  results included. **Append-only**: never edited, trimmed or reordered. An append carries `expected_count` (how many
  messages the caller holds) and is refused with 409 if the file has another count, so two writers can never
  interleave.
- **Compaction** (on-demand, beta `compact-2026-09-04`, only for models that report `capabilities.compaction`): when the
  next request would pass 150k tokens, the API writes a summary block. It is **appended** as one more message; requests
  start from the newest summary. Nothing earlier is removed from the file.

### Redis cache

Redis keeps the memory calls off Postgres. It is a cache only: on a miss the row and the files answer.

| Key | Value | TTL |
|---|---|---|
| `rubric_agent:chat:<id>` | hash: `project_id`, the three paths | 24 h, refreshed on use |
| `rubric_agent:chat:<id>:seq` | last transcript seq | 24 h |
| `rubric_agent:chat:<id>:count` | number of Chat Agent messages | 24 h |

A memory call checks the cached `project_id` against the caller's project, so the cache never widens access.
Deleting a chat evicts its keys, so its memory routes return 404 at once.

### Memory API

| Route | Body / query | Answer |
|---|---|---|
| `GET /chats/{id}/events` | `?after=N` | `{events, last_seq}`; empty at once if the caller is up to date |
| `POST /chats/{id}/events` | `{events: [...]}` (≤ 500) | `{last_seq}`; 409 on a gap or repeat |
| `GET /chats/{id}/agent` | | `{config, messages, count}` |
| `PUT /chats/{id}/agent/config` | `{config}` | written once; 409 if a different one exists |
| `POST /chats/{id}/agent/messages` | `{expected_count, messages: [...]}` (≤ 100) | `{count}`; 409 on a stale count |

All under `/api/v1/rubric-agent`, scoped to the caller's project like the chat CRUD.

## The refiner's files (not in the database)

```
refiner-data/chats/<chat_id>/               the refiner's own folder (RUBRIC_REFINER_DATA)
├── inputs/                                 uploaded files; docs/ for documents
└── run/                                    process.json, models.json, events.jsonl, setup/, versions/, metrics/,
                                            report.json, results.xlsx, final_prompt.md
```

Deleting a chat deletes this folder (the refiner stops a running run first); the backend soft-deletes the row and
keeps its memory files.

## Migrations

| Revision | What |
|---|---|
| 087 | `rubric_agent_chat`, the NOTIFY trigger, `rubric_agent_ping()`, the pg_cron schedule (if pg_cron exists) |
| 088 | `agent_config_path`, `agent_messages_path`; every row's paths moved to `projects/<p>/chats/<id>/…` |

`backend/scripts/migrate_rubric_agent_memory.py` copies chats written before 088 from the old shared folder.
