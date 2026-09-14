You are reviewing the output of a rubric prompt on a batch of submissions. For each row you
receive, an independent band was fixed BEFORE the rubric's score was seen, and the rubric's score fell
outside it. Explain why, then find the patterns.

For every row:
- comment: one or two sentences. What evidence did the rubric over- or under-weight relative to the
  band's evidence? Be concrete; quote the submission or the reason when useful.
- defects: zero or more of exactly these tags —
  unsupported_evidence (reason cites something not in the submission),
  contradicts_score (reason argues for a different score than given),
  pipeline_internals (reason mentions fields, schemas, summaries or the model itself),
  ignores_evidence_rule (reason weighs attachments or claims against the constitution's rules),
  language_mismatch (reason or feedback not in the submitter's language),
  generic_reason (reason could apply to any submission).

Then patterns: for each metric, 2 to 4 recurring causes of disagreement, each with the CIDs that
support it. Only report a pattern with at least 3 supporting rows. A pattern names the kind of
submission and the direction of error, e.g. "combining several known components is scored as low
originality even when the combination is the idea".

summary: three lines on where the rubric is most wrong and where it is fine. Do not propose rubric
wording; that is someone else's job.
