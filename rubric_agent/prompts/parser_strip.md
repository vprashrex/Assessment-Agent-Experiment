You produce the STARTING rubric for an automated refinement run. You are given a mature, hand-tuned rubric
prompt. Return a deliberately under-specified version of it — the kind of first draft an organisation writes
before months of refinement:

- Keep: the role/persona in one or two sentences, the list of metrics with a one-line intent each, the
  scale range, the output format section verbatim (the scorer must still return the same JSON), and any
  section that defines a non-score output (for example feedback-writing rules) verbatim.
- Remove: per-band descriptors (replace each metric's scale with one sentence like "1 = weakest, 10 =
  strongest"), numeric caps and fixed-band rules, worked examples, evidence-weighting rules, step-by-step
  procedures, guardrail lists.
- Do not add anything. Do not fix anything. Keep the language and tone of the original.

Return rubric_md and `removed`: one line per kind of content you took out.
