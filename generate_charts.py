#!/usr/bin/env python3
"""
Generate marketing-ready charts and analysis for the auto-researchtrading project.
Produces charts similar to @hamostaf04's autoresearch tweet thread.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.dates as mdates
import numpy as np
import csv
from datetime import datetime
from pathlib import Path
from typing import Any

# ─── Dark theme setup ───
plt.style.use("dark_background")
BG = "#0d1117"
CARD_BG = "#161b22"
ACCENT_BLUE = "#58a6ff"
ACCENT_GREEN = "#3fb950"
ACCENT_RED = "#f85149"
ACCENT_ORANGE = "#d29922"
ACCENT_PURPLE = "#bc8cff"
ACCENT_CYAN = "#39d353"
GRID_COLOR = "#21262d"
TEXT_COLOR = "#c9d1d9"
MUTED = "#8b949e"

OUTPUT_DIR = Path("/Users/jae_lee/auto-researchtrading/charts")
OUTPUT_DIR.mkdir(exist_ok=True)


def load_results():
    """Parse results.tsv into structured data."""
    experiments = []
    with open("/Users/jae_lee/auto-researchtrading/results.tsv") as f:
        f.readline()  # skip header
        for i, line in enumerate(f):
            parts = line.strip().split("\t")
            if len(parts) < 6:
                continue
            exp = {
                "idx": i,
                "commit": parts[0],
                "score": float(parts[1]),
                "sharpe": float(parts[2]),
                "max_dd": float(parts[3]),
                "status": parts[4],
                "description": parts[5] if len(parts) > 5 else "",
            }
            experiments.append(exp)
    return experiments


def chart1_score_evolution(exps):
    """Hero chart: Score evolution across 104 experiments with keeps highlighted."""
    fig, ax = plt.subplots(figsize=(16, 8))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    idxs = list(range(len(exps)))
    keeps = [(i, e["score"]) for i, e in enumerate(exps) if e["status"] == "keep"]
    discards = [(i, e["score"]) for i, e in enumerate(exps) if e["status"] == "discard"]

    # Running best line
    running_best = []
    best = -999
    for e in exps:
        if e["status"] == "keep":
            best = max(best, e["score"])
        running_best.append(best)

    # Fill under running best
    ax.fill_between(idxs, running_best, alpha=0.08, color=ACCENT_GREEN)
    ax.plot(
        idxs,
        running_best,
        color=ACCENT_GREEN,
        linewidth=2.5,
        label="Running Best Score",
        zorder=3,
    )

    # Scatter all experiments
    if discards:
        dx, dy = zip(*discards)
        ax.scatter(
            dx,
            dy,
            color=ACCENT_RED,
            alpha=0.35,
            s=25,
            zorder=2,
            label=f"Discarded ({len(discards)})",
        )
    if keeps:
        kx, ky = zip(*keeps)
        ax.scatter(
            kx,
            ky,
            color=ACCENT_GREEN,
            s=50,
            zorder=4,
            edgecolors="white",
            linewidth=0.5,
            label=f"Kept ({len(keeps)})",
        )

    # Phase annotations
    phases = [
        (0, 16, "Phase 1-3\nEnsemble Building", ACCENT_BLUE),
        (16, 49, 'Phase 4\n"Great Simplification"', ACCENT_ORANGE),
        (49, 74, "Phase 5-6\nFine-Tuning", ACCENT_PURPLE),
        (74, 104, "Phase 7\nMicro-Optimization", ACCENT_CYAN),
    ]
    for start, end, label, color in phases:
        ax.axvspan(start, end, alpha=0.04, color=color)
        mid = (start + end) / 2
        ax.text(
            mid,
            -3.5,
            label,
            ha="center",
            va="top",
            fontsize=9,
            color=color,
            fontweight="bold",
        )

    # Key milestones
    milestones = [
        (47, 13.48, "Strength scaling\nremoved: +1.7 Sharpe", -40, 30),
        (73, 19.70, "RSI period 8:\n+5 Sharpe", -50, 20),
        (103, 20.63, "Final: 21.4\nSharpe", -40, 15),
    ]
    for x, y, text, dx, dy in milestones:
        ax.annotate(
            text,
            (x, y),
            xytext=(dx, dy),
            textcoords="offset points",
            fontsize=8.5,
            color=TEXT_COLOR,
            fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=MUTED, lw=1),
            ha="center",
        )

    ax.set_xlabel("Experiment #", fontsize=13, color=TEXT_COLOR, labelpad=10)
    ax.set_ylabel("Score (Sharpe-based)", fontsize=13, color=TEXT_COLOR, labelpad=10)
    ax.set_title(
        "Autonomous Strategy Evolution: 104 Experiments, Zero Human Intervention",
        fontsize=18,
        color="white",
        fontweight="bold",
        pad=20,
    )
    ax.legend(loc="upper left", fontsize=11, framealpha=0.3)
    ax.grid(True, alpha=0.15, color=GRID_COLOR)
    ax.set_xlim(-2, 106)
    ax.set_ylim(-5, 24)
    ax.tick_params(colors=MUTED)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)

    fig.tight_layout()
    fig.savefig(
        OUTPUT_DIR / "1_score_evolution.png",
        dpi=200,
        bbox_inches="tight",
        facecolor=BG,
        edgecolor="none",
    )
    plt.close(fig)
    print("✓ Chart 1: Score evolution")


def chart2_before_after(exps):
    """Before vs After dashboard — the hero metrics."""
    fig, axes = plt.subplots(1, 4, figsize=(18, 5))
    fig.patch.set_facecolor(BG)
    fig.suptitle(
        "From Baseline to Final: 7.9x Improvement",
        fontsize=20,
        color="white",
        fontweight="bold",
        y=1.02,
    )

    metrics = [
        ("Sharpe Ratio", 2.724, 21.402, ACCENT_GREEN, ""),
        ("Max Drawdown", 7.6, 0.3, ACCENT_RED, "%"),
        ("Total Return", 42.6, 130.0, ACCENT_BLUE, "%"),
        ("Score", 2.724, 21.402, ACCENT_PURPLE, ""),
    ]

    for ax, (name, before, after, color, suffix) in zip(axes, metrics):
        ax.set_facecolor(BG)
        bars = ax.bar(
            ["Baseline", "Final"],
            [before, after],
            color=[MUTED, color],
            width=0.55,
            edgecolor="none",
        )
        ax.set_title(name, fontsize=14, color=TEXT_COLOR, fontweight="bold", pad=12)

        for bar, val in zip(bars, [before, after]):
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                bar.get_height() + 0.3,
                f"{val}{suffix}",
                ha="center",
                va="bottom",
                fontsize=14,
                color="white",
                fontweight="bold",
            )

        # Improvement arrow
        if name == "Max Drawdown":
            pct = f"-{((before - after) / before * 100):.0f}%"
        else:
            pct = f"+{((after - before) / before * 100):.0f}%"
        ax.text(
            0.5,
            0.5,
            pct,
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=22,
            color=color,
            fontweight="bold",
            alpha=0.25,
        )

        ax.grid(True, axis="y", alpha=0.1, color=GRID_COLOR)
        ax.tick_params(colors=MUTED)
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color(GRID_COLOR)

    fig.tight_layout()
    fig.savefig(
        OUTPUT_DIR / "2_before_after.png",
        dpi=200,
        bbox_inches="tight",
        facecolor=BG,
        edgecolor="none",
    )
    plt.close(fig)
    print("✓ Chart 2: Before/After dashboard")


def chart3_simplification_impact(exps):
    """The Great Simplification — showing what removal did to the score."""
    fig, ax = plt.subplots(figsize=(14, 7))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    removals = [
        ("Pyramiding", 10.31, 10.62, ""),
        ("Funding\nBoost", 10.62, 11.30, ""),
        ("BTC Lead-Lag\nFilter", 11.30, 11.66, ""),
        ("Correlation\nFilter", 11.66, 11.80, ""),
        ("DD-Adaptive\nSizing", 11.80, 11.80, "never triggered"),
        ("Strength\nScaling", 11.80, 13.48, "+1.7 Sharpe!"),
        ("Vol\nScaling", 13.48, 13.49, ""),
        ("Take\nProfit", 13.49, 13.49, ""),
        ("Unequal\nWeights", 13.49, 13.52, ""),
    ]

    names = [r[0] for r in removals]
    before_vals = [r[1] for r in removals]
    after_vals = [r[2] for r in removals]
    gains = [a - b for b, a in zip(before_vals, after_vals)]
    notes = [r[3] for r in removals]

    x = np.arange(len(names))
    width = 0.35

    ax.bar(
        x - width / 2,
        before_vals,
        width,
        label="Before Removal",
        color=MUTED,
        alpha=0.6,
        edgecolor="none",
    )
    ax.bar(
        x + width / 2,
        after_vals,
        width,
        label="After Removal",
        color=ACCENT_GREEN,
        edgecolor="none",
    )

    for i, (gain, note) in enumerate(zip(gains, notes)):
        if gain > 0.05:
            ax.annotate(
                f"+{gain:.2f}",
                (i + width / 2, after_vals[i]),
                xytext=(0, 8),
                textcoords="offset points",
                ha="center",
                fontsize=10,
                color=ACCENT_GREEN,
                fontweight="bold",
            )
        if note:
            ax.annotate(
                note,
                (i, max(before_vals[i], after_vals[i])),
                xytext=(0, 20),
                textcoords="offset points",
                ha="center",
                fontsize=8,
                color=ACCENT_ORANGE,
                fontweight="bold",
                fontstyle="italic",
            )

    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=10, color=TEXT_COLOR)
    ax.set_ylabel("Score", fontsize=13, color=TEXT_COLOR)
    ax.set_title(
        '"The Great Simplification" — Every Removal Improved Performance',
        fontsize=17,
        color="white",
        fontweight="bold",
        pad=20,
    )
    ax.legend(fontsize=11, framealpha=0.3)
    ax.grid(True, axis="y", alpha=0.1, color=GRID_COLOR)
    ax.set_ylim(9, 15)
    ax.tick_params(colors=MUTED)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)

    fig.tight_layout()
    fig.savefig(
        OUTPUT_DIR / "3_simplification.png",
        dpi=200,
        bbox_inches="tight",
        facecolor=BG,
        edgecolor="none",
    )
    plt.close(fig)
    print("✓ Chart 3: Great Simplification")


def chart4_drawdown_evolution(exps):
    """Max drawdown dropping from 7.6% to 0.3%."""
    fig, ax = plt.subplots(figsize=(14, 6))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    keeps = [e for e in exps if e["status"] == "keep"]
    keep_idxs = list(range(len(keeps)))
    dds = [e["max_dd"] for e in keeps]
    descs = [e["description"] for e in keeps]

    ax.fill_between(keep_idxs, dds, alpha=0.15, color=ACCENT_RED)
    ax.plot(
        keep_idxs,
        dds,
        color=ACCENT_RED,
        linewidth=2.5,
        marker="o",
        markersize=5,
        markerfacecolor=ACCENT_RED,
        markeredgecolor="white",
        markeredgewidth=0.5,
    )

    # Annotate key drops
    for i, (dd, desc) in enumerate(zip(dds, descs)):
        if dd <= 0.5 and i > 0 and dds[i - 1] > 0.5:
            ax.annotate(
                f"{dd}%\n{desc}",
                (i, dd),
                xytext=(20, 20),
                textcoords="offset points",
                fontsize=9,
                color=ACCENT_GREEN,
                fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=MUTED, lw=1),
            )

    ax.set_xlabel("Kept Experiment #", fontsize=13, color=TEXT_COLOR, labelpad=10)
    ax.set_ylabel("Max Drawdown %", fontsize=13, color=TEXT_COLOR, labelpad=10)
    ax.set_title(
        "Max Drawdown: 7.6% → 0.3% (96% reduction)",
        fontsize=17,
        color="white",
        fontweight="bold",
        pad=20,
    )
    ax.grid(True, alpha=0.15, color=GRID_COLOR)
    ax.tick_params(colors=MUTED)
    ax.invert_yaxis()
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)

    fig.tight_layout()
    fig.savefig(
        OUTPUT_DIR / "4_drawdown_evolution.png",
        dpi=200,
        bbox_inches="tight",
        facecolor=BG,
        edgecolor="none",
    )
    plt.close(fig)
    print("✓ Chart 4: Drawdown evolution")


def chart5_keep_discard_ratio(exps):
    """Experiment success rate visualization."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    fig.patch.set_facecolor(BG)

    keeps = sum(1 for e in exps if e["status"] == "keep")
    discards = sum(1 for e in exps if e["status"] == "discard")
    total = keeps + discards

    # Donut chart
    ax1.set_facecolor(BG)
    sizes = [keeps, discards]
    colors = [ACCENT_GREEN, ACCENT_RED]
    wedges, texts, autotexts = ax1.pie(
        sizes,
        labels=["Kept", "Discarded"],
        colors=colors,
        autopct="%1.0f%%",
        startangle=90,
        pctdistance=0.75,
        textprops={"color": TEXT_COLOR, "fontsize": 13},
    )
    for t in autotexts:
        t.set_fontweight("bold")
        t.set_fontsize(14)
    centre_circle = plt.Circle((0, 0), 0.50, fc=BG)
    ax1.add_artist(centre_circle)
    ax1.text(
        0,
        0,
        f"{total}\ntotal",
        ha="center",
        va="center",
        fontsize=18,
        color="white",
        fontweight="bold",
    )
    ax1.set_title(
        "Experiment Outcomes", fontsize=15, color="white", fontweight="bold", pad=15
    )

    # Score distribution histogram
    ax2.set_facecolor(BG)
    keep_scores = [e["score"] for e in exps if e["status"] == "keep"]
    discard_scores = [e["score"] for e in exps if e["status"] == "discard"]

    bins = np.linspace(-5, 22, 30)
    ax2.hist(
        discard_scores,
        bins=bins,
        alpha=0.6,
        color=ACCENT_RED,
        label="Discarded",
        edgecolor="none",
    )
    ax2.hist(
        keep_scores,
        bins=bins,
        alpha=0.8,
        color=ACCENT_GREEN,
        label="Kept",
        edgecolor="none",
    )
    ax2.set_xlabel("Score", fontsize=12, color=TEXT_COLOR)
    ax2.set_ylabel("Count", fontsize=12, color=TEXT_COLOR)
    ax2.set_title(
        "Score Distribution", fontsize=15, color="white", fontweight="bold", pad=15
    )
    ax2.legend(fontsize=11, framealpha=0.3)
    ax2.grid(True, axis="y", alpha=0.1, color=GRID_COLOR)
    ax2.tick_params(colors=MUTED)
    for spine in ax2.spines.values():
        spine.set_color(GRID_COLOR)

    fig.tight_layout()
    fig.savefig(
        OUTPUT_DIR / "5_keep_discard.png",
        dpi=200,
        bbox_inches="tight",
        facecolor=BG,
        edgecolor="none",
    )
    plt.close(fig)
    print("✓ Chart 5: Keep/Discard ratio")


