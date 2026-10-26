"""Where the refiner keeps a chat's files. The refiner owns this folder and is the only thing that writes to it:
uploads arrive through its HTTP route (POST /chats/{chat_id}/inputs), context notes through its add_context_note
action. The chat's conversation lives elsewhere (the Chat Agent's memory, kept by the Kaapi backend).

<RUBRIC_REFINER_DATA>/chats/<chat_id>/
  inputs/            uploaded files: sheet, context, current rubric, output schema, docs/
  run/               the refiner run folder (see loop.py)

RUBRIC_REFINER_DATA defaults to refiner-data/ in this repository (gitignored).
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")  # a UUID or a short slug; never a path
_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]")


def data_root() -> Path:
    return Path(os.getenv("RUBRIC_REFINER_DATA") or ROOT / "refiner-data").expanduser().resolve()


def chat_dir(chat_id: str) -> Path:
    if not _ID.match(str(chat_id)):
        raise ValueError(f"invalid chat id: {chat_id!r}")
    return data_root() / "chats" / chat_id


def run_dir(chat_id: str) -> Path:
    return chat_dir(chat_id) / "run"


def inputs_dir(chat_id: str) -> Path:
    return chat_dir(chat_id) / "inputs"


def safe_name(name: str) -> str:
    """A file name reduced to its base name and plain characters, so an upload can never leave inputs/."""
    base = _UNSAFE.sub("_", Path(name).name).lstrip(".")[:120]
    if not base:
        raise ValueError(f"invalid file name: {name!r}")
    return base


def save_input(chat_id: str, name: str, data: bytes, folder: str | None = None) -> str:
    """Store one uploaded file in the chat's inputs/ (or inputs/<folder>/); returns its name relative to inputs/."""
    d = inputs_dir(chat_id) / safe_name(folder) if folder else inputs_dir(chat_id)
    d.mkdir(parents=True, exist_ok=True)
    file = safe_name(name)
    (d / file).write_bytes(data)
    return f"{safe_name(folder)}/{file}" if folder else file


def remove_chat(chat_id: str) -> None:
    """Delete everything the refiner holds for a chat: its inputs and its run."""
    shutil.rmtree(chat_dir(chat_id), ignore_errors=True)


def input_file(chat_id: str, name: str | None) -> str | None:
    """An uploaded file (or folder, for docs) by name; refuses anything outside the chat's inputs/."""
    if not name:
        return None
    base = inputs_dir(chat_id).resolve()
    p = (base / name).resolve()
    if base not in p.parents and p != base:
        raise ValueError(f"{name!r} is not inside this chat's inputs")
    if not p.exists():
        have = sorted(x.name for x in base.iterdir()) if base.exists() else []
        raise FileNotFoundError(f"{name!r} was not uploaded to this chat; uploaded: {have}")
    return str(p)
