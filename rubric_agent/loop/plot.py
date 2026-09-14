"""Trend plot: small multiples, one column per metric, three rows sharing only the x axis (round):
ICC (separation vs noise, higher better), within-run std (consistency, lower better), Judge disagree %
(quality, lower better). Filled marker = version KEPT, hollow = NOT KEPT. One hue; text in ink."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from ..core.runio import Run  # noqa: E402

INK, MUTED, GRID, LINE = "#1F2937", "#6B7280", "#E5E7EB", "#2563EB"
ROWS = [("icc", "ICC (higher = better)", (0, 1)), ("within", "within-run std (lower = better)", None), ("disagree", "Judge disagree % (lower = better)", (0, 100))]


def plot_trend(run_dir: Path) -> Path:
    run = Run(str(run_dir))
    rows, metrics = run.json("trend.json", []), run.metrics
    fig, axes = plt.subplots(len(ROWS), len(metrics), figsize=(3.1 * len(metrics), 7.2), sharex=True, squeeze=False)
    x = [r["round"] for r in rows]
    within_max = max([r["per_metric"][m]["within"] or 0 for r in rows for m in metrics] + [0.5]) * 1.25
    for j, m in enumerate(metrics):
        for i, (key, label, lim) in enumerate(ROWS):
            ax = axes[i][j]
            pts = [(r["round"], r["per_metric"][m].get(key), r.get("kept")) for r in rows if r["per_metric"][m].get(key) is not None]
            if pts:
                ax.plot([p[0] for p in pts], [p[1] for p in pts], color=LINE, linewidth=2, zorder=2)
                for a, b, kept in pts:
                    ax.plot(a, b, marker="o", markersize=8, color=LINE, markerfacecolor=LINE if kept else "white", markeredgewidth=2, zorder=3)
                ax.annotate(f"{pts[-1][1]:g}", (pts[-1][0], pts[-1][1]), textcoords="offset points", xytext=(6, 0), va="center", fontsize=9, color=INK)
            ax.set_ylim(*(lim or (0, within_max)))
            ax.grid(axis="y", color=GRID, linewidth=0.8)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
            for side in ("left", "bottom"):
                ax.spines[side].set_color(GRID)
            ax.tick_params(colors=MUTED, labelsize=8)
            ax.set_xticks(x)
            if i == 0:
                ax.set_title(m, fontsize=11, color=INK, loc="left")
            if j == 0:
                ax.set_ylabel(label, fontsize=9, color=MUTED)
            if i == len(ROWS) - 1:
                ax.set_xlabel("round", fontsize=9, color=MUTED)
    fig.suptitle(f"{run_dir.name}: filled = kept, hollow = not kept", fontsize=11, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    out = run_dir / "trend.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out
