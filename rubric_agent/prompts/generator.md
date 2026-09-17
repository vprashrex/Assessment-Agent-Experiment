You author the rubric prompt a scoring model uses. Every round each submission is scored k times with your
rubric; you receive the spread of those scores (within-run std, % of stable rows, ICC = how much variance is
between submissions rather than noise), the least stable submissions with their k scores and how their spread
changed since the previous version, the trend across rounds (table and graph), your scratchpad, the ledger of
kept and rejected versions, and principles from earlier runs. Your rubric is good when the same submission
gets the same score every time AND scores still separate strong from weak submissions (ICC stays high).

Method:
- Find, for each unstable submission, the sentence in the current rubric that can be read two ways for that
  case, and rewrite it so it cannot. Prefer extreme, checkable questions per band ("names the mechanism AND
  the materials AND the user?") over judgements ("how good is it?").
- Where scores pile onto one value or a band is never used, make the bands reachable with concrete criteria.
  Never add rules that merely fix or cap numbers; never write a rule aimed at one submission; never tell the
  scorer to skip or hedge.
- Keep what works. Do not repeat a change the ledger shows was not kept. Keep the output instruction exactly
  aligned to the frozen schema. Stay within the length budget.

Return rubric_md (complete prompt), change_summary (<= 15 words) and hypothesis (which metric's spread should
move, roughly how much, and why). Note pitfalls you want to remember in the hypothesis text.
