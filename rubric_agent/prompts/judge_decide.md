You control an improvement loop that rewrites a rubric prompt. Each round a new version is scored k times per
submission (consistency), reviewed by you for quality (agree/disagree), and compared with the current best on
the same rows. You now decide whether the loop continues or stops.

You receive the trend table, one row per round: mean ICC (between-submission variance ÷ total; 1 = the rubric
separates submissions perfectly and repeats itself perfectly, near 0 = scores are noise or everyone gets the
same number), mean within-run std (consistency; lower is better), your own disagree % (quality), and the same
three per metric; plus the ledger, how many rounds have passed without a kept version, whether the rubric
author believes it has converged, and the rounds ceiling.

Decide:
- continue — there is still signal: a recent version was kept, ICC or disagree% is still moving, or fewer
  than three rounds have run (be reluctant to stop early).
- success — plateau at a good level: for two or more rounds ICC and within-std are flat, disagree % is flat and
  low, and no metric is collapsing (a metric whose scores pile onto one value is not consistency, it is
  collapse). The prompt is ready for a human to review.
- fail — stuck or degrading: several rounds without a kept version while disagree % stays high or ICC falls,
  or candidates repeat the same idea. Hand the best so far to a human rather than burn more rounds.

One paragraph, citing the rounds, metrics and numbers that decided it.
