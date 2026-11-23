# Rubric agent: transport

How events travel from the refiner and the backend to the browser. Everything live is **Server-Sent Events (SSE)**:
one-way, plain HTTP, resumable by id. Requests the other way are plain REST and MCP calls. Architecture overview:
[architecture.md](architecture.md); tables and the heartbeat: [database.md](database.md).

## The streams at a glance

```
 refiner :8765                       Next.js :3000                                   Browser
 ─────────────                       ─────────────                                   ───────
 GET /events/<chat>  ══SSE══▶  run relay (one per running chat) ─┐
   id per event,                                                  │
   heartbeat every 10 s                                           ├─▶ bus ══SSE══▶  GET /api/agent/events
                                                                  │   (in-process)   one stream per tab,
 backend :8000                                                    │                  every chat the user sees
 ─────────────                                                    │
 GET /status-stream  ══SSE══▶  status stream (one per user) ─────┤
   LISTEN rubric_agent_status                                     │
                                                                  │
                                Chat Agent turns (text, reasoning, steps) ─┘

 Every event worth keeping is also saved to the transcript (backend, batched) before or while it is shown.
```

| # | Stream | From → to | Carries | Resumes with |
|---|---|---|---|---|
| 1 | `GET /events/<chat>` | refiner → Next.js | run events + heartbeats | `Last-Event-ID` = last run seq relayed |
| 2 | `GET /api/v1/rubric-agent/status-stream` | backend → Next.js | chat status changes for one project | nothing to resume: status is also on the row |
| 3 | `GET /api/agent/events` | Next.js → browser | every chat event of every chat the user can see | `GET /transcript?after=<last seq>` |

## The event envelope

Every event a browser sees is a `ChatEvent`:

```json
{"chatId": "86a0…", "seq": 146, "ts": "2026-10-26T10:31:47Z",
 "type": "version.verdict", "metric": "novelty", "runSeq": 72, "data": {"version": "v2", "verdict": "rejected", …}}
```

- `seq > 0`: saved in the transcript (messages, reasoning, steps, run events, status, plain notes, briefs).
- `seq = 0`: live only, never saved (`message.delta`, `reasoning.delta`, `agent.working`, `run.heartbeat`,
  `chat.title`).
- `runSeq`: the refiner's own seq, on relayed run events only.

## 1. Refiner → Next.js: run events

The run process appends one line per event to `run/events.jsonl` the moment something happens (`run.started`,
`setup.ready`, `judge.done`, `candidate.written`, `version.verdict`, `metric.stopped`, `composed`, `report.ready`,
`run.done`, `run.failed`, …). The refiner's `/events/<chat>` streams that file:

```
retry: 3000

id: 71
event: candidate.written
data: {"seq":71,"ts":"…","type":"candidate.written","metric":"novelty","data":{…}}

event: heartbeat
data: {"alive":true,"state":"running","ts":"…"}
```

- Starts after `Last-Event-ID` (or `?after=`), then follows the file (read every 0.25 s).
- Each run event has `id:` = its seq, so a reconnect resumes exactly where it stopped.
- **Heartbeat** every 10 s, with no `id:` so it never moves the resume point: whether the run's process is up, from
  the same check the database heartbeat uses (`/health`).
- Ends once `run.done` or `run.failed` has been sent and nothing newer follows.

**The relay** (`server/registry.ts`, one per running chat, held by the Next.js server, not by a page):

1. connects with `Last-Event-ID` = the highest `runSeq` already in the transcript;
2. for each run event: append it to the transcript, publish it to the browsers, then react: `run.started` → status
   `active`; `judge.done` / `candidate.written` → a plain-language note; `version.verdict` → a short brief; `run.done` /
   `run.failed` → status `done` / `failed` and a `[Run update]` turn for the Chat Agent;
3. for each heartbeat: publish `run.heartbeat` to the browsers only (it drives the "✻ Refining… · alive" line);
4. if the stream drops without a final event, ask `/health/<chat>`: reconnect while the run is running (backoff up to
   10 s, at most 30 failures in a row), stop once it has ended and every event is relayed.

Relays keep running when the user switches chats or closes the tab. After a Next.js restart, the first page load
reattaches every `active` chat (`resumeRunning`).

## 2. Backend → Next.js: chat status

