"""Descriptions of the measuring tools the judge may call during its round summary (built in engine/loop.py)."""

JUDGE_TOOLS = {
    # ---------- alignment ----------
    'alignment': (
        'MAE, bias, within ±1, within ±2 (or accuracy) of a rubric version against the reference, over all'
        ' items or the given ids.'
    ),

    # ---------- item_errors ----------
    'item_errors': (
        'Per item error (output − reference) for a version, optionally only some ids.'
    ),

    # ---------- compare ----------
    'compare': (
        'Items that moved closer to / further from the reference between two versions, with the size of'
        ' each move.'
    ),

    # ---------- pattern_check ----------
    'pattern_check': (
        "Is a group of items a real pattern? Compares the group's mean error with the dynamic threshold"
        ' z·scatter/√n (n = group size). Returns real true/false and direction.'
    ),

    # ---------- volatility ----------
    'volatility': (
        'Are the misses scattered rather than systematic? volatile = no overall direction beyond the'
        " threshold AND scatter ≥ ratio × the references' own spread."
    ),
}
