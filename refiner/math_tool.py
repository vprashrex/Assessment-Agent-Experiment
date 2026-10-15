"""All alignment maths. Deterministic, pure Python, no model involved. The judge calls these as tools; the loop's
keep/reject gate calls the same functions, so every number anyone sees comes from here.

Notation (for N items with a reference):
    e_i      = output_i − reference_i                       (enum: e_i = 0 if equal else 1)
    MAE      = (1/N) · Σ |e_i|                              average size of the miss
    bias     = (1/N) · Σ e_i                                average direction (+ = scores too high)
    within_k = (1/N) · #{ i : |e_i| ≤ k }                   share of items within k points
    exact    = #{ i : e_i = 0 }                             items matching the reference (counts, for the results sheet)
    scatter  = sqrt( Σ (e_i − bias)² / (N − 1) )            how much the misses differ from each other
    T(n)     = z · scatter / sqrt(n)                        dynamic threshold for a group of n items
                                                            (z = 2 ≈ 95% confidence; smaller groups need a
                                                             bigger average error before it counts)
    pattern  : a group of items is a real pattern if |mean error of the group| > T(n_group)
    volatile : the misses are scattered rather than systematic when
               |bias| ≤ T(N)  (no overall direction)  AND  scatter / sd(reference) ≥ ratio
               (errors as large as the differences between the items themselves)

Every function returns plain JSON-able dicts with values rounded to 4 places. Inputs are explicit:
`errors` is {item_id: error} as produced by `item_errors`.
"""

from __future__ import annotations

import math
from typing import Any

Z = 2.0            # confidence multiplier for the dynamic threshold
VOLATILE_RATIO = 0.75  # scatter / sd(reference) at or above which misses are "as big as the items' own differences"


def _r(x: float) -> float:
    return round(float(x), 4)


def _mean(xs: list[float]) -> float:
    return math.fsum(xs) / len(xs)


def _sd(xs: list[float]) -> float:
    """Sample standard deviation (N − 1). 0 for fewer than two values."""
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(math.fsum((x - m) ** 2 for x in xs) / (len(xs) - 1))


# ---------- per-item ----------

def item_errors(outputs: dict[str, Any], references: dict[str, Any], kind: str = "number") -> dict[str, float]:
    """e_i for every item that has both an output and a reference. kind = 'number' | 'enum'."""
    out = {}
    for i in sorted(outputs):
        o, r = outputs[i], references.get(i)
        if o is None or r is None:
            continue
        out[i] = (0.0 if o == r else 1.0) if kind == "enum" else _r(float(o) - float(r))
    return out


# ---------- whole set / any subset ----------

def alignment(errors: dict[str, float], ids: list[str] | None = None, kind: str = "number") -> dict[str, Any]:
    """MAE, bias, within ±1, within ±2 over all items or the given ids. For enum: accuracy and miss rate."""
    e = [errors[i] for i in sorted(errors) if not ids or i in set(ids)]
    n = len(e)
    if not n:
        return {"n": 0}
    if kind == "enum":
        miss = math.fsum(e) / n
        return {"n": n, "accuracy": _r(1 - miss), "mae": _r(miss)}
    return {"n": n,
            "mae": _r(_mean([abs(x) for x in e])),
            "bias": _r(_mean(e)),
            "within1": _r(sum(abs(x) <= 1 for x in e) / n),
            "within2": _r(sum(abs(x) <= 2 for x in e) / n)}


def agreement(errors: dict[str, float], kind: str = "number") -> dict[str, Any]:
    """Counts for the results sheet: items, exact matches, within ±1, and the average gap (MAE)."""
    e = list(errors.values())
    if not e:
        return {"n": 0}
    out = {"n": len(e), "exact": sum(x == 0 for x in e), "mae": _r(_mean([abs(x) for x in e]))}
    return out if kind == "enum" else {**out, "within1": sum(abs(x) <= 1 for x in e)}


def compare(old: dict[str, float], new: dict[str, float]) -> dict[str, Any]:
    """Items whose |error| got smaller (closer) / larger (further) between two versions, with the size of each move."""
    common = sorted(set(old) & set(new))
    closer = {i: _r(abs(old[i]) - abs(new[i])) for i in common if abs(new[i]) < abs(old[i])}
    further = {i: _r(abs(new[i]) - abs(old[i])) for i in common if abs(new[i]) > abs(old[i])}
    return {"closer": closer, "further": further, "unchanged": len(common) - len(closer) - len(further)}


def threshold(errors: dict[str, float], n: int, z: float = Z) -> dict[str, Any]:
    """T(n) = z · scatter / sqrt(n): the average error a group of n items must exceed to count as a pattern,
    with scatter measured over the whole set (stable even for small groups)."""
    s = _sd(list(errors.values()))
    return {"scatter": _r(s), "n": n, "z": z, "threshold": _r(z * s / math.sqrt(n)) if n > 0 else None}


def pattern_check(errors: dict[str, float], ids: list[str], z: float = Z) -> dict[str, Any]:
    """Is this group of items a real pattern? Mean error of the group vs T(n_group).
    direction: 'too_high' / 'too_low' when real, 'none' when the group's average is inside the noise."""
    g = [errors[i] for i in ids if i in errors]
    if not g:
        return {"n": 0, "real": False}
    t = threshold(errors, len(g), z)["threshold"]
    m = _mean(g)
    real = abs(m) > t
    return {"n": len(g), "mean_error": _r(m), "mean_abs_error": _r(_mean([abs(x) for x in g])), "threshold": t, "real": real,
            "direction": ("too_high" if m > 0 else "too_low") if real else "none",
            "missing_ids": [i for i in ids if i not in errors]}


def volatility(errors: dict[str, float], references: dict[str, Any], ratio: float = VOLATILE_RATIO, z: float = Z) -> dict[str, Any]:
    """Are the misses scattered rather than systematic?
    volatile = |bias| ≤ T(N) and scatter / sd(reference) ≥ ratio.
    systematic_share = bias² / mean(e²): the part of the squared error explained by one overall direction."""
    e = [errors[i] for i in sorted(errors)]
    n = len(e)
    if n < 2:
        return {"n": n, "volatile": False}
    bias, s = _mean(e), _sd(e)
    t = z * s / math.sqrt(n)
    ref_sd = _sd([float(references[i]) for i in sorted(errors)])
    rel = s / ref_sd if ref_sd > 0 else float("inf")
    mse = _mean([x * x for x in e])
    return {"n": n, "bias": _r(bias), "scatter": _r(s), "threshold": _r(t), "reference_sd": _r(ref_sd),
            "scatter_to_reference": _r(rel), "ratio": ratio,
            "systematic_share": _r(bias * bias / mse) if mse > 0 else 0.0,
            "volatile": abs(bias) <= t and rel >= ratio}