```
 any UPDATE of status ──▶ trigger ──▶ pg_notify('rubric_agent_status', {chat_id, status, failure_reason, project_id})
                                         │
 backend /status-stream ── LISTEN ◀──────┘   one Postgres connection per stream
   filters by the caller's project
   event: status
   data: {"chat_id":"…","status":"failed","failure_reason":"no pong for 60 s"}
   ": ping" comment every 15 s
```

- The backend holds one `LISTEN` connection per open stream (psycopg async, autocommit) and releases its pooled
  session at once, so a long stream does not hold a pool slot.
- Next.js opens **one status stream per signed-in user** (by credentials) while that user has a browser stream open.
  Each change becomes a `stream.status` event in the chat's transcript (skipped when it repeats the last one) and goes
  to the browsers.
- This is how a heartbeat verdict from Postgres ("process not running", "no pong for 60 s") reaches the page with no
  polling anywhere.

## 3. Next.js → browser: the page's one stream

`GET /api/agent/events` (`app/api/agent/events/route.ts`):

```
retry: 3000

event: ready
data: {"chats":12}

event: message.delta
data: {"chatId":"…","seq":0,"type":"message.delta","data":{"messageId":"…","text":"Main "}}

: ping
```

- **One stream per tab** for every chat the user can see (their chats at connect time, plus chats they create or
  open later, `shareChat`). Events for other users' chats never enter it.
- Fed by the **bus** (`server/bus.ts`): in-process pub/sub on `globalThis`. Agent turns, relays and status streams all
  `publish`; each stream subscriber forwards the events of its chats.
- `: ping` every 15 s keeps proxies from closing an idle stream; headers `Cache-Control: no-cache, no-transform`,
  `X-Accel-Buffering: no` stop buffering.
- Opening the stream also starts the user's status stream and reattaches running relays.

**The client** (`client/useAgentStream.ts`):

- Reads the stream with `fetch` and a stream reader rather than `EventSource`, so it can send the API key header.
- Reconnects with backoff (1 s, 2 s, 4 s … up to 15 s). After every connect it **catches up**: reloads the chat list
  and fetches the open chat's transcript after its last loaded seq. An event missed while disconnected is never lost,
  because every saved event is in the transcript.
- Applies events through the store's **display queue** (`client/store.ts`), so the page reads like a conversation:
  the agent's answer first, run steps about 1.5 s later (`HOLD_MS`), 300 ms apart (`GAP_MS`), streamed text redrawn
  every 100 ms (`TEXT_MS`).

## Saving while streaming

Showing and saving are separate, so the page is never slower than the run:

| Event kind | Shown | Saved |
|---|---|---|
| Chat Agent message (user, assistant, tool results) | as it streams | to the Chat Agent's memory **before the next step** (awaited) |
| Transcript event (reply done, step, run event, status) | at once (bus) | to the transcript in **batches**: every 250 ms or 50 events, in the background |
| Live-only event (deltas, heartbeat, working, title) | at once | never |

The transcript batch is accepted only if it continues the file (409 otherwise; the client keeps only what the backend
lacks), and the session cache in Next.js means reads never go back to the backend while a chat is open.

## Requests the other way

| From → to | Transport | Used for |
|---|---|---|
| Browser → Next.js | REST `/api/agent/*` (multipart for messages with files) | messages, chat CRUD, models, run files |
| Next.js → refiner | **MCP** over streamable HTTP (`/mcp`), one short connection per call | the Chat Agent's actions |
| Next.js → refiner | HTTP `POST /chats/<id>/inputs`, `DELETE /chats/<id>`, `GET /runs/<id>/…`, `GET /models` | uploads, delete, reports and downloads, model catalog |
| Next.js → backend | REST `/api/v1/rubric-agent/*` | chat rows, transcript, Chat Agent memory |
| Postgres → refiner | `http_get` from the heartbeat job | `GET /health/<id>` every 15 s |
| Next.js → Anthropic | HTTPS, streamed | Chat Agent turns, compaction, titles and notes |

## Timings

| What | Interval |
|---|---|
| Refiner reads `events.jsonl` for new lines | 0.25 s |
| Refiner heartbeat on `/events` | 10 s |
| Database heartbeat (pg_cron) | 15 s; failed after 60 s without a pong |
| Backend `: ping` on `/status-stream` | 15 s |
| Next.js `: ping` on `/api/agent/events` | 15 s |
| Transcript save batch | 250 ms or 50 events |
| Browser reconnect | 1 s → 15 s backoff |
| SSE `retry:` hint | 3 s |
