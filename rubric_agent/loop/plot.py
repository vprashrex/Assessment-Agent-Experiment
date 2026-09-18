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


def plot_contrib(run: Run) -> Path:
    """trend_contrib.png — who moved the overall std, round by round.

    Contributions are signed and sum exactly to the overall move, so the honest form is a
    diverging stacked bar: each metric's Δ/M stacked upward if it made things worse and downward
    if it made things better, with the net marked on top. Reading the net off the stack is the
    point — a short net bar sitting between tall opposing stacks is a revision that traded one
    metric against another rather than improving anything.
    """
    from .contrib import noise_floor, parent  # local: contrib imports nothing from plot

    metrics = run.metrics
    trend, versions = run.json("trend.json", []), run.json("versions.json", {})
    rows = [t for t in trend if t.get("per_metric")]
    pairs = [(t, parent(versions, trend, t)) for t in rows]
    pairs = [(t, b) for t, b in pairs if b is not None]
    if not pairs:
        fig, ax = plt.subplots(figsize=(7, 3))
        ax.text(0.5, 0.5, "no comparable rounds yet", ha="center", va="center", color=MUTED)
        ax.axis("off")
        out = run.dir / "trend_contrib.png"
        fig.savefig(out, dpi=150)
        plt.close(fig)
        return out
    floor = noise_floor(trend, metrics).get("floor") or 0.0
    M = len(metrics)
    x = list(range(len(pairs)))
    fig, ax = plt.subplots(figsize=(max(7.0, 1.5 * len(pairs) + 3.2), 4.6))
    # The floor band is labelled in the legend, not annotated in the plot area: with bars on both
    # sides of zero there is no corner in the axes that is reliably free of a bar or a value label.
    band = None
    if floor:
        band = ax.axhspan(-floor, floor, color=GRID, alpha=0.55, zorder=0,
                          label=f"±{floor:.3f} re-score noise floor")
    up = [0.0] * len(pairs)
    dn = [0.0] * len(pairs)
    for j, m in enumerate(metrics):
        col = PALETTE[j % len(PALETTE)]
        vals = [(t["per_metric"][m]["within"] - b["per_metric"][m]["within"]) / M for t, b in pairs]
        bot = [up[i] if v >= 0 else dn[i] for i, v in enumerate(vals)]
        # 2px surface gap between stacked segments, so adjacent hues never touch
        ax.bar(x, vals, bottom=bot, width=0.62, color=col, label=m, zorder=2, linewidth=1.2, edgecolor="white")
        for i, v in enumerate(vals):
            if v >= 0:
                up[i] += v
            else:
                dn[i] += v
    net = [t["within"] - b["within"] for t, b in pairs]
    ax.plot(x, net, marker="D", markersize=7, linestyle="none", color=INK, zorder=4,
            markeredgecolor="white", markeredgewidth=1.4, label="net (sum of contributions)")
    for i, v in enumerate(net):
        ax.annotate(f"{v:+.3f}", (x[i], v), textcoords="offset points", xytext=(0, 11 if v >= 0 else -17),
                    ha="center", fontsize=8.5, color=INK, fontweight="bold", zorder=5)
    ax.axhline(0, color="#C3C2B7", linewidth=1.2, zorder=1)
    ax.set_xlim(-0.72, len(pairs) - 0.28)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{t['version']}\n{'recheck' if t.get('assure') else 'kept' if t.get('kept') else 'rejected'}"
                        for t, _ in pairs], fontsize=9, color=MUTED)
    ax.set_ylabel("contribution to overall avg std  (Δ ÷ %d)" % M, fontsize=9, color=MUTED)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    h, la = ax.get_legend_handles_labels()
    if band is not None:  # band last: it is context, the metrics are the subject
        h, la = [e for e in h if e is not band], [e for e in la if not e.startswith("±")]
        h.append(band)
        la.append(f"±{floor:.3f} re-score noise floor")
    ax.legend(h, la, fontsize=8.5, frameon=False, ncol=3, loc="upper left", bbox_to_anchor=(0, -0.13))
    fig.suptitle(f"{run.dir.name}: which metric moved the overall std (below 0 = made it more consistent)",
                 fontsize=11, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    out = run.dir / "trend_contrib.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_all(run_dir: Path) -> list[Path]:
    run = Run(str(run_dir))
    return [plot_metric(run, k) for k in GRAPHS] + [plot_rows(run), plot_contrib(run)]
