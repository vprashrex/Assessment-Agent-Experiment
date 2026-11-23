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
    gate     : exact matches decide, measured twice — no fixed thresholds:
               a candidate wins when it has more exact matches than the best (ties fall to MAE, then to length).
               A first-pass win only makes it borderline: the loop scores it once more and the POOLED numbers
               (mean of both passes) give the verdict. A scorer that merely wavers does not win twice.
               kept   = pooled exact > best's, or equal exact and pooled MAE lower, or equal both and shorter
               Words never veto a win: length is handled by the measured simplify loop (shrink until the
               exact matches drop) and the shorter-wins tie-break.
    diagnosis: when a loop stops flat, code (never a model) names the likeliest blocker from the signals —
               volatile misses with even moves → the reference scores themselves disagree;
               scores flipping between identical passes → the scoring model is unsteady;
               a one-sided bias that persists → the rubric/context lacks criteria for that direction.

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
    """e_i for every item that has both an output and a reference. kind = 'number' | 'enum' | 'verdict'.

    'verdict' (feedback mode, no golden dataset): the reference is a constraint the operator gave against the
    assessment's own score — {"old": score, "verdict": agree | too_high | too_low, "target": number | None} —
    and the error says whether the new score satisfies it:
        target set → e = new − target        agree → e = new − old (any move is a miss)
        too_high   → 0 when new < old, else +1 (still too high)
        too_low    → 0 when new > old, else −1 (still too low)
    So exact = verdicts satisfied, bias = the net direction still wrong; no score is ever invented."""
    out = {}
    for i in sorted(outputs):
        o, r = outputs[i], references.get(i)
        if o is None or r is None:
            continue
        if kind == "verdict":
            old, v, tgt = float(r.get("old", 0)), r.get("verdict", "agree"), r.get("target")
            new = float(o)
            out[i] = (_r(new - float(tgt)) if tgt is not None
                      else _r(new - old) if v == "agree"
                      else (0.0 if new < old else 1.0) if v == "too_high"
                      else (0.0 if new > old else -1.0))
        else:
            out[i] = (0.0 if o == r else 1.0) if kind == "enum" else _r(float(o) - float(r))
    return out


def _refval(r: Any) -> float | None:
    """A reference as a number for spread maths: the value itself, or a verdict constraint's old score."""
    try:
        return float(r.get("old")) if isinstance(r, dict) else float(r)
    except (TypeError, ValueError):
        return None


# ---------- whole set / any subset ----------

def alignment(errors: dict[str, float], ids: list[str] | None = None, kind: str = "number") -> dict[str, Any]:
    """MAE, bias, within ±1, within ±2 over all items or the given ids. For enum: accuracy and miss rate."""
    e = [errors[i] for i in sorted(errors) if not ids or i in set(ids)]
    n = len(e)
    if not n:
        return {"n": 0}
    exact = sum(1 for x in e if x == 0)
    if kind == "enum":
        miss = math.fsum(e) / n
        return {"n": n, "accuracy": _r(1 - miss), "mae": _r(miss), "exact": exact}
    return {"n": n,
            "mae": _r(_mean([abs(x) for x in e])),
            "bias": _r(_mean(e)),
            "within1": _r(sum(abs(x) <= 1 for x in e) / n),
            "within2": _r(sum(abs(x) <= 2 for x in e) / n),
            "exact": exact}


def agreement(errors: dict[str, float], kind: str = "number") -> dict[str, Any]:
    """Counts for the results sheet: items, exact matches, within ±1, and the average gap (MAE)."""
    e = list(errors.values())
    if not e:
        return {"n": 0}
    out = {"n": len(e), "exact": sum(x == 0 for x in e), "mae": _r(_mean([abs(x) for x in e]))}
    return out if kind == "enum" else {**out, "within1": sum(abs(x) <= 1 for x in e)}


def summary(errors: dict[str, float], kind: str = "number") -> dict[str, Any]:
    """The numbers every version event carries: `alignment` over every item (MAE, bias, within ±1/±2 or accuracy, exact)."""
    return alignment(errors, None, kind)


def pool(first: float, second: float) -> float:
    """The gate's pooled number from two scoring passes: their mean."""
    return _r((float(first) + float(second)) / 2)


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
    ref_sd = _sd([x for i in sorted(errors) if (x := _refval(references.get(i))) is not None])
    rel = s / ref_sd if ref_sd > 0 else float("inf")
    mse = _mean([x * x for x in e])
    return {"n": n, "bias": _r(bias), "scatter": _r(s), "threshold": _r(t), "reference_sd": _r(ref_sd),
            "scatter_to_reference": _r(rel), "ratio": ratio,
            "systematic_share": _r(bias * bias / mse) if mse > 0 else 0.0,
            "volatile": abs(bias) <= t and rel >= ratio}


