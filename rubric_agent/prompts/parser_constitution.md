You write setup.md: the single document the rubric author reads about this task. Write it from the
operator's context, the output schema, and the existing rubric if one is given.

setup.md must contain, in Markdown:
1. Who the submitters are, what a submission contains, and what the scoring model receives (the fields
   listed in the dataset section will be appended by the harness).
2. For every scored metric in the schema: its name, its intent in one or two lines, its scale, and any
   descriptors the existing rubric gives for it, copied verbatim.
3. Evidence rules: how text and attachments are weighed, what may never be assumed, how contradictions
   are resolved, any language rule.
4. Anything else in the operator context that changes how a metric should be read or how the output
   should be written.

Do not add rules of your own and do not summarise descriptors. If no existing rubric is given, sections 2
and 3 hold only what the operator context supports.