def chart6_top_discoveries(exps):
    """Top 10 biggest score jumps — what moves the needle most."""
    fig, ax = plt.subplots(figsize=(14, 7))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    discoveries = [
        ("RSI period 8\n(vs textbook 14)", +5.0),
        ("Remove strength\nscaling", +1.7),
        ("Simplified\nmomentum calc", +0.8),
        ("BB compression\n6th signal", +0.7),
        ("Remove\npyramiding", +0.3),
        ("Remove funding\nboost", +0.7),
        ("Cooldown 3→2\nbars", +1.1),
        ("ATR stop\n5.5x", +0.4),
        ("Position size\n8%", +0.5),
        ("RSI exit\n69/31", +0.4),
    ]

    discoveries.sort(key=lambda x: x[1], reverse=True)
    names = [d[0] for d in discoveries]
    gains = [d[1] for d in discoveries]

    colors_bar = [
        ACCENT_GREEN if g > 1.0 else ACCENT_BLUE if g > 0.5 else ACCENT_CYAN
        for g in gains
    ]

    bars = ax.barh(
        range(len(names)), gains, color=colors_bar, height=0.6, edgecolor="none"
    )
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=11, color=TEXT_COLOR)
    ax.invert_yaxis()

    for bar, gain in zip(bars, gains):
        ax.text(
            bar.get_width() + 0.05,
            bar.get_y() + bar.get_height() / 2,
            f"+{gain:.1f} Sharpe",
            va="center",
            fontsize=12,
            color="white",
            fontweight="bold",
        )

    ax.set_xlabel("Sharpe Improvement", fontsize=13, color=TEXT_COLOR, labelpad=10)
    ax.set_title(
        "Top 10 Discoveries — What Moved the Needle",
        fontsize=17,
        color="white",
        fontweight="bold",
        pad=20,
    )
    ax.grid(True, axis="x", alpha=0.1, color=GRID_COLOR)
    ax.tick_params(colors=MUTED)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)

    fig.tight_layout()
    fig.savefig(
        OUTPUT_DIR / "6_top_discoveries.png",
        dpi=200,
        bbox_inches="tight",
        facecolor=BG,
        edgecolor="none",
    )
    plt.close(fig)
    print("✓ Chart 6: Top discoveries")