def diagnose(errors: dict[str, float], references: dict[str, float], exact_v0: int, exact_best: int,
             rounds: int, kept: int, flips: int | None = None, flip_n: int = 0) -> dict[str, Any]:
    """Why a loop stopped flat, from the numbers alone (code, never a model): the likeliest blockers, one
    plain-language note and one action for the operator."""
    n = len(errors)
    e = [float(x) for x in errors.values()]
    bias = _mean(e) if e else 0.0
    t = Z * _sd(e) / math.sqrt(n) if n > 1 else 0.0
    up, down = sum(1 for x in e if x > 0), sum(1 for x in e if x < 0)
    sym = min(up, down) / max(up, down) if max(up, down) else 1.0
    vol = volatility(errors, references) if n > 1 and references else {"volatile": False}
    flip_rate = (flips / flip_n) if flips is not None and flip_n else None
    causes: list[str] = []
    action = ""
    if flip_rate is not None and flip_rate >= 0.2:
        causes.append(f"the scoring model is unsteady — {flips} of {flip_n} submissions got a different score "
                      "on an identical second pass, so real improvements drown in that wobble")
        action = "try a steadier scoring model, or average two scoring passes when using the rubric"
    if vol.get("volatile") and sym >= 0.6:
        causes.append(f"the remaining misses pull both ways about evenly ({up} scored too high, {down} too low) "
                      "with no pattern — this usually means the reference scores themselves disagree from "
                      "reviewer to reviewer, so no wording can match them all")
        action = action or ("have the reviewers jointly re-score the submissions where the sheet and the rubric "
                            "differ by 2 or more points, write down the criteria they agree on, and refine again")
    if t > 0 and abs(bias) > t:
        lean = "high" if bias > 0 else "low"
        causes.append(f"scores still lean {lean} overall (bias {bias:+.2f}) — the rubric or the context notes "
                      "lack a criterion that decides these cases")
        action = action or "add the missing rule to the context notes or the base rubric, then refine again"
    if not causes:
        causes.append("the rubric has learned what this data can teach — the remaining misses are one-point "
                      "judgement calls on band boundaries")
        action = action or ("collect a few more scored submissions (especially near the disputed boundary), "
                            "or treat the within-±1 agreement as the working measure")
    note = (f"After {rounds} round(s) and {kept} kept change(s), exact matches went {exact_v0} → {exact_best} "
            f"of {n} and then stopped improving. Likeliest blocker: {causes[0]}."
            + (" Also: " + "; ".join(causes[1:]) + "." if len(causes) > 1 else "")
            + f" Suggested next step: {action}.")
    return {"signals": {"n": n, "bias": _r(bias), "threshold": _r(t), "too_high": up, "too_low": down,
                        "symmetry": _r(sym), "volatile": bool(vol.get("volatile")),
                        "flip_rate": _r(flip_rate) if flip_rate is not None else None},
            "causes": causes, "action": action, "note": note}


def keep_candidate(exact_best: float, exact_cand: float, mae_best: float, mae_cand: float,
                   words_best: int, words_cand: int, closer: int = 0, further: int = 0,
                   confirm: bool = False) -> dict[str, Any]:
    """The keep/reject gate (see the module docstring): exact matches decide, measured twice. The first pass only
    marks a winner borderline; the loop scores it once more and calls again with the POOLED numbers (mean of both
    passes) and `confirm=True`, which makes the verdict final. `closer`/`further` are information for the events;
    they do not gate."""
    gain, added = _r(mae_best - mae_cand), words_cand - words_best
    out = {"gain": gain, "added_words": added, "closer": closer, "further": further,
           "exact_best": exact_best, "exact_cand": _r(exact_cand), "kept": False, "borderline": False, "reason": ""}
    wins = exact_cand > exact_best or (exact_cand == exact_best and gain > 0)
    if wins:
        if confirm:
            out["kept"] = True
        else:
            out["borderline"] = True  # measure twice: one more scoring pass, then the pooled numbers decide
            out["reason"] = "ahead on the first pass — confirming with a second one"
    elif exact_cand == exact_best and gain == 0 and added < 0:
        out["kept"] = True  # as accurate, shorter: nothing to confirm, the text just got smaller
    else:
        out["reason"] = ("as accurate but not shorter" if exact_cand == exact_best and gain <= 0
                         else "fewer exact matches" if exact_cand < exact_best else "less accurate")
    return out

