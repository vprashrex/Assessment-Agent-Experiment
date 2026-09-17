"""Consistency maths over k-run scores: per-row std, stable % (all k within one adjacent value), ICC, bootstrap SE, trend."""

from __future__ import annotations

import math
import random
from collections import Counter
from typing import Any

from ..core.config import SEVERE_RANGE, STABLE_RANGE


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def std(xs: list[float]) -> float | None:
    if not xs:
        return None
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def row_stats(scores: dict[str, dict[str, Any]], metrics: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for cid, rec in scores.items():
        ok = [r["scores"] for r in rec["runs"] if r.get("scores")]
        out[cid] = {"n_fail": len(rec["runs"]) - len(ok), "n": len(rec["runs"]), "metrics": {}}
        for m in metrics:
            vals = [s[m] for s in ok]
            sd = std(vals)
            out[cid]["metrics"][m] = {"values": vals, "mean": mean(vals), "std": sd, "range": (max(vals) - min(vals)) if vals else None,
                                      "stable": bool(vals) and max(vals) - min(vals) <= STABLE_RANGE and len(vals) == len(rec["runs"])}
    return out


def metric_stats(rows: dict[str, dict[str, Any]], metrics: list[str], lo: int, hi: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for m in metrics:
        per = [(cid, r["metrics"][m]) for cid, r in rows.items() if r["metrics"][m]["mean"] is not None]
        within = mean([x["std"] for _, x in per]) or 0.0
        between = std([x["mean"] for _, x in per]) or 0.0
        dist = Counter(v for _, x in per for v in x["values"])
        n = sum(dist.values()) or 1
        top = dist.most_common(1)[0] if dist else (None, 0)
        var = mean([(x["std"] or 0) ** 2 for _, x in per]) or 0.0
        out[m] = {"within_std": round(within, 3), "within_var": round(var, 3), "between_std": round(between, 3),
                  "icc": round(between**2 / (between**2 + within**2), 3) if (between or within) else 0.0,
                  "stable_pct": round(100 * sum(1 for _, x in per if x["stable"]) / max(1, len(rows)), 1),
                  "severe": sum(1 for _, x in per if (x["range"] or 0) >= SEVERE_RANGE),
                  "severe_rows": [cid for cid, x in per if (x["range"] or 0) >= SEVERE_RANGE],
                  "unstable": sorted((cid for cid, x in per if not x["stable"]), key=lambda c: -(rows[c]["metrics"][m]["std"] or 9)),
                  "counts": {str(v): dist.get(v, 0) for v in range(lo, hi + 1)},
                  "unused": [v for v in range(lo, hi + 1) if dist.get(v, 0) == 0],
                  "pileup": f"{top[0]} ({100 * top[1] // n}%)" if top[1] / n > 0.4 else None}
    out["_icc"] = round(mean([out[m]["icc"] for m in metrics]) or 0.0, 3)
    out["_within"] = round(mean([out[m]["within_std"] for m in metrics]) or 0.0, 3)
    out["_var"] = round(mean([out[m]["within_var"] for m in metrics]) or 0.0, 3)
    out["_stable_pct"] = round(mean([out[m]["stable_pct"] for m in metrics]) or 0.0, 1)
    out["_severe"] = sum(out[m]["severe"] for m in metrics)
    out["_fail_rate"] = round(sum(r["n_fail"] for r in rows.values()) / max(1, sum(r["n"] for r in rows.values())), 3)
    return out


def bootstrap_se(rows: dict[str, dict[str, Any]], metrics: list[str], lo: int, hi: int, b: int = 150) -> dict[str, float]:
    cids = list(rows)
    if len(cids) < 3:
        return {"_icc": float("inf"), "_within": float("inf"), "_stable_pct": float("inf"), "_severe": float("inf")}
    rnd = random.Random(0)
    samples = {"_icc": [], "_within": [], "_stable_pct": [], "_severe": []}
    for _ in range(b):
        pick = rnd.choices(cids, k=len(cids))
        ms = metric_stats({f"{c}#{i}": rows[c] for i, c in enumerate(pick)}, metrics, lo, hi)
        for key in samples:
            samples[key].append(ms[key])
    return {k: round(std(v) or 0.0, 4) for k, v in samples.items()}


def row_deltas(cur: dict[str, dict[str, Any]], prev: dict[str, dict[str, Any]], metrics: list[str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for cid, r in cur.items():
        if cid not in prev:
            continue
        d = {m: round((r["metrics"][m]["std"] or 0) - (prev[cid]["metrics"][m]["std"] or 0), 2) for m in metrics
             if r["metrics"][m]["std"] is not None and prev[cid]["metrics"][m]["std"] is not None}
        if d:
            out[cid] = d
    return out


def trend_row(run, rnd: int, version: str, ms: dict[str, Any], rows: dict[str, dict[str, Any]], metrics: list[str], **extra: Any) -> dict[str, Any]:
    row = {"round": rnd, "version": version, "icc": ms["_icc"], "within": ms["_within"], "var": ms["_var"], "stable_pct": ms["_stable_pct"],
           "severe": ms["_severe"],
           "per_metric": {m: {"icc": ms[m]["icc"], "within": ms[m]["within_std"], "var": ms[m]["within_var"], "stable_pct": ms[m]["stable_pct"], "severe": ms[m]["severe"],
                              "mean": round(mean([r["metrics"][m]["mean"] for r in rows.values() if r["metrics"][m]["mean"] is not None]) or 0, 2)}
                          for m in metrics}, **extra}
    rows_ = run.json("trend.json", [])
    rows_.append(row)
    run.write("trend.json", rows_)
    return row


def trend_md(rows: list[dict[str, Any]], metrics: list[str]) -> str:
    head = "| round | version | kept | stable% | avg std | severe flips | ICC | " + " | ".join(f"{m[:6]} stable%/std/flips/icc" for m in metrics) + " |"
    out = [head, "|" + "---|" * (7 + len(metrics))]
    for r in rows:
        cells = [f"{r['per_metric'][m]['stable_pct']}/{r['per_metric'][m]['within']}/{r['per_metric'][m].get('severe', '')}/{r['per_metric'][m]['icc']}" for m in metrics]
        out.append(f"| {r['round']} | {r['version']} | {r.get('kept', '')} | {r['stable_pct']} | {r['within']} | {r.get('severe', '')} | {r['icc']} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def fmt(ms: dict[str, Any], metrics: list[str]) -> str:
    return " ".join(f"{m[:4]} st {ms[m]['stable_pct']:.0f}% sd {ms[m]['within_std']:.2f} fl {ms[m]['severe']} icc {ms[m]['icc']:.2f}" for m in metrics)