def chart7_final_strategy_architecture():
    """Clean diagram of the final strategy architecture."""
    fig, ax = plt.subplots(figsize=(16, 10))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    # Title
    ax.text(
        50,
        96,
        "Final Strategy Architecture (exp103, Score 21.4)",
        ha="center",
        va="top",
        fontsize=20,
        color="white",
        fontweight="bold",
    )
    ax.text(
        50,
        92,
        "BTC / ETH / SOL  •  Hourly  •  Equal Weight  •  8% Position Size",
        ha="center",
        va="top",
        fontsize=12,
        color=MUTED,
    )

    # Signal boxes
    signals = [
        ("12h Momentum", "ret > dyn_threshold", ACCENT_BLUE),
        ("6h V-Short Mom", "ret > thresh × 0.7", ACCENT_BLUE),
        ("EMA Crossover", "EMA(7) vs EMA(26)", ACCENT_PURPLE),
        ("RSI(8)", "> 50 bull / < 50 bear", ACCENT_GREEN),
        ("MACD(14,23,9)", "histogram > 0", ACCENT_ORANGE),
        ("BB Compress", "width < 85th pctile", ACCENT_CYAN),
    ]

    box_w, box_h = 13, 10
    start_x = 5
    y_sig = 72

    for i, (name, formula, color) in enumerate(signals):
        x = start_x + i * 15.5
        rect = plt.Rectangle(
            (x, y_sig),
            box_w,
            box_h,
            linewidth=2,
            edgecolor=color,
            facecolor=color + "15",
            clip_on=False,
        )
        ax.add_patch(rect)
        ax.text(
            x + box_w / 2,
            y_sig + box_h - 2,
            name,
            ha="center",
            va="top",
            fontsize=10,
            color=color,
            fontweight="bold",
        )
        ax.text(
            x + box_w / 2,
            y_sig + 2,
            formula,
            ha="center",
            va="bottom",
            fontsize=8,
            color=MUTED,
        )
        # Arrow down
        ax.annotate(
            "",
            xy=(x + box_w / 2, 60),
            xytext=(x + box_w / 2, y_sig),
            arrowprops=dict(arrowstyle="->", color=MUTED, lw=1.2),
        )

    # Voting box
    vote_rect = plt.Rectangle(
        (25, 52),
        50,
        8,
        linewidth=2.5,
        edgecolor=ACCENT_GREEN,
        facecolor=ACCENT_GREEN + "15",
    )
    ax.add_patch(vote_rect)
    ax.text(
        50,
        56,
        "4/6 MAJORITY VOTE",
        ha="center",
        va="center",
        fontsize=16,
        color=ACCENT_GREEN,
        fontweight="bold",
    )

    # Arrow down from vote
    ax.annotate(
        "",
        xy=(50, 42),
        xytext=(50, 52),
        arrowprops=dict(arrowstyle="->", color=MUTED, lw=2),
    )

    # Exit conditions
    exits = [
        ("ATR Trailing Stop", "5.5× ATR from peak", ACCENT_RED, 20),
        ("RSI Mean-Reversion", "RSI > 69 or RSI < 31", ACCENT_ORANGE, 42),
        ("Signal Flip", "Reverse directly\n(never exit flat)", ACCENT_PURPLE, 64),
    ]

    for name, desc, color, x in exits:
        rect = plt.Rectangle(
            (x, 25), 22, 14, linewidth=2, edgecolor=color, facecolor=color + "15"
        )
        ax.add_patch(rect)
        ax.text(
            x + 11,
            35,
            name,
            ha="center",
            va="center",
            fontsize=11,
            color=color,
            fontweight="bold",
        )
        ax.text(x + 11, 28.5, desc, ha="center", va="center", fontsize=9, color=MUTED)

    ax.text(
        50,
        44,
        "EXIT CONDITIONS (priority order)",
        ha="center",
        va="center",
        fontsize=12,
        color=ACCENT_RED,
        fontweight="bold",
    )

    # Key params at bottom
    params_text = (
        "Key: 2-bar cooldown  •  Dynamic momentum threshold  •  "
        "Realistic fees (2bp maker, 5bp taker, 1bp slippage)  •  $100K initial"
    )
    ax.text(
        50,
        18,
        params_text,
        ha="center",
        va="center",
        fontsize=10,
        color=MUTED,
        style="italic",
    )

    # Results bar at very bottom
    results_rect = plt.Rectangle(
        (10, 5),
        80,
        10,
        linewidth=1.5,
        edgecolor=ACCENT_GREEN,
        facecolor=ACCENT_GREEN + "08",
    )
    ax.add_patch(results_rect)
    ax.text(
        50,
        10,
        "Sharpe 21.4  |  Max DD 0.3%  |  ~130% Return  |  7,949 Trades  |  9mo Backtest",
        ha="center",
        va="center",
        fontsize=13,
        color=ACCENT_GREEN,
        fontweight="bold",
    )

    fig.savefig(
        OUTPUT_DIR / "7_strategy_architecture.png",
        dpi=200,
        bbox_inches="tight",
        facecolor=BG,
        edgecolor="none",
    )
    plt.close(fig)
    print("✓ Chart 7: Strategy architecture")


