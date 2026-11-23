"""Rubric refiner: refines an assessment prompt until a scoring model agrees with human reference judgements.

Public API (api.py):
    RunConfig, prepare, refine, start, stop, status, checklist, version_report, report
"""

from .api import checklist, prepare, refine, report, start, status, stop, version_report
from .config import RunConfig
from .engine.loop import NeedsAnswers

__version__ = "0.1.0"
__all__ = ["RunConfig", "NeedsAnswers", "prepare", "refine", "start", "stop", "status", "checklist", "version_report", "report"]
