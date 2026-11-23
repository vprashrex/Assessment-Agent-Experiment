"""Plain HTTP routes beside /mcp, for the Kaapi control plane and the database heartbeat (127.0.0.1 only): uploads,
chat deletion, run events (SSE), liveness, run files, the model catalog. server.py registers them on the server."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import time
from datetime import datetime, timezone
from pathlib import Path

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse

from refiner import api, paths
from refiner.agents import models
from refiner.engine import events
from refiner.mcp import inspect

ROUTES: list[tuple[str, list[str], object]] = []


def route(path: str, methods: list[str]):
    """Collect a route; register() puts every collected route on the server."""
    def collect(fn):
        ROUTES.append((path, methods, fn))
        return fn
    return collect


def register(mcp: FastMCP) -> None:
    for path, methods, fn in ROUTES:
        mcp.custom_route(path, methods=methods)(fn)



def _run_dir(request: Request):
    try:
        return paths.run_dir(request.path_params["chat_id"])
    except ValueError as e:
        raise _Bad(str(e))


class _Bad(Exception):
    pass


def _guard(fn):
    async def wrapped(request: Request) -> Response:
        try:
            return await fn(request)
        except _Bad as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except (FileNotFoundError, ValueError) as e:
            return JSONResponse({"error": str(e)}, status_code=404)
    wrapped.__name__ = fn.__name__
    return wrapped


HEARTBEAT_S = 10
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


@route("/events/{chat_id}", methods=["GET"])
@_guard
async def stream_events(request: Request) -> Response:
    """Every run event after Last-Event-ID (or ?after=), then new ones the moment they are written, plus a
    `heartbeat` event (no id) every HEARTBEAT_S seconds saying whether the run's process is up. Ends after
    run.done / run.failed once nothing newer follows."""
    d = _run_dir(request)
    try:
        after = int(request.headers.get("last-event-id") or request.query_params.get("after") or 0)
    except ValueError:
        raise _Bad("Last-Event-ID / after must be an integer")

    async def gen():
        pos, last_ping = after, time.monotonic()
        yield "retry: 3000\n\n"
        while not await request.is_disconnected():
            new = await asyncio.to_thread(events.read, d, pos)
            for e in new:
                pos = e["seq"]
                yield f"id: {e['seq']}\nevent: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
            if new and new[-1]["type"] in events.TERMINAL:
                return
            if time.monotonic() - last_ping >= HEARTBEAT_S:
                last_ping = time.monotonic()
                # proof of life for the UI: is the run's process up (no id, so resuming is unaffected)
                h = await asyncio.to_thread(api.health, str(d))
                beat = {"alive": h["alive"], "state": h["state"], "ts": datetime.now(timezone.utc).isoformat()}
                yield f"event: heartbeat\ndata: {json.dumps(beat)}\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


MAX_UPLOAD = 50 * 1024 * 1024


def _chat_id(request: Request) -> str:
    try:
        return paths.chat_dir(request.path_params["chat_id"]).name
    except ValueError as e:
        raise _Bad(str(e))


@route("/chats/{chat_id}/inputs", methods=["POST"])
@_guard
async def upload_inputs(request: Request) -> Response:
    """Uploaded files (multipart): `files` go into the chat's inputs/, `docs` into inputs/docs/. Returns each file's
    name (relative to inputs/), size and opening text."""
    chat_id = _chat_id(request)
    form = await request.form()
    saved = []
    for field, folder in (("files", None), ("docs", "docs")):
        for f in form.getlist(field):
            if not hasattr(f, "read"):
                continue
            data = await f.read()
            if len(data) > MAX_UPLOAD:
                raise _Bad(f"{f.filename} is larger than 50 MB")
            name = paths.save_input(chat_id, f.filename or "file", data, folder)
            saved.append({"name": name, "size": len(data), "opening": inspect.opening(paths.inputs_dir(chat_id) / name)})
    return JSONResponse({"files": saved})


@route("/chats/{chat_id}/inputs/{name:path}", methods=["GET"])
@_guard
async def read_input(request: Request) -> Response:
    """One uploaded file as it was uploaded, for previewing it in the chat."""
    p = paths.input_file(_chat_id(request), request.path_params["name"])
    if not p or Path(p).is_dir():
        raise FileNotFoundError("not a file")
    return FileResponse(p, media_type=mimetypes.guess_type(p)[0] or "application/octet-stream")


@route("/chats/{chat_id}", methods=["DELETE"])
@_guard
async def delete_chat(request: Request) -> Response:
    """Stop the chat's run if it is going, then delete its inputs and run."""
    chat_id = _chat_id(request)
    if api.status(str(paths.run_dir(chat_id))).get("running"):
        api.stop(str(paths.run_dir(chat_id)))
    paths.remove_chat(chat_id)
    return JSONResponse({"deleted": True})


@route("/models", methods=["GET"])
async def model_catalog(request: Request) -> Response:
    """models.yaml as JSON: the defaults and every active model, for the UI's model pickers."""
    return JSONResponse({"defaults": models.catalog().get("defaults") or {}, "models": models.active()})


@route("/health/{chat_id}", methods=["GET"])
@_guard
async def health(request: Request) -> Response:
    return JSONResponse(api.health(str(_run_dir(request))))


@route("/runs/{chat_id}/report", methods=["GET"])
@_guard
async def run_report(request: Request) -> Response:
    rep = api.report(str(_run_dir(request)))
    return JSONResponse(rep) if rep else JSONResponse({"error": "report not ready"}, status_code=404)


@route("/runs/{chat_id}/versions", methods=["GET"])
@_guard
async def run_versions(request: Request) -> Response:
    return JSONResponse(api.version_report(str(_run_dir(request)), request.query_params.get("metric") or None))


@route("/runs/{chat_id}/rubric", methods=["GET"])
@_guard
async def run_rubric(request: Request) -> Response:
    q = request.query_params
    if not q.get("version"):
        raise _Bad("version is required")
    return JSONResponse(api.rubric(str(_run_dir(request)), q.get("metric") or None, q["version"]))


@route("/runs/{chat_id}/final_rubric.md", methods=["GET"])
@_guard
async def final_rubric(request: Request) -> Response:
    p = _run_dir(request) / "final_prompt.md"
    if not p.exists():
        return JSONResponse({"error": "final rubric not ready"}, status_code=404)
    return PlainTextResponse(p.read_text(), media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="final_rubric.md"'})


@route("/runs/{chat_id}/results.xlsx", methods=["GET"])
@_guard
async def results_xlsx(request: Request) -> Response:
    p = await asyncio.to_thread(api.results_file, str(_run_dir(request)))
    if not p:
        return JSONResponse({"error": "results not ready"}, status_code=404)
    return Response(p.read_bytes(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="results.xlsx"'})


@route("/runs/{chat_id}/inputs", methods=["GET"])
@_guard
async def inputs(request: Request) -> Response:
    _run_dir(request)
    return JSONResponse(inspect.inputs(request.path_params["chat_id"]))