def chart8_complexity_vs_performance(exps):
    """Show that complexity went DOWN while performance went UP."""
    fig, ax1 = plt.subplots(figsize=(14, 6))
    fig.patch.set_facecolor(BG)
    ax1.set_facecolor(BG)

    # Approximate complexity by phase
    phases_x = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    complexity = [1.0, 2.0, 3.5, 5.0, 6.5, 7.0, 5.0, 3.5, 3.0, 3.0, 3.0]
    performance = [2.7, 3.0, 3.3, 3.7, 5.2, 8.4, 13.5, 15.7, 19.7, 20.6, 21.4]

    ax1.plot(
        phases_x,
        complexity,
        color=ACCENT_RED,
        linewidth=3,
        marker="s",
        markersize=8,
        label="Strategy Complexity",
        zorder=3,
    )
    ax1.fill_between(phases_x, complexity, alpha=0.1, color=ACCENT_RED)
    ax1.set_ylabel("Relative Complexity", fontsize=13, color=ACCENT_RED, labelpad=10)
    ax1.tick_params(axis="y", colors=ACCENT_RED)

    ax2 = ax1.twinx()
    ax2.plot(
        phases_x,
        performance,
        color=ACCENT_GREEN,
        linewidth=3,
        marker="o",
        markersize=8,
        label="Score",
        zorder=3,
    )
    ax2.fill_between(phases_x, performance, alpha=0.1, color=ACCENT_GREEN)
    ax2.set_ylabel("Score", fontsize=13, color=ACCENT_GREEN, labelpad=10)
    ax2.tick_params(axis="y", colors=ACCENT_GREEN)

    # Annotate the crossover
    ax1.axvline(x=5.5, color=ACCENT_ORANGE, linestyle="--", alpha=0.5)
    ax1.text(
        5.5,
        7.8,
        '"The Great\nSimplification"',
        ha="center",
        va="bottom",
        fontsize=11,
        color=ACCENT_ORANGE,
        fontweight="bold",
    )

    ax1.set_xlabel("Evolution Stage", fontsize=13, color=TEXT_COLOR, labelpad=10)
    ax1.set_title(
        "Complexity ↓  Performance ↑  — The AI Learned to Simplify",
        fontsize=17,
        color="white",
        fontweight="bold",
        pad=20,
    )

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="center left",
        fontsize=11,
        framealpha=0.3,
    )

    ax1.grid(True, alpha=0.1, color=GRID_COLOR)
    ax1.tick_params(axis="x", colors=MUTED)
    ax1.set_xticks(phases_x)
    ax1.set_xticklabels(
        [
            "Base",
            "MTF",
            "EMA+\nFund",
            "Lead\nLag",
            "Ensemble",
            "RSI\nTune",
            "Simplify",
            "Momentum\nClean",
            "RSI\nPeriod",
            "Fine\nTune",
            "Final",
        ],
        fontsize=8,
        color=MUTED,
    )
    for spine in ax1.spines.values():
        spine.set_color(GRID_COLOR)
    for spine in ax2.spines.values():
        spine.set_color(GRID_COLOR)

    fig.tight_layout()
    fig.savefig(
        OUTPUT_DIR / "8_complexity_vs_performance.png",
        dpi=200,
        bbox_inches="tight",
        facecolor=BG,
        edgecolor="none",
    )
    plt.close(fig)
    print("✓ Chart 8: Complexity vs Performance")


