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
        'ERROR (output − reference): {error}'
    ),

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

    # ---------- generator mode line: rewrite the metrics sections (scattered misses) ----------
    'generator_mode_rewrite': (
        'MODE: REWRITE — the reviewer measured the misses as scattered with no systematic pattern, so piecewise edits will not converge. Brief: {brief}'
    ),

    # ---------- generator retry: the first message again, with why its edits were rejected ----------
    'generator_retry': (
        '{message}\n'
        '\n'
        'REJECTED: {problems}. Fix and return again.'
    ),
}
