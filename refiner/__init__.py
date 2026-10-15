"""Rubric refiner: refines an assessment prompt until a scoring model agrees with human reference judgements.

Public API — see refiner/README.md:
    RunConfig, prepare, refine, start, stop, status, checklist, version, list_runs
"""

from .api import checklist, list_runs, prepare, refine, start, status, stop, version
from .config import RunConfig
from .loop import NeedsAnswers

__version__ = "0.1.0"
__all__ = ["RunConfig", "NeedsAnswers", "prepare", "refine", "start", "stop", "status", "checklist", "version", "list_runs"]
