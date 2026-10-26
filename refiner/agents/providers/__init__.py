"""One interface over the model providers. Each module has `complete(model, system, user, schema, effort, tools, log,
files) -> str` and returns the model's JSON answer as text; llm.call does the rest (retries, checks)."""

from __future__ import annotations

from typing import Callable

from .. import models
from . import anthropic, gemini, openai
from .base import Files, LLMError, Tools

PROVIDERS: dict[str, Callable[..., str]] = {"anthropic": anthropic.complete, "openai": openai.complete,
                                            "google": gemini.complete}


def get(model: str) -> Callable[..., str]:
    """The provider serving a model (models.yaml), Anthropic for one it does not list."""
    return PROVIDERS.get(models.provider(model), anthropic.complete)


__all__ = ["Files", "LLMError", "PROVIDERS", "Tools", "get"]