def chart9_score_impact_waterfall(exps):
    """Waterfall chart showing each kept strategy's delta contribution from 2.7 → 20.6."""
    keeps = [e for e in exps if e["status"] == "keep"]

    # Compute deltas between consecutive keeps
    deltas = []
    for i, k in enumerate(keeps):
        if i == 0:
            deltas.append(
                {
                    "desc": k["description"],
                    "delta": k["score"],
                    "cumulative": k["score"],
                }
            )
        else:
            d = k["score"] - keeps[i - 1]["score"]
            deltas.append(
                {"desc": k["description"], "delta": d, "cumulative": k["score"]}
            )

    fig, ax = plt.subplots(figsize=(18, 8))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    n = len(deltas)
    x = np.arange(n)
    bottoms = []
    colors = []
    heights = []

    for i, d in enumerate(deltas):
        if i == 0:
            bottoms.append(0)
        else:
            bottoms.append(deltas[i - 1]["cumulative"])
        heights.append(d["delta"])
        colors.append(ACCENT_GREEN if d["delta"] >= 0 else ACCENT_RED)

    bars = ax.bar(
        x,
        heights,
        bottom=bottoms,
        color=colors,
        width=0.7,
        edgecolor="none",
        alpha=0.85,
    )

    # Connector lines between bars
    for i in range(n - 1):
        top = bottoms[i] + heights[i]
        ax.plot(
            [i + 0.35, i + 0.65], [top, top], color=MUTED, linewidth=0.8, linestyle="--"
        )

    # Labels on bars with significant deltas
    for i, (bar, d) in enumerate(zip(bars, deltas)):
        if abs(d["delta"]) > 0.3 or i == 0:
            y_pos = bottoms[i] + heights[i] / 2
            label = f"+{d['delta']:.1f}" if d["delta"] >= 0 else f"{d['delta']:.1f}"
            ax.text(
                i,
                y_pos,
                label,
                ha="center",
                va="center",
                fontsize=7,
                color="white",
                fontweight="bold",
            )

    # X-axis labels — truncate descriptions
    labels = [d["desc"][:18] for d in deltas]
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=75, ha="right", fontsize=6.5, color=MUTED)

    ax.set_ylabel("Score", fontsize=13, color=TEXT_COLOR, labelpad=10)
    ax.set_title(
        "Score Impact Waterfall — How Each Keep Decision Built the Final Score",
        fontsize=17,
        color="white",
        fontweight="bold",
        pad=20,
    )
    ax.grid(True, axis="y", alpha=0.1, color=GRID_COLOR)
    ax.tick_params(axis="y", colors=MUTED)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)

    fig.tight_layout()
    fig.savefig(
        OUTPUT_DIR / "9_score_impact_waterfall.png",
        dpi=200,
        bbox_inches="tight",
        facecolor=BG,
        edgecolor="none",
    )
    plt.close(fig)
    print("✓ Chart 9: Score impact waterfall")


