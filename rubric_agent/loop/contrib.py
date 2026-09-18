"""Which metric moved the overall std, and by how much.

`_within` is the unweighted mean of the per-metric within-std, so

    Δ_overall = (1/M) · Σ_m Δ_m

holds exactly — no interaction term, no residual, every metric weighted 1/M whatever its
level. So `contribution` below is not an approximation: it is that identity, term by term,
in the same units as the number the gate reads. `reconstruct` asserts it rather than
trusting it.

Three things the shares cannot say on their own, and which the callers here surface:

  * **A share is not evidence.** The only honest yardstick for a per-metric Δ is a re-score
    of the *same* rubric, which is exactly what the assurance round is. `noise_floor` reads
    the yardstick off those rounds. Before one exists it falls back to the analytic SE —
    flagged as such, because with the rows held fixed the SE understates the real floor by
    roughly an order of magnitude: scorer stochasticity, not row sampling, dominates.

  * **Shares are signed and need not lie in [0, 100].** When metrics move in opposite
    directions the denominator is a near-cancellation, so one metric can read 227% while
    another reads -55%. `gross` (|Δ| over Σ|Δ|) is the churn view that stays in [0, 100]
    and shows the offsetting movement the signed share hides.

  * **Mean-of-std is not variance-additive.** `_var` is. When the two orderings disagree,
    `rank_flip` says so and the std-based ranking is the weaker claim.

`compression` covers the other way a share misleads: a revision that only pushes scores
down the scale shrinks per-row std mechanically. within/between = sqrt((1-ICC)/ICC) is
scale-free, so a metric whose raw std fell while that ratio did not has not improved.
"""

from __future__ import annotations

import math
from typing import Any

WITHIN, VAR = "within", "var"


