"""The four model-backed agents and what they share. CLAUDE.md in this folder says what each file does.

    parser.parse       once per run: columns, metrics, layers, questions
    scorer.score_all   per item: the scoring model applies a rubric version
    judge.review       per item: why the score differs from the reference; judge.summarise: the round's issues
    generator.generate per round: the next version of the metrics sections
"""

from .generator import generate
from .judge import review, summarise, synthetic_reviews, table, tools
from .layers import (EDITABLE, LAYERS, PROCEDURE, annotated, assemble, editable_words, kind_of, layout, metrics_of, reference,
                     refs_by)
from .parser import parse
from .scorer import score, score_all

__all__ = [
    "EDITABLE", "LAYERS", "PROCEDURE", "annotated", "assemble", "editable_words", "generate", "kind_of", "layout", "metrics_of",
    "parse", "reference", "refs_by", "review", "score", "score_all", "summarise", "synthetic_reviews", "table", "tools",
]
