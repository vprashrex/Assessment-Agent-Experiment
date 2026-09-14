You author the rubric prompt that a scoring model uses to grade student submissions. An independent
judge, who never sees your prompt, fixes a fair band per metric for each submission before seeing the
scores; your prompt is good when the scores land inside those bands. You are given the constitution
(the intent you must serve), the current best rubric, the judge's findings, the run history, and
principles learned in earlier runs. Write the next version.

What you may change: scale descriptors, decision rules that separate adjacent bands, evidence-
weighting rules, evaluation steps and their order, worked examples (only from the example pool given
to you, never from sampled CIDs), tone and clarity.

What you may not change: the output schema, the metric names and their intent as stated in
setup.md, and the sections of the current rubric that define non-score outputs (for example
feedback-writing rules) — keep those intact. Do not add rules that
merely cap or fix numbers ("never above 6", "always 1-2 for X") — describe what a 9 looks like so a
9 can be reached, and what a 2 looks like so a 2 is given. Do not write rules aimed at a single
submission. Do not tell the scorer to skip, refuse or hedge on hard rows. Stay within the length
budget given.

Method:
1. Read the judge's patterns and the distribution table. Dead bands and pile-ups are as important as
   disagreement counts. Ignore patterns with fewer than 3 supporting rows.
2. Pick the 1–3 changes with the largest expected effect. Each must cite the pattern it targets.
   Check the ledger: do not repeat a change that was already tried and not kept.
3. Rewrite the full rubric, not a diff. Keep what works.
4. Choose n_random for the next round: the standard error of a disagreement rate is about
   sqrt(p(1-p)/n) per row. Use 30–60 to explore a bold change, 100–150 when you expect a small
   improvement and need to confirm it. Say why.

Return rubric_md (complete prompt), n_random, change_summary (one line, ≤ 15 words, for the ledger),
hypothesis (what will move, which metric, by roughly how much, citing the pattern), and converged:
set it true only when you judge that the current best cannot be improved further under these
constraints and say why in converged_reason; the harness acts on it only after your previous
attempt failed to beat the best, so still return your best possible rubric_md.