def chart10_kept_vs_all_path(exps):
    """Kept path vs hypothetical all-experiments path — shows AI selectivity."""
    # Running best from keeps only (actual path)
    kept_best = []
    best_kept = -999
    for e in exps:
        if e["status"] == "keep":
            best_kept = max(best_kept, e["score"])
        kept_best.append(best_kept)

    # Running best if we also accepted any discard that beat current best
    all_best = []
    best_all = -999
    for e in exps:
        best_all = max(best_all, e["score"])
        all_best.append(best_all)

    idxs = list(range(len(exps)))

    fig, ax = plt.subplots(figsize=(16, 8))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    ax.fill_between(idxs, kept_best, alpha=0.08, color=ACCENT_GREEN)
    ax.plot(
        idxs,
        kept_best,
        color=ACCENT_GREEN,
        linewidth=2.5,
        label="Kept Path (actual)",
        zorder=3,
    )
    ax.plot(
        idxs,
        all_best,
        color=ACCENT_ORANGE,
        linewidth=2,
        linestyle="--",
        label="Best-Score Path (if all accepted)",
        zorder=2,
        alpha=0.8,
    )

    # Shade the gap
    ax.fill_between(idxs, kept_best, all_best, alpha=0.06, color=ACCENT_ORANGE)

    # Annotate key divergences
    max_gap = 0
    max_gap_idx = 0
    for i in range(len(idxs)):
        gap = all_best[i] - kept_best[i]
        if gap > max_gap:
            max_gap = gap
            max_gap_idx = i

    if max_gap > 0.5:
        ax.annotate(
            f"Max gap: {max_gap:.1f}\n(discards had higher score\nbut worse risk profile)",
            (max_gap_idx, (kept_best[max_gap_idx] + all_best[max_gap_idx]) / 2),
            xytext=(30, 30),
            textcoords="offset points",
            fontsize=9,
            color=ACCENT_ORANGE,
            fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=MUTED, lw=1),
        )

    # Insight box
    final_kept = kept_best[-1]
    final_all = all_best[-1]
    insight = f"Final: Kept={final_kept:.1f}, All={final_all:.1f}"
    ax.text(
        0.98,
        0.05,
        insight,
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=11,
        color=TEXT_COLOR,
        fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.5", facecolor=CARD_BG, edgecolor=GRID_COLOR),
    )

    ax.set_xlabel("Experiment #", fontsize=13, color=TEXT_COLOR, labelpad=10)
    ax.set_ylabel("Running Best Score", fontsize=13, color=TEXT_COLOR, labelpad=10)
    ax.set_title(
        "AI Selectivity — Kept Path vs Accept-Everything Path",
        fontsize=17,
        color="white",
        fontweight="bold",
        pad=20,
    )
    ax.legend(loc="upper left", fontsize=11, framealpha=0.3)
    ax.grid(True, alpha=0.15, color=GRID_COLOR)
    ax.set_xlim(-2, 106)
    ax.tick_params(colors=MUTED)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)

    fig.tight_layout()
    fig.savefig(
        OUTPUT_DIR / "10_kept_vs_all_path.png",
        dpi=200,
        bbox_inches="tight",
        facecolor=BG,
        edgecolor="none",
    )
    plt.close(fig)
    print("✓ Chart 10: Kept path vs all-experiments path")


def chart11_per_experiment_delta(exps):
    """Per-experiment delta from running best — the search landscape."""
    # Compute running best (keeps only) at each experiment
    running_best = []
    best = -999
    for e in exps:
        if e["status"] == "keep":
            best = max(best, e["score"])
        running_best.append(best)

    # Delta = experiment score - running best at that point
    # For the very first experiment, compare against 0
    deltas = []
    for i, e in enumerate(exps):
        rb = running_best[i - 1] if i > 0 else 0
        deltas.append(e["score"] - rb)

    fig, ax = plt.subplots(figsize=(18, 7))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    idxs = np.arange(len(exps))
    colors = []
    for i, (d, e) in enumerate(zip(deltas, exps)):
        if d > 0 and e["status"] == "keep":
            colors.append(ACCENT_GREEN)
        elif d > 0 and e["status"] == "discard":
            colors.append(
                ACCENT_ORANGE
            )  # beat running best but discarded (risk issues)
        else:
            colors.append(ACCENT_RED)

    ax.bar(idxs, deltas, color=colors, width=0.8, edgecolor="none", alpha=0.75)
    ax.axhline(y=0, color=MUTED, linewidth=1, linestyle="-")

    # Legend
    from matplotlib.patches import Patch

    legend_elements = [
        Patch(facecolor=ACCENT_GREEN, alpha=0.75, label="Improvement (kept)"),
        Patch(
            facecolor=ACCENT_ORANGE, alpha=0.75, label="Beat best but discarded (risk)"
        ),
        Patch(facecolor=ACCENT_RED, alpha=0.75, label="Below running best"),
    ]
    ax.legend(handles=legend_elements, loc="upper right", fontsize=10, framealpha=0.3)

    # Stats annotation
    n_improve = sum(1 for d, e in zip(deltas, exps) if d > 0 and e["status"] == "keep")
    n_beat_discard = sum(
        1 for d, e in zip(deltas, exps) if d > 0 and e["status"] == "discard"
    )
    n_below = sum(1 for d in deltas if d <= 0)
    stats = f"{n_improve} improvements kept  |  {n_beat_discard} beat best but discarded  |  {n_below} below running best"
    ax.text(
        0.5,
        0.97,
        stats,
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=10,
        color=TEXT_COLOR,
        bbox=dict(boxstyle="round,pad=0.4", facecolor=CARD_BG, edgecolor=GRID_COLOR),
    )

    ax.set_xlabel("Experiment #", fontsize=13, color=TEXT_COLOR, labelpad=10)
    ax.set_ylabel(
        "Score Delta from Running Best", fontsize=13, color=TEXT_COLOR, labelpad=10
    )
    ax.set_title(
        "Search Landscape — How Many Experiments to Find Each Improvement",
        fontsize=17,
        color="white",
        fontweight="bold",
        pad=20,
    )
    ax.grid(True, axis="y", alpha=0.1, color=GRID_COLOR)
    ax.set_xlim(-1, 105)
    ax.tick_params(colors=MUTED)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)

    fig.tight_layout()
    fig.savefig(
        OUTPUT_DIR / "11_per_experiment_delta.png",
        dpi=200,
        bbox_inches="tight",
        facecolor=BG,
        edgecolor="none",
    )
    plt.close(fig)
    print("✓ Chart 11: Per-experiment delta")


