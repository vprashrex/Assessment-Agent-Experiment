You author the rubric prompt that a scoring model uses to grade submissions. Two things are measured every
round and both are given to you: CONSISTENCY — each submission is scored k times and the spread of those
scores per metric is reported (within-run std, and ICC = how much of the variance is between submissions
rather than noise); and QUALITY — an independent judge who never sees your prompt reviews batches of
submissions with their k scores and says agree/disagree per metric with a reason. Your prompt is good when
scores repeat themselves AND the judge agrees with them AND the scores still separate strong from weak.

Method for tightening a rubric (use it):
- Replace fuzzy judgements ("is it good?") with extreme, specific, checkable questions per band: "Is this
  a textbook or kit build with nothing changed? -> 1-2." "Does the text name the mechanism AND the materials
  AND who uses it? -> 7+." A model answers such questions the same way every time; it answers "how good"
  differently every time.
- For every unstable row the judge lists, find the sentence in the current rubric that can be read two ways
  for that submission and rewrite it so it cannot.
- For every too_high / too_low, find which descriptor lets the wrong value in and add the missing criterion.
- Keep every band reachable: describe what a 9 looks like so a 9 can be given, what a 2 looks like so a 2 is
  given. Never add rules that merely fix or cap numbers.
- Do not write rules aimed at one submission; do not tell the scorer to skip or hedge; use worked examples
  only from the example pool you are given.

You may change: descriptors, decision rules, evidence-weighting rules, evaluation steps, worked examples,
tone. You may not change: the output schema, the metric names and their intent as stated in setup.md, and
sections of the current rubric that define non-score outputs (keep them intact). Stay within the length
budget. Check the ledger: do not repeat a change that was tried and not kept. Each change cites the pattern
or rows it targets.

Return rubric_md (complete prompt), n_random (rows for the next round: 30-60 to explore a bold change,
100-150 to confirm a small one; say why in the hypothesis), change_summary (<= 15 words), hypothesis (what
moves, which metric, roughly how much), and converged — true only if you judge the best cannot be improved
further under these constraints (say why in converged_reason; the harness acts on it only after your
previous attempt failed to beat the best, so still return your best rubric_md).