def _rows(trend: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [t for t in trend if t.get("per_metric")]


def analytic_se(x: dict[str, Any], n: int) -> float:
    """SE of the mean per-row std. Var(s) = E[s²] - E[s]² = var - within², so SE = sd(s)/sqrt(n).

    A floor on the true uncertainty, never an estimate of it — it prices row sampling only,
    and the rows do not change between rounds.
    """
    return math.sqrt(max(x[VAR] - x[WITHIN] ** 2, 0.0) / max(n, 1))


def noise_floor(trend: list[dict[str, Any]], metrics: list[str], n: int = 0) -> dict[str, Any]:
    """The per-metric Δ you get from re-scoring an unchanged rubric.

    Pairs every assurance round with the same version's own earlier round: identical rubric,
    identical rows, so every Δ there is noise by construction. Returns the RMS over those
    pairs, which is the threshold a per-metric Δ has to clear to mean anything.
    """
    rows = _rows(trend)
    deltas: list[float] = []
    pairs: list[tuple[str, int, int]] = []
    for a in rows:
        if not a.get("assure"):
            continue
        base = next((b for b in rows if b["version"] == a["version"] and not b.get("assure")), None)
        if base is None:
            continue
        pairs.append((a["version"], base["round"], a["round"]))
        deltas += [a["per_metric"][m][WITHIN] - base["per_metric"][m][WITHIN] for m in metrics]
    if deltas:
        return {"floor": math.sqrt(sum(d * d for d in deltas) / len(deltas)), "source": "assurance re-score",
                "pairs": pairs, "n_deltas": len(deltas), "max": max(abs(d) for d in deltas)}
    se = [analytic_se(rows[-1]["per_metric"][m], n) for m in metrics] if rows and n else []
    return {"floor": (sum(se) / len(se)) if se else 0.0, "source": "analytic SE (understates: no re-score yet)",
            "pairs": [], "n_deltas": 0, "max": 0.0}


def decompose(cur: dict[str, Any], base: dict[str, Any], metrics: list[str], floor: float = 0.0) -> dict[str, Any]:
    """Split cur[_within] - base[_within] into one exact term per metric."""
    m_, b_ = cur["per_metric"], base["per_metric"]
    M = len(metrics)
    d = {m: m_[m][WITHIN] - b_[m][WITHIN] for m in metrics}
    dv = {m: m_[m][VAR] - b_[m][VAR] for m in metrics}
    tot, gross = sum(d.values()), sum(abs(x) for x in d.values())
    tot_v = sum(dv.values())
    out = []
    for m in sorted(metrics, key=lambda m: d[m]):
        out.append({"metric": m, "from": b_[m][WITHIN], "to": m_[m][WITHIN], "delta": round(d[m], 4),
                    "contribution": round(d[m] / M, 4),
                    "share": round(100 * d[m] / tot, 1) if abs(tot) > 1e-12 else None,
                    "gross": round(100 * abs(d[m]) / gross, 1) if gross > 1e-12 else None,
                    "var_share": round(100 * dv[m] / tot_v, 1) if abs(tot_v) > 1e-12 else None,
                    "verdict": "worse" if d[m] > 2 * floor else "better" if d[m] < -2 * floor
                               else "noise" if abs(d[m]) < floor else "weak"})
    rank_s = [x["metric"] for x in sorted(out, key=lambda x: x["delta"])]
    rank_v = [x["metric"] for x in sorted(out, key=lambda x: dv[x["metric"]])]
    return {"d_overall": round(cur[WITHIN] - base[WITHIN], 4), "sum_contributions": round(tot / M, 4),
            "residual": round(tot / M - (cur[WITHIN] - base[WITHIN]), 5), "floor": round(floor, 4),
            "beyond_floor": sum(1 for x in out if x["verdict"] in ("better", "worse")),
            "rank_flip": rank_s != rank_v, "rank_by_var": rank_v, "metrics": out}


def compression(cur: dict[str, Any], base: dict[str, Any], metrics: list[str]) -> list[dict[str, Any]]:
    """Per metric: did the std fall because the scorer agrees, or because the scale shrank?

    within/between = sqrt((1-ICC)/ICC) is invariant to any rescaling of the scores, so it
    separates the two. `mean` drift is reported beside it as the mechanism.
    """
    def ratio(x: dict[str, Any]) -> float:
        i = min(max(x["icc"], 0.0), 1 - 1e-9)
        return math.sqrt((1 - i) / i) if i > 0 else float("inf")

    out = []
    for m in metrics:
        a, b = base["per_metric"][m], cur["per_metric"][m]
        ra, rb = ratio(a), ratio(b)
        d_raw, d_rat = b[WITHIN] - a[WITHIN], rb - ra
        # Compression is specifically a std that FELL without the scale-free ratio following it.
        # A std that rose is simply worse, and a ratio that improved while the std rose means the
        # metric started separating submissions faster than it got noisier.
        if d_raw > 0.002:
            v = "worse" if d_rat > 0.002 else "noisier but more discriminating"
        elif d_raw < -0.002:
            v = "real gain" if d_rat < -0.002 else "SCALE COMPRESSION — not a gain"
        else:
            v = "flat"
        out.append({"metric": m, "d_mean": round(b.get("mean", 0) - a.get("mean", 0), 3),
                    "d_within": round(d_raw, 4), "wb_from": round(ra, 4), "wb_to": round(rb, 4),
                    "d_wb": round(d_rat, 4), "verdict": v})
    return out


def tolerances(metrics: list[str], se: dict[str, float], floor: float) -> dict[str, float]:
    """How far a single metric has to move before it counts as having moved.

    max of two error sources, because they measure different things and neither dominates
    everywhere: the bootstrap SE prices resampling the submissions (and is ±inf on a sample too
    small to bootstrap, which correctly disables the guard), the retest floor prices re-asking the
    scorer. On the recorded runs the floor is the larger of the two by roughly 1.5x.
    """
    return {m: max(2 * se.get(f"{m}.within", 0.0), floor) for m in metrics}


def trade_guard(d: dict[str, float], tol: dict[str, float]) -> dict[str, Any]:
    """Did this revision buy its overall win by making one metric better and others worse?

    Two questions, and only the pair of answers is a verdict:

      * did any metric regress past its own tolerance?
      * is the win *broad* — does it survive deleting the single metric that contributed most of
        it? That is a leave-one-out on the identity, and it is the whole test: a revision whose
        gain lives entirely in one metric while three others slide is the failure mode the
        aggregate cannot see, because mean-of-std lets one large negative term pay for several
        small positive ones.

    A regression on its own does not block — the best revision on either recorded run regressed a
    metric while improving three. What blocks is a regression whose win does not survive the
    leave-one-out.
    """
    metrics = list(d)
    regressed = sorted((m for m in metrics if d[m] > tol[m]), key=lambda m: -d[m])
    best = min(metrics, key=lambda m: d[m]) if metrics else None
    loo = (sum(d[m] for m in metrics if m != best) / (len(metrics) - 1)) if len(metrics) > 1 else 0.0
    broad = loo <= 0
    return {"regressed": regressed, "dropped": best, "loo": round(loo, 4), "broad": broad,
            "blocked": bool(regressed) and not broad,
            "why": (f"{', '.join(regressed)} regressed and the win does not survive dropping {best} "
                    f"(leave-one-out mean Δ {loo:+.3f})") if regressed and not broad
                   else (f"{', '.join(regressed)} regressed but the win is broad without {best} ({loo:+.3f})"
                         if regressed else "no metric regressed past tolerance")}


def parent(versions: dict[str, Any], trend: list[dict[str, Any]], row: dict[str, Any]) -> dict[str, Any] | None:
    """The round this round should be compared against: its own earlier scoring for an
    assurance re-score, otherwise the round that scored the version it branched from."""
    rows = _rows(trend)
    if row.get("assure"):
        return next((b for b in rows if b["version"] == row["version"] and not b.get("assure")), None)
    base = (versions.get(row["version"]) or {}).get("base")
    if not base:
        return None
    r = (versions.get(base) or {}).get("round")
    return next((b for b in rows if b["round"] == r and not b.get("assure")), None)


def contrib_md(d: dict[str, Any], title: str) -> str:
    """One markdown table: the identity, term by term."""
    head = (f"**{title}** — overall avg std moved {d['d_overall']:+.3f} "
            f"(noise floor ±{d['floor']:.3f}; {d['beyond_floor']}/{len(d['metrics'])} metrics beyond it)\n\n"
            "| metric | from | to | Δ metric | contribution | share | churn | by variance | vs noise |\n"
            "|---|---|---|---|---|---|---|---|---|")
    body = []
    for x in d["metrics"]:
        sh = "n/a" if x["share"] is None else f"{x['share']:.0f}%"
        gr = "n/a" if x["gross"] is None else f"{x['gross']:.0f}%"
        vs = "n/a" if x["var_share"] is None else f"{x['var_share']:.0f}%"
        body.append(f"| {x['metric']} | {x['from']:.3f} | {x['to']:.3f} | {x['delta']:+.3f} | "
                    f"{x['contribution']:+.3f} | {sh} | {gr} | {vs} | {x['verdict']} |")
    body.append(f"| **sum** | | | {sum(x['delta'] for x in d['metrics']):+.3f} | **{d['sum_contributions']:+.3f}** | 100% | 100% | 100% | |")
    note = f"\n\nresidual vs the reported aggregate: {d['residual']:+.5f}"
    if d["rank_flip"]:
        note += (f"  \n⚠ variance-based ranking differs ({' < '.join(d['rank_by_var'])}) — mean-of-std is not "
                 "variance-additive, so treat the std ordering as the weaker claim.")
    if abs(d["d_overall"]) < d["floor"]:
        note += "  \n⚠ the overall move is inside the noise floor: attributing it to any metric is over-reading."
    return head + "\n" + "\n".join(body) + note


def compression_md(rows: list[dict[str, Any]], title: str) -> str:
    head = (f"**{title}** — is the drop agreement or a shrinking scale? within/between = sqrt((1-ICC)/ICC) "
            "is scale-free.\n\n| metric | Δ mean score | Δ within-std | within/between | → | Δ | reading |\n|---|---|---|---|---|---|---|")
    body = [f"| {x['metric']} | {x['d_mean']:+.2f} | {x['d_within']:+.3f} | {x['wb_from']:.4f} | "
            f"{x['wb_to']:.4f} | {x['d_wb']:+.4f} | {x['verdict']} |" for x in rows]
    return head + "\n" + "\n".join(body)


def report(trend: list[dict[str, Any]], versions: dict[str, Any], metrics: list[str], n: int = 0) -> str:
    """Full attribution for a finished or in-flight run: every round against its parent,
    then the cumulative baseline → best, then the compression check on that span."""
    rows = _rows(trend)
    if len(rows) < 2:
        return "(need at least two scored rounds before anything can be attributed)"
    nf = noise_floor(trend, metrics, n)
    out = [f"## Per-metric contribution to the overall std\n",
           f"Overall avg std is the unweighted mean of the {len(metrics)} per-metric std, so the split below is an "
           f"identity, not a model: each metric carries weight 1/{len(metrics)} and the contributions sum to the "
           f"overall move exactly.\n",
           f"Noise floor: **±{nf['floor']:.3f}** per metric, from {nf['source']}."
           + (f" {nf['n_deltas']} deltas over {len(nf['pairs'])} re-score pair(s) "
              f"({', '.join(f'{v} r{a}↔r{b}' for v, a, b in nf['pairs'])}), largest |Δ| {nf['max']:.3f}."
              if nf["pairs"] else " No assurance round yet, so this is a lower bound only.")
           + (f" With only {nf['n_deltas']} deltas the floor is itself uncertain to roughly "
              f"±{nf['floor'] / math.sqrt(2 * nf['n_deltas']):.3f}, so treat it as an order of magnitude, "
              "not a threshold to test against." if 0 < nf["n_deltas"] < 20 else "") + "\n"]
    for row in rows:
        base = parent(versions, trend, row)
        if base is None:
            continue
        kept = "kept" if row.get("kept") else "rejected"
        what = (f"round {row['round']}: re-score of {row['version']} vs its own round {base['round']}"
                if row.get("assure") else
                f"round {row['round']}: {row['version']} vs parent {(versions.get(row['version']) or {}).get('base')} [{kept}]")
        out.append(contrib_md(decompose(row, base, metrics, nf["floor"]), what) + "\n")
    first = rows[0]
    best = next((r for r in reversed(rows) if r.get("assure")), None) or next(
        (r for r in reversed(rows) if r.get("kept")), rows[-1])
    if best is not first:
        out.append(contrib_md(decompose(best, first, metrics, nf["floor"]),
                              f"cumulative: {first['version']} (round {first['round']}) → {best['version']} (round {best['round']})") + "\n")
        out.append(compression_md(compression(best, first, metrics),
                                  f"cumulative: {first['version']} → {best['version']}") + "\n")
    return "\n".join(out)
