"""Every piece of text the refiner sends to a model. Code never writes prompt text inline; it loads it from here, so
the prompts can be read, reviewed and evaluated in one place.

    system/          each agent's system prompt (parser, judge, generator); the scorer's system prompt is the rubric
    user.py          the message each model call sends, a template whose {placeholders} agents/ fills
    mcp.py           what the Chat Agent reads about this server: its instructions and one description per action

CLAUDE.md lists every prompt, the call that sends it and the fields it is filled with.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from .user import USER

DIR = Path(__file__).parent


@lru_cache(maxsize=None)
def system(agent: str) -> str:
    """An agent's system prompt, exactly as the file holds it."""
    return (DIR / "system" / f"{agent}.md").read_text(encoding="utf-8")


def render(name: str, **fields: object) -> str:
    """A user message (user.USER[name]) with its {placeholders} filled. Values are inserted as they are (braces in
    them are safe)."""
    return USER[name].format_map(fields)
