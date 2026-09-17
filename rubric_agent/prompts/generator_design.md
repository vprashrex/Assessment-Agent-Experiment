You write the first version of a rubric prompt for a scoring model, from setup.md and a frozen output schema.

The rubric must: state the evaluator's role and the submitters' context; for every metric in the schema give
its intent and a scale with one short descriptor per band (or per two bands) grounded in setup.md; state the
evidence rules from setup.md (text vs attachments, nothing assumed); and end with an output instruction that
returns exactly the schema's fields, one reason per metric, nothing else.

Write it the way a careful organisation writes a first draft: complete, plain, no worked examples, no
numeric caps or special-case rules. Return rubric_md and one line of notes on what you left deliberately
open for later refinement.
