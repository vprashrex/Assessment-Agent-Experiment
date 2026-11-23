# mcp/ — the server

`uv run refiner-server` serves HTTP on 127.0.0.1:8765 (`/mcp` plus the routes below); `uv run refiner-mcp` serves
the same actions over stdio for Claude Desktop / Claude Code.

| File | What it does |
|---|---|
| `server.py` | the FastMCP instance and the 12 actions the Chat Agent calls (list_inputs, inspect_inputs, add_context_note, prepare_run, start_run, run_status, stop_run, get_checklist, get_version_report, get_rubric, get_report, get_final_prompt); `main` (stdio) and `serve` (HTTP); registers the routes |
| `routes.py` | plain HTTP routes for the Kaapi control plane and the database heartbeat: uploads (`POST /chats/<id>/inputs`, one file back for preview: `GET /chats/<id>/inputs/<name>`), delete, run events (`/events/<id>`, SSE), `/health/<id>`, run files (`/runs/<id>/…`), the model catalog (`/models`) |
| `inspect.py` | a chat's uploads: the file list, a content-based preview of each file, a file's opening lines for naming the chat |

Rules:
- Absolute imports only (`from refiner …`): `fastmcp run refiner/mcp/server.py:mcp` loads `server.py` by path.
- Action descriptions and the server instructions are in `prompts/mcp.py`, not in docstrings.
- Long-running actions start background processes and return at once; Claude Desktop times out on long calls.
- Files reach the refiner only through these routes and actions; no other service writes into `refiner-data/`.
