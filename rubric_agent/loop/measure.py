"""Plain-code measurement over k-run scores: per-row mean/std, per-metric within/between std and ICC,
score distribution, Judge disagreement, rank concordance, trend table."""

from __future__ import annotations

import math
import random
from collections import Counter
from typing import Any

from ..core.runio import Run


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def std(xs: list[float]) -> float | None:
    if len(xs) < 2:
        return 0.0 if xs else None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def row_stats(scores: dict[str, dict[str, Any]], metrics: list[str]) -> dict[str, dict[str, Any]]:
    """Per row: per metric {values, mean, std, mode, n_fail}; failed runs excluded from values, counted."""
    out: dict[str, dict[str, Any]] = {}
    for cid, rec in scores.items():
        runs = rec["runs"]
        ok = [r["scores"] for r in runs if r.get("scores")]
        out[cid] = {"n_fail": len(runs) - len(ok), "metrics": {}}
        for m in metrics:
            vals = [s[m] for s in ok]
            out[cid]["metrics"][m] = {"values": vals, "mean": mean(vals), "std": std(vals),
                                      "mode": Counter(vals).most_common(1)[0][0] if vals else None}
    return out


def metric_stats(rows: dict[str, dict[str, Any]], metrics: list[str], lo: int, hi: int) -> dict[str, Any]:
    """Per metric: within-row std (consistency), between-row std (discrimination), ICC, unstable rows, distribution."""
    out: dict[str, Any] = {}
    for m in metrics:
        per = [(cid, r["metrics"][m]) for cid, r in rows.items() if r["metrics"][m]["mean"] is not None]
        within = mean([x["std"] for _, x in per]) or 0.0
        between = std([x["mean"] for _, x in per]) or 0.0
        icc = between**2 / (between**2 + within**2) if (between or within) else 0.0
        dist = Counter(v for _, x in per for v in x["values"])
        n = sum(dist.values()) or 1
        top = dist.most_common(1)[0] if dist else (None, 0)
        out[m] = {"within_std": round(within, 3), "between_std": round(between, 3), "icc": round(icc, 3),
                  "unstable": sorted((cid for cid, x in per if x["std"] and x["std"] > 1.0), key=lambda c: -rows[c]["metrics"][m]["std"]),
                  "counts": {str(v): dist.get(v, 0) for v in range(lo, hi + 1)},
                  "unused": [v for v in range(lo, hi + 1) if dist.get(v, 0) == 0],
                  "pileup": f"{top[0]} ({100 * top[1] // n}%)" if top[1] / n > 0.4 else None}
    out["_icc_mean"] = round(mean([out[m]["icc"] for m in metrics]) or 0.0, 3)
    out["_within_mean"] = round(mean([out[m]["within_std"] for m in metrics]) or 0.0, 3)
    out["_fail_rate"] = round(sum(r["n_fail"] for r in rows.values()) / max(1, sum(len(r["metrics"]) and 1 for r in rows.values())), 3)
    return out


def icc_bootstrap_se(rows: dict[str, dict[str, Any]], metrics: list[str], lo: int, hi: int, b: int = 200) -> float:
    """SE of the mean ICC under resampling rows: the noise band a candidate must beat."""
    cids = list(rows)
    if len(cids) < 3:
        return float("inf")
    rnd = random.Random(0)
    vals = []
    for _ in range(b):
        pick = {c: rows[c] for c in rnd.choices(cids, k=len(cids))}
        vals.append(metric_stats(pick, metrics, lo, hi)["_icc_mean"])
    return std(vals) or 0.0


def disagreement(review_rows: list[dict[str, Any]], metrics: list[str]) -> dict[str, float]:
    """Judge disagree % per metric and overall from review verdicts."""
    out = {}
    for m in metrics:
        v = [r for r in review_rows if r["metric"] == m]
        out[m] = round(100 * sum(1 for r in v if not r["agree"]) / len(v), 1) if v else float("nan")
    out["_overall"] = round(100 * sum(1 for r in review_rows if not r["agree"]) / len(review_rows), 1) if review_rows else float("nan")
    return out


def concordance(order: list[str], rows: dict[str, dict[str, Any]], m: str) -> float | None:
    """Kendall tau between the Judge's best->worst order and the scorer's mean scores (1 = same order)."""
    ids = [c for c in order if c in rows and rows[c]["metrics"][m]["mean"] is not None]
    if len(ids) < 3:
        return None
    s = 0
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            d = rows[ids[i]]["metrics"][m]["mean"] - rows[ids[j]]["metrics"][m]["mean"]
            s += (d > 0) - (d < 0)
    return round(s / (len(ids) * (len(ids) - 1) / 2), 2)


def trend_row(run: Run, rnd: int, version: str, ms: dict[str, Any], dis: dict[str, float], rows: dict[str, dict[str, Any]],
              metrics: list[str], **extra: Any) -> dict[str, Any]:
    row = {"round": rnd, "version": version, "icc": ms["_icc_mean"], "within": ms["_within_mean"], "disagree": dis.get("_overall"),
           "per_metric": {m: {"icc": ms[m]["icc"], "within": ms[m]["within_std"], "disagree": dis.get(m),
                              "mean": round(mean([r["metrics"][m]["mean"] for r in rows.values() if r["metrics"][m]["mean"] is not None]) or 0, 2)}
                          for m in metrics}, **extra}
    rows_ = run.json("trend.json", [])
    rows_.append(row)
    run.write("trend.json", rows_)
    return row


def trend_md(rows: list[dict[str, Any]], metrics: list[str]) -> str:
    head = "| round | version | kept | ICC | within-std | disagree% | " + " | ".join(f"{m[:5]} icc/within/dis%" for m in metrics) + " |"
    out = [head, "|" + "---|" * (6 + len(metrics))]
    for r in rows:
        cells = [f"{r['per_metric'][m]['icc']}/{r['per_metric'][m]['within']}/{r['per_metric'][m]['disagree']}" for m in metrics]
        out.append(f"| {r['round']} | {r['version']} | {r.get('kept', '')} | {r['icc']} | {r['within']} | {r['disagree']} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def fmt(ms: dict[str, Any], dis: dict[str, float], metrics: list[str]) -> str:
    return " ".join(f"{m[:4]} icc {ms[m]['icc']:.2f} sd {ms[m]['within_std']:.2f} dis {dis.get(m, float('nan')):.0f}" for m in metrics)