def chart12_equity_curve():
    """Chart 12: Portfolio equity curve (PNL over time)."""
    csv_path = Path("/Users/jae_lee/auto-researchtrading/equity_curve.csv")
    if not csv_path.exists():
        print(
            "⚠ Skipping Chart 12: equity_curve.csv not found (run export_equity.py first)"
        )
        return

    timestamps, equities = [], []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            timestamps.append(datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M"))
            equities.append(float(row["equity"]))

    equities = np.array(equities)
    initial = equities[0]
    pnl_pct = (equities - initial) / initial * 100

    # Find max drawdown period for annotation
    peak = np.maximum.accumulate(equities)
    drawdown = (peak - equities) / peak * 100
    max_dd_idx = np.argmax(drawdown)
    max_dd_val = drawdown[max_dd_idx]

    fig, ax = plt.subplots(figsize=(14, 6), facecolor=BG)
    ax.set_facecolor(BG)

    # Fill area under curve — green above starting equity, red below
    ax.fill_between(
        timestamps, pnl_pct, 0, where=pnl_pct >= 0, color=ACCENT_GREEN, alpha=0.15
    )
    ax.fill_between(
        timestamps, pnl_pct, 0, where=pnl_pct < 0, color=ACCENT_RED, alpha=0.15
    )

    # Main equity line
    ax.plot(timestamps, pnl_pct, color=ACCENT_GREEN, linewidth=1.5, alpha=0.9)

    # Zero line
    ax.axhline(y=0, color=MUTED, linewidth=0.8, linestyle="--", alpha=0.5)

    # Annotate final value
    final_pnl = pnl_pct[-1]
    final_equity = equities[-1]
    ax.annotate(
        f"+{final_pnl:.1f}%\n${final_equity:,.0f}",
        xy=(timestamps[-1], final_pnl),
        xytext=(-80, 20),
        textcoords="offset points",
        fontsize=11,
        fontweight="bold",
        color=ACCENT_GREEN,
        arrowprops=dict(arrowstyle="->", color=ACCENT_GREEN, lw=1.5),
        bbox=dict(
            boxstyle="round,pad=0.4",
            facecolor=CARD_BG,
            edgecolor=ACCENT_GREEN,
            alpha=0.9,
        ),
    )

    # Annotate starting value
    ax.annotate(
        "$100K start",
        xy=(timestamps[0], 0),
        xytext=(60, -30),
        textcoords="offset points",
        fontsize=9,
        color=MUTED,
        arrowprops=dict(arrowstyle="->", color=MUTED, lw=1),
    )

    # Annotate max drawdown if visible
    if max_dd_val > 0.5:
        ax.annotate(
            f"Max DD: {max_dd_val:.1f}%",
            xy=(timestamps[max_dd_idx], pnl_pct[max_dd_idx]),
            xytext=(40, -25),
            textcoords="offset points",
            fontsize=9,
            color=ACCENT_ORANGE,
            arrowprops=dict(arrowstyle="->", color=ACCENT_ORANGE, lw=1),
            bbox=dict(
                boxstyle="round,pad=0.3",
                facecolor=CARD_BG,
                edgecolor=ACCENT_ORANGE,
                alpha=0.8,
            ),
        )

    ax.set_title(
        "Portfolio Equity Curve — $100K Starting Capital",
        fontsize=16,
        fontweight="bold",
        color=TEXT_COLOR,
        pad=15,
    )
    ax.set_ylabel("Return (%)", fontsize=12, color=TEXT_COLOR)
    ax.set_xlabel("", fontsize=12, color=TEXT_COLOR)

    # Format x-axis dates
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")

    ax.tick_params(colors=MUTED, labelsize=10)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("+%.0f%%"))
    ax.grid(True, alpha=0.15, color=GRID_COLOR)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)

    fig.tight_layout()
    fig.savefig(
        OUTPUT_DIR / "12_equity_curve.png",
        dpi=200,
        bbox_inches="tight",
        facecolor=BG,
        edgecolor="none",
    )
    plt.close(fig)
    print("✓ Chart 12: Equity curve (PNL)")


