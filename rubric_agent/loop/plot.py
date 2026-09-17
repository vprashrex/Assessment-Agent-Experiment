"""One grid per consistency metric (first panel = all metrics, then one per metric; x = run; filled = kept):
trend_stable.png, trend_std.png, trend_flips.png, trend_icc.png, trend_var.png. rows.png: per-submission std heatmap."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from ..core.runio import Run  # noqa: E402

INK, MUTED, GRID = "#1F2937", "#6B7280", "#E5E7EB"
PALETTE = ["#2563EB", "#DC6803", "#059669", "#7C3AED", "#DB2777", "#0891B2", "#CA8A04", "#4B5563"]
GRAPHS = {  # key: (file, title, y label, fixed y range or None, all-metrics aggregation)
    "stable_pct": ("trend_stable.png", "stable rows % — k scores within one adjacent value (higher = consistent)", "stable rows %", (0, 100)),
    "within": ("trend_std.png", "avg per-submission std of k scores (lower = consistent)", "avg std-dev", None),
    "severe": ("trend_flips.png", "severe flips — submissions whose k scores span 2+ points (lower = consistent)", "submissions", None),
    "icc": ("trend_icc.png", "ICC — between-submission variance / total (must stay high; a fall = collapse)", "ICC", (0, 1)),
    "var": ("trend_var.png", "avg per-submission variance of k scores (lower = consistent)", "avg variance", None),
}


def _style(ax, x):
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.set_xticks(x)
    ax.set_xlabel("run (round)", fontsize=9, color=MUTED)


def plot_metric(run: Run, key: str) -> Path:
    file, title, ylabel, yrange = GRAPHS[key]
    rows, metrics = run.json("trend.json", []), run.metrics
    cols = ["all metrics"] + metrics
    x = [r["round"] for r in rows]
    series = [[r.get(key, 0) for r in rows]] + [[r["per_metric"][m].get(key, 0) for r in rows] for m in metrics]
    ymax_all = yrange[1] if yrange else max(max(series[0]), 0.1) * 1.25
    ymax = yrange[1] if yrange else max(max(max(s) for s in series[1:]), 0.1) * 1.25
    fig, axes = plt.subplots(1, len(cols), figsize=(2.9 * len(cols), 3.8), squeeze=False)
    for j, (ax, name, y) in enumerate(zip(axes[0], cols, series)):
        color = INK if j == 0 else PALETTE[(j - 1) % len(PALETTE)]
        ax.plot(x, y, color=color, linewidth=2.4 if j == 0 else 1.8, zorder=2)
        for a, b, r in zip(x, y, rows):
            ax.plot(a, b, marker="o", markersize=7, color=color, markerfacecolor=color if r.get("kept") else "white", markeredgewidth=2, zorder=3)
        ax.annotate(f"{y[-1]:g}", (x[-1], y[-1]), textcoords="offset points", xytext=(6, 0), va="center", fontsize=9, color=INK)
        ax.set_ylim(0, ymax if j else ymax_all)
        ax.set_title(name + (" (sum)" if j == 0 and key == "severe" else " (avg)" if j == 0 else ""), fontsize=10, color=INK, loc="left",
                     fontweight="bold" if j == 0 else "normal")
        _style(ax, x)
        if j == 0:
            ax.set_ylabel(ylabel, fontsize=9, color=MUTED)
    fig.suptitle(f"{run.dir.name}: {title}", fontsize=11, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    out = run.dir / file
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def plot_rows(run: Run) -> Path:
    metrics = run.metrics
    rounds = sorted(int(p.stem.split("_")[1]) for p in (run.dir / "stats").glob("round_*.json"))
    per_round = {r: next(iter(run.json(f"stats/round_{r}.json", {}).values()))["rows"] for r in rounds}
    cids = sorted(per_round[rounds[-1]], key=lambda c: -sum(per_round[rounds[-1]][c]["metrics"][m]["std"] or 0 for m in metrics))
    fig, axes = plt.subplots(1, len(metrics), figsize=(2.4 * len(metrics), max(4, min(14, 0.08 * len(cids)))), squeeze=False)
    for j, m in enumerate(metrics):
        grid = [[per_round[r].get(c, {}).get("metrics", {}).get(m, {}).get("std") or 0 for r in rounds] for c in cids]
        ax = axes[0][j]
        im = ax.imshow(grid, aspect="auto", cmap="Blues", vmin=0, vmax=2, interpolation="nearest")
        ax.set_title(m, fontsize=10, color=INK, loc="left")
        ax.set_xticks(range(len(rounds)))
        ax.set_xticklabels(rounds, fontsize=8, color=MUTED)
        ax.set_yticks([])
        ax.set_xlabel("run", fontsize=8, color=MUTED)
    fig.colorbar(im, ax=axes[0].tolist(), shrink=0.6, label="std of k scores")
    fig.suptitle(f"{run.dir.name}: per-submission std, rows sorted by latest instability", fontsize=10, color=INK, x=0.01, ha="left")
    out = run.dir / "rows.png"
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_all(run_dir: Path) -> list[Path]:
    run = Run(str(run_dir))
    return [plot_metric(run, k) for k in GRAPHS] + [plot_rows(run)]
