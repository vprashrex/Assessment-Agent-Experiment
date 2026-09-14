"""Parser agent: cleans the sheet, picks columns, writes setup.md, describes attachments once."""

from .build import run, scores_from, submission_text

__all__ = ["run", "scores_from", "submission_text"]
