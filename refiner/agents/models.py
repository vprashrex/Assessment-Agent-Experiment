"""The model catalog, `models.yaml` at the project root: which provider serves a model, its output limit and how the
run's effort maps onto its reasoning setting. A model missing from the catalog still works, routed by its name."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from ..paths import ROOT

CATALOG = ROOT / "models.yaml"
REASONING_KEYS = ("effort", "thinking_level")


@lru_cache(maxsize=1)
def catalog() -> dict[str, Any]:
    return yaml.safe_load(CATALOG.read_text()) if CATALOG.exists() else {"defaults": {}, "models": []}


def active() -> list[dict]:
    """Models the UI may offer: active and usable by at least one agent."""
    return [m for m in catalog().get("models") or [] if m.get("is_active", True) and m.get("roles")]


def entry(model: str) -> dict:
    return next((m for m in catalog().get("models") or [] if m["model_name"] == model), {})


def provider(model: str) -> str:
    if p := entry(model).get("provider"):
        return p
    if model.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    return "google" if model.startswith("gemini") else "anthropic"


def reasoning(model: str, effort: str) -> str | None:
    """The run's effort if the model lists it, else the model's default. None for a catalogued model without a
    reasoning setting (it runs without thinking); a model missing from the catalog gets the effort as given."""
    e = entry(model)
    if not e:
        return effort
    cfg = e.get("config") or {}
    spec = next((cfg[k] for k in REASONING_KEYS if k in cfg), None)
    if not spec:
        return None
    return effort if effort in (spec.get("options") or []) else spec.get("default", effort)


def max_output(model: str, fallback: int = 16000) -> int:
    spec = (entry(model).get("config") or {}).get("max_output_tokens") or {}
    return int(spec.get("default", fallback))