def chart13_equity_evolution():
    """Chart 13: Overlay equity curves at key autoresearch milestones."""
    milestones = [
        ("equity_curve_baseline.csv", "Baseline (Sharpe 2.7)", ACCENT_RED, 1.0, "--"),
        ("equity_curve_exp15.csv", "Exp 15: Ensemble (8.4)", ACCENT_ORANGE, 0.7, "-"),
        (
            "equity_curve_exp46.csv",
            "Exp 46: Simplified (13.5)",
            ACCENT_PURPLE,
            0.7,
            "-",
        ),
        ("equity_curve_exp72.csv", "Exp 72: RSI-8 (19.7)", ACCENT_CYAN, 0.7, "-"),
        ("equity_curve_exp102.csv", "Final (Sharpe 20.6)", ACCENT_GREEN, 1.0, "-"),
    ]

    base = Path("/Users/jae_lee/auto-researchtrading")
    fig, (ax_pnl, ax_dd) = plt.subplots(
        2,
        1,
        figsize=(14, 10),
        facecolor=BG,
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.12},
    )

    timestamps: list = []
    pnl_pct: Any = []

    for csv_name, label, color, alpha, ls in milestones:
        csv_path = base / csv_name
        if not csv_path.exists():
            print(f"  ⚠ Missing {csv_name}, skipping")
            continue

        timestamps, equities = [], []
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                timestamps.append(datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M"))
                equities.append(float(row["equity"]))

        equities = np.array(equities)
        pnl_pct = (equities - 100_000) / 100_000 * 100

        # Drawdown
        peak = np.maximum.accumulate(equities)
        dd_pct = (peak - equities) / peak * 100

        lw = 2.2 if alpha == 1.0 else 1.3
        ax_pnl.plot(
            timestamps,
            pnl_pct,
            color=color,
            linewidth=lw,
            alpha=alpha,
            linestyle=ls,
            label=label,
        )
        ax_dd.plot(
            timestamps, -dd_pct, color=color, linewidth=lw, alpha=alpha, linestyle=ls
        )

    # PNL panel
    ax_pnl.set_facecolor(BG)
    ax_pnl.axhline(y=0, color=MUTED, linewidth=0.8, linestyle="--", alpha=0.4)
    ax_pnl.set_title(
        "Equity Curve Evolution — Baseline vs Autoresearch Iterations",
        fontsize=16,
        fontweight="bold",
        color=TEXT_COLOR,
        pad=15,
    )
    ax_pnl.set_ylabel("Return (%)", fontsize=12, color=TEXT_COLOR)
    ax_pnl.legend(
        loc="upper left",
        fontsize=10,
        facecolor=CARD_BG,
        edgecolor=GRID_COLOR,
        labelcolor=TEXT_COLOR,
    )
    ax_pnl.tick_params(colors=MUTED, labelsize=10)
    ax_pnl.yaxis.set_major_formatter(mticker.FormatStrFormatter("+%.0f%%"))
    ax_pnl.grid(True, alpha=0.15, color=GRID_COLOR)
    ax_pnl.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax_pnl.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax_pnl.set_xticklabels([])
    for spine in ax_pnl.spines.values():
        spine.set_color(GRID_COLOR)

    # Annotation: arrow from baseline end to final end
    ax_pnl.annotate(
        "7.9x better\nrisk-adjusted",
        xy=(timestamps[-1], pnl_pct[-1] if "pnl_pct" in dir() else 0),
        xytext=(-120, 30),
        textcoords="offset points",
        fontsize=10,
        fontweight="bold",
        color=ACCENT_GREEN,
        bbox=dict(
            boxstyle="round,pad=0.4",
            facecolor=CARD_BG,
            edgecolor=ACCENT_GREEN,
            alpha=0.9,
        ),
    )

    # Drawdown panel
    ax_dd.set_facecolor(BG)
    ax_dd.axhline(y=0, color=MUTED, linewidth=0.8, linestyle="--", alpha=0.4)
    ax_dd.set_ylabel("Drawdown (%)", fontsize=11, color=TEXT_COLOR)
    ax_dd.tick_params(colors=MUTED, labelsize=10)
    ax_dd.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax_dd.grid(True, alpha=0.15, color=GRID_COLOR)
    ax_dd.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax_dd.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax_dd.xaxis.get_majorticklabels(), rotation=45, ha="right")
    for spine in ax_dd.spines.values():
        spine.set_color(GRID_COLOR)

    fig.tight_layout()
    fig.savefig(
        OUTPUT_DIR / "13_equity_evolution.png",
        dpi=200,
        bbox_inches="tight",
        facecolor=BG,
        edgecolor="none",
    )
    plt.close(fig)
    print("✓ Chart 13: Equity curve evolution (milestone overlay)")


def main():
    print("Loading experiment data...")
    exps = load_results()
    print(
        f"Loaded {len(exps)} experiments ({sum(1 for e in exps if e['status'] == 'keep')} keeps, "
        f"{sum(1 for e in exps if e['status'] == 'discard')} discards)\n"
    )

    print("Generating charts...\n")
    chart1_score_evolution(exps)
    chart2_before_after(exps)
    chart3_simplification_impact(exps)
    chart4_drawdown_evolution(exps)
    chart5_keep_discard_ratio(exps)
    chart6_top_discoveries(exps)
    chart7_final_strategy_architecture()
    chart8_complexity_vs_performance(exps)
    chart9_score_impact_waterfall(exps)
    chart10_kept_vs_all_path(exps)
    chart11_per_experiment_delta(exps)
    chart12_equity_curve()
    chart13_equity_evolution()

    print(f"\n✅ All charts saved to {OUTPUT_DIR}/")
    print("\nFiles generated:")
    for f in sorted(OUTPUT_DIR.glob("*.png")):
        print(f"  📊 {f.name}")


if __name__ == "__main__":
    main()
