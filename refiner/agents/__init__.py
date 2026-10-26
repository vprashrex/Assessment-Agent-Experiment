"""The four model-backed agents and what they share. CLAUDE.md in this folder says what each file does.

    parser.parse       once per run: columns, metrics, layers, questions
    scorer.score_all   per item: the scoring model applies a rubric version
    judge.review       per item: why the score differs from the reference; judge.summarise: the round's issues
    generator.generate per round: the next version of the metrics sections
"""

from .generator import GEN_SCHEMA, apply, generate, rewrite
from .judge import ITEM_SCHEMA, SUMMARY_SCHEMA, checklist_text, review, summarise, table
from .layers import EDITABLE, LAYERS, annotated, assemble, files_of, layout, metrics_of, numbered, reference
from .parser import SETUP_SCHEMA, parse, profile
from .scorer import output_schema, parse_output, score, score_all

__all__ = [
    "EDITABLE", "GEN_SCHEMA", "ITEM_SCHEMA", "LAYERS", "SETUP_SCHEMA", "SUMMARY_SCHEMA", "annotated", "apply", "assemble",
    "checklist_text", "files_of", "generate", "layout", "metrics_of", "numbered", "output_schema", "parse", "parse_output",
    "profile", "reference", "review", "rewrite", "score", "score_all", "summarise", "table",
]
