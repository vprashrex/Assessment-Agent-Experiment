You write setup.md: the single document that a rubric author (generator) and an independent judge
will both read. Neither of them sees anything else about the task. Write it from the operator's
context, the existing rubric prompt, and the output schema.

setup.md must contain, in Markdown:
1. Who the submitters are, what a submission contains, and what the scoring model receives.
2. For every scored metric: its name, its intent in one or two lines, and its full scale descriptors
   copied verbatim from the existing prompt.
3. Evidence rules: how text and attachments are weighed, what may never be assumed, how
   contradictions are resolved, any language rule.
4. How to judge: the evaluation principles (context of the submitters, evidence-based, fair) and
   what the judge must NOT do.
5. Anything else in the operator context that changes how a metric should be read.

Leave out rules that merely fix or cap a number ("cannot exceed 6", "assign 1-2 in case X"). Those
are the old prompt's scoring policy, not the intent the judge should hold. Do not add rules of your
own and do not summarise the descriptors.

Also fill `metrics`: for every scored dimension, its name, the dot-path of its numeric score in the
output schema, the dot-path of its reason text (or null), and the scale min and max.
