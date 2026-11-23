"""The message each model call sends, as templates: agents/ fills the {placeholders} (prompts.render).
A literal brace would need doubling ({{), so templates hold none."""

USER = {
    # ---------- parser: the sheet's columns, the operator notes, the current rubric (line-numbered), the output schema ----------
    'parser': (
        'OPERATOR NOTES:\n'
        '{context}\n'
        '\n'
        'CURRENT PROMPT (line-numbered):\n'
        '<<<\n'
        '{rubric}>>>\n'
        '\n'
        'OUTPUT SCHEMA (may be absent):\n'
        '{schema}\n'
        '\n'
        'COLUMNS:\n'
        '{columns}'
    ),

    # ---------- judge, shared stages (procedure, polish): the review row built from the numbers alone ----------
    'synthetic_review': '{metric}: output off by {size}',

    # ---------- judge, per item: how a verdict reference (feedback mode) is described instead of a score ----------
    'judge_verdict_reference': "(no reference score — a reviewer's verdict on the earlier score {old}: {verdict}{remark})",
    'judge_verdict_remark': '; their remark: {remark}',
    'judge_review_unavailable': '(review unavailable: {error})',

    # ---------- judge and generator: the checklist as text (status and numbers measured by code) ----------
    'checklist_empty': '(empty — first round)',
    'checklist_entry': (
        '[{id}] {status} · {title} ({direction}, {n} items: {items})\n'
        '   root cause: {root_cause}\n   clause: {clause}\n   fix: {fix}\n'
        '   measured on {version}: mean error {mean_error} vs threshold {threshold} · history: {history}'
    ),

    # ---------- judge, round: one submission's note in the summary call ----------
    'judge_note': (
        '[{id}] {direction} ({size})\n   observations: {observations}\n'
        '   model reasoning: {model_reasoning}\n   clause: {clause}\n   comment: {comment}'
    ),

    # ---------- judge, round: what happened to the last candidate (the loop writes it, the judge reads it) ----------
    'last_change_baseline': '(baseline — no edit yet)',
    'last_change_shared': '(shared stage)',
    'last_change': (
        '{cand} (edited from {best}) was {verdict}{reason}. Its metrics text has {words} words '
        '({best} has {best_words}, the original {v0_words}). Use the tools to measure it against {best}.\n'
        'Items this edit pushed further from the reference, with the reason:\n{items}'
    ),
    'last_change_item': '  [{id}] {direction} — clause: {clause} — {comment}',

    # ---------- generator: the round's overview in the two stages that run no judge summary ----------
    'simplify_overview': 'The refinement has stopped. Say the same thing in fewer words; change no meaning.',
    'polish_overview': (
        'Composed stage: the whole rubric is scored together, as in production. '
        "The weakest part now is '{target}'. Fix only what the table shows; the rest of the rubric is locked."
    ),

    # ---------- generator: why an edit was not applied (sent back with generator_retry) ----------
    'problem_locked': 'old_text is in a LOCKED part: {old}',
    'problem_not_found': 'old_text not found exactly once in an EDITABLE part: {old}',
    'problem_rewrite_parts': 'rewrite must return exactly {n} non-empty parts, one per EDITABLE part, in order',
    'problem_repetition': 'degenerate repetition in the new text ({sample}); write real sentences',

    # ---------- every agent: how the rubric's parts are marked in the prompt ----------
    'marker_editable': '[EDITABLE · {layer} · part {k}]\n{text}\n[/EDITABLE]',
    'marker_locked': '[LOCKED · {layer}]\n{text}\n[/LOCKED]',

    # ---------- parser, when the operator gave no notes: stands in for {context} ----------
    'parser_no_notes': (
        '(none given: work out the inputs, the reference columns and the layers from the columns and the rubric'
        ' alone, and ask a question only for what they cannot settle)'
    ),

    # ---------- scorer: one submission (its system prompt is the rubric being refined) ----------
    'scorer': (
        '{submission}\n'
        '\n'
        'Return the JSON object exactly as specified.'
    ),

    # ---------- judge, per item: why one submission's score differs from the reference ----------
    'judge_item': (
        'TASK: ITEM\n'
        '\n'
        'RUBRIC (the scoring model sees it without the LOCKED/EDITABLE marks):\n'
        '<<<\n'
        '{rubric}\n'
        '>>>\n'
        '\n'
        'SUBMISSION (as the scoring model saw it; any attached files are part of it):\n'
        '<<<\n'
        '{submission}\n'
        '>>>\n'
        '\n'
        'MODEL OUTPUT: {output}\n'
        'REFERENCE: {reference}\n'
        'WHY THE REFERENCE WAS GIVEN (the reviewers\' own comments; they may cover several metrics):\n'
        '<<<\n'
        '{rationale}\n'
        '>>>\n'
        'ERROR (output − reference): {error}'
    ),
    'judge_no_rationale': '(the sheet carries no comments)',

    # ---------- judge, per round: every item's notes, the checklist, what changed ----------
    'judge_summary': (
        'TASK: SUMMARY\n'
        '\n'
        'CURRENT BEST RUBRIC ({version}; the scoring model sees it without the LOCKED/EDITABLE marks):\n'
        '<<<\n'
        '{rubric}\n'
        '>>>\n'
        '\n'
        'VERSIONS SCORED SO FAR: {versions}\n'
        '\n'
        'ISSUE CHECKLIST FROM EARLIER ROUNDS:\n'
        '{checklist}\n'
        '\n'
        'WHAT CHANGED SINCE LAST ROUND:\n'
        '{change}\n'
        '\n'
        'NOTES ON EVERY SUBMISSION, scored with {version}:\n'
        '{notes}\n'
        '\n'
        'DIALOGUE SO FAR:\n'
        '{dialogue}'
    ),

    # ---------- generator: the next version, from the judge's overview, summary, checklist and per-item table ----------
    'generator': (
        '{mode}\n'
        '\n'
        '{length}\n'
        '\n'
        'CURRENT RUBRIC:\n'
        '<<<\n'
        '{rubric}>>>\n'
        '\n'
        'REVIEWER OVERVIEW:\n'
        '{overview}\n'
        '\n'
        'REVIEWER SUMMARY:\n'
        '{summary}\n'
        '\n'
        'ISSUE CHECKLIST:\n'
        '{checklist}\n'
        '\n'
        'PER-ITEM TABLE:\n'
        '{table}\n'
        '\n'
        'DIALOGUE SO FAR:\n'
        '{dialogue}'
    ),

    # ---------- generator mode line: patch the metrics sections ----------
    'generator_mode_edit': (
        'MODE: EDIT'
    ),

    # ---------- generator mode line: only merge and shorten; no new rules ----------
    'generator_mode_simplify': (
        'MODE: SIMPLIFY — do not add any new rule or distinction. Only merge guidance that repeats, delete text that '
        'no longer decides a score, and tighten wording, so the EDITABLE parts say the same thing in fewer words.'
    ),

    # ---------- generator mode line: rewrite the metrics sections (scattered misses) ----------
    'generator_mode_rewrite': (
        'MODE: REWRITE — the reviewer measured the misses as scattered with no systematic pattern, so piecewise edits will not converge. Brief: {brief}'
    ),

    # ---------- generator length line: the editable text's size now and in v0; no target is set ----------
    'generator_length': (
        'LENGTH: the EDITABLE parts hold {words} words now; they held {v0_words} in the original rubric. You decide '
        'the length.'
    ),

    # ---------- generator retry: the first message again, with why its edits were rejected ----------
    'generator_retry': (
        '{message}\n'
        '\n'
        'REJECTED: {problems}. Fix and return again.'
    ),
}
