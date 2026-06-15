#!/usr/bin/env python3
"""
plot_emission.py — Emission-based volume model charts.

Compares emissionBasedVolume=True vs False:
  E01  LP balance: emission vs base (per flow %)
  E02  PAPER minted: emission vs base
  E03  Trader net PnL: emission vs base
  E04  Volume: emission vs base (per flow %)
  E05  Emission multiplier decay over time
  E06  Summary table (startDay=0)
  E07  Tail progress: emission vs base
  E08  Staker fees: emission vs base

Usage:
    python3 plot_emission.py
    python3 plot_emission.py --dir /path/to/csvs
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

START_DATE = datetime(2025, 8, 1, tzinfo=timezone.utc)
SIM_DAYS = 290

FLOW_FRACS = [0.25, 0.50, 0.75, 1.0]
FLOW_COLORS = {0.25: "#a855f7", 0.50: "#f7931a", 0.75: "#1769e0", 1.0: "#18936a"}
FLOW_LABELS = {0.25: "25% flow", 0.50: "50% flow", 0.75: "75% flow", 1.0: "100% flow"}


def day_to_date(day: int) -> datetime:
    return START_DATE + timedelta(days=int(day))


def setup_style():
    plt.rcParams.update({
        "font.family": "sans-serif", "font.size": 10,
        "axes.titlesize": 12, "axes.titleweight": "bold",
        "axes.labelsize": 10, "axes.grid": True,
        "grid.alpha": 0.25, "grid.linewidth": 0.5,
        "figure.facecolor": "white", "axes.facecolor": "white",
        "figure.dpi": 150,
    })


def dates_axis(ax):
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)


def usd_fmt(x, _):
    if abs(x) >= 1e9: return f"${x/1e9:.1f}B"
    if abs(x) >= 1e6: return f"${x/1e6:.1f}M"
    if abs(x) >= 1e3: return f"${x/1e3:.0f}K"
    return f"${x:.0f}"


def usd_signed(x, _):
    s = "-" if x < 0 else ""
    v = abs(x)
    if v >= 1e9: return f"{s}${v/1e9:.1f}B"
    if v >= 1e6: return f"{s}${v/1e6:.1f}M"
    if v >= 1e3: return f"{s}${v/1e3:.0f}K"
    return f"{s}${v:.0f}"


def paper_fmt(x, _):
    if abs(x) >= 1e9: return f"{x/1e9:.2f}B"
    if abs(x) >= 1e6: return f"{x/1e6:.0f}M"
    return f"{x:,.0f}"


def get_defaults(r, emission: bool):
    """Get rows where all impact params are at docs defaults."""
    mask = (np.isclose(r["btcBaseRate"], 0.05) &
            np.isclose(r["btcReferenceNotional"], 100_000) &
            np.isclose(r["ethReferenceNotional"], 50_000))
    if "emissionBased" in r.columns:
        mask &= (r["emissionBased"] == emission)
    return r[mask]


# =========================================================================
# E01: LP balance — emission vs base, per flow %
# =========================================================================
def plot_e01_lp_compare(results, daily_lp, out: Path):
    if daily_lp is None:
        return

    flows = FLOW_FRACS
    fig, axes = plt.subplots(1, len(flows), figsize=(5 * len(flows), 5), sharey=True)
    fig.suptitle("LP balance: base vs emission-based volume (startDay=0, ADL off)",
                 fontsize=14, fontweight="bold")

    dates = [day_to_date(d) for d in range(SIM_DAYS)]

    for col, flow in enumerate(flows):
        ax = axes[col] if len(flows) > 1 else axes

        for em, ls, alpha, tag in [(False, "-", 0.9, "base"), (True, "--", 0.7, "emission")]:
            defaults = get_defaults(results, emission=em)
            mask = ((defaults["sampleFraction"] == flow) &
                    (defaults["startDay"] == 0) &
                    (defaults["adlWorstCase"] == False))
            subset = defaults[mask]
            if subset.empty:
                continue
            sid = subset.iloc[0]["scenario_id"]
            if sid not in daily_lp.index:
                continue
            lp_vals = daily_lp.loc[sid].values.astype(float)
            ax.plot(dates, lp_vals, color=FLOW_COLORS[flow], ls=ls, lw=2,
                    alpha=alpha, label=tag)

        ax.axhline(5_000_000, color="#9a6b16", ls=":", lw=1, alpha=0.3)
        ax.axhline(2_000_000, color="#59636f", ls=":", lw=1, alpha=0.3)
        ax.set_title(FLOW_LABELS[flow])
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
        dates_axis(ax)
        if col == 0:
            ax.set_ylabel("LP balance")
        ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out / "E01_lp_compare.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# E02: PAPER minted — emission vs base by flow
# =========================================================================
def plot_e02_paper_compare(results, out: Path):
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle("PAPER minted: base vs emission-based volume (ADL off)",
                 fontsize=14, fontweight="bold")

    for ax_idx, (em, title) in enumerate([(False, "Base model"), (True, "Emission model")]):
        ax = axes[ax_idx]
        ax.set_title(title)
        defaults = get_defaults(results, emission=em)
        for flow in FLOW_FRACS:
            mask = ((defaults["sampleFraction"] == flow) &
                    (defaults["adlWorstCase"] == False))
            data = defaults[mask].sort_values("startDay")
            if data.empty:
                continue
            x_dates = [day_to_date(d) for d in data["startDay"]]
            ax.plot(x_dates, data["finalPaper"], color=FLOW_COLORS[flow],
                    lw=2, alpha=0.85, label=FLOW_LABELS[flow])

        ax.yaxis.set_major_formatter(mticker.FuncFormatter(paper_fmt))
        dates_axis(ax)
        ax.set_ylabel("PAPER minted")
        ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out / "E02_paper_compare.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# E03: Trader net PnL — emission vs base
# =========================================================================
def plot_e03_trader_compare(results, out: Path):
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle("Trader net PnL: base vs emission-based volume (ADL off)",
                 fontsize=14, fontweight="bold")

    for ax_idx, (em, title) in enumerate([(False, "Base model"), (True, "Emission model")]):
        ax = axes[ax_idx]
        ax.set_title(title)
        defaults = get_defaults(results, emission=em)
        for flow in FLOW_FRACS:
            mask = ((defaults["sampleFraction"] == flow) &
                    (defaults["adlWorstCase"] == False))
            data = defaults[mask].sort_values("startDay")
            if data.empty:
                continue
            x_dates = [day_to_date(d) for d in data["startDay"]]
            ax.plot(x_dates, data["traderNet"], color=FLOW_COLORS[flow],
                    lw=2, alpha=0.85, label=FLOW_LABELS[flow])

        ax.axhline(0, color="black", ls="-", lw=0.5, alpha=0.3)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(usd_signed))
        dates_axis(ax)
        ax.set_ylabel("Trader net PnL ($)")
        ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out / "E03_trader_compare.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# E04: Total volume — emission vs base
# =========================================================================
def plot_e04_volume_compare(results, out: Path):
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle("Total simulated volume: base vs emission-based (ADL off)",
                 fontsize=14, fontweight="bold")

    for ax_idx, (em, title) in enumerate([(False, "Base model"), (True, "Emission model")]):
        ax = axes[ax_idx]
        ax.set_title(title)
        defaults = get_defaults(results, emission=em)
        for flow in FLOW_FRACS:
            mask = ((defaults["sampleFraction"] == flow) &
                    (defaults["adlWorstCase"] == False))
            data = defaults[mask].sort_values("startDay")
            if data.empty:
                continue
            x_dates = [day_to_date(d) for d in data["startDay"]]
            ax.plot(x_dates, data["totalVolume"], color=FLOW_COLORS[flow],
                    lw=2, alpha=0.85, label=FLOW_LABELS[flow])

        ax.yaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
        dates_axis(ax)
        ax.set_ylabel("Total volume ($)")
        ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out / "E04_volume_compare.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# E05: Emission multiplier decay — theoretical curve + key checkpoints
# =========================================================================
def plot_e05_emission_curve(out: Path):
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle("Emission multiplier: (S / (S + tailProgress))^2",
                 fontsize=14, fontweight="bold")

    S = 120_000_000  # tail_scale

    # Left: multiplier vs tailProgress
    ax = axes[0]
    tp = np.linspace(0, 500_000_000, 1000)
    mult = (S / (S + tp)) ** 2
    ax.plot(tp / 1e6, mult, color="#1769e0", lw=2.5)
    # Mark key points
    for tp_val, label in [(0, "Start"), (S / 4, "$30M"), (S, "$120M"),
                          (S * 2, "$240M"), (S * 5, "$600M")]:
        m = (S / (S + tp_val)) ** 2
        ax.plot(tp_val / 1e6, m, "o", color="#e05f2b", markersize=8)
        ax.annotate(f"{label}\nmult={m:.2f}", (tp_val / 1e6, m),
                    textcoords="offset points", xytext=(10, 10), fontsize=8,
                    arrowprops=dict(arrowstyle="->", color="gray"))

    ax.set_xlabel("Tail progress ($M)")
    ax.set_ylabel("Volume multiplier")
    ax.set_title("Multiplier vs cumulative LP gain past $2M")
    ax.set_ylim(0, 1.05)

    # Right: PAPER per $ vs tailProgress (mint rate × volume_mult)
    ax = axes[1]
    # In flat region (< $2M), rate = 100 PAPER/$. Past $2M:
    # rate = 100 * (S/(S+tp))^2, volume gets same multiplier
    # effective PAPER/$ = rate * volume_mult = 100 * (S/(S+tp))^4
    effective = 100 * (S / (S + tp)) ** 4
    ax.plot(tp / 1e6, effective, color="#18936a", lw=2.5)
    ax.set_xlabel("Tail progress ($M)")
    ax.set_ylabel("Effective PAPER per $ volume")
    ax.set_title("Self-reinforcing: rate × volume both decay")
    ax.set_yscale("log")

    fig.tight_layout()
    fig.savefig(out / "E05_emission_curve.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# E06: Summary table — emission vs base at startDay=0
# =========================================================================
def plot_e06_summary_table(results, out: Path):
    fig, ax = plt.subplots(figsize=(16, 8))
    ax.set_title("Emission vs Base model — summary (startDay=0, ADL off)",
                 fontsize=13, fontweight="bold")
    ax.axis("off")

    flows = FLOW_FRACS
    metrics = [
        ("finalLp", "Final LP ($)"),
        ("finalPaper", "PAPER minted"),
        ("finalStakers", "Staker fees ($)"),
        ("traderNet", "Trader net PnL ($)"),
        ("totalVolume", "Total volume ($)"),
        ("tailProgress", "Tail progress ($)"),
        ("costPerPaper", "Cost per PAPER ($)"),
        ("maxDebt", "Max queue debt ($)"),
    ]

    col_labels = []
    for flow in flows:
        col_labels.append(f"{flow:.0%} base")
        col_labels.append(f"{flow:.0%} emis.")

    row_labels = [m[1] for m in metrics]
    cell_data = []

    def fmt_val(val, key):
        if key == "costPerPaper":
            return f"${val:.4f}"
        if abs(val) >= 1e9:
            return f"${val/1e9:.1f}B"
        if abs(val) >= 1e6:
            return f"${val/1e6:.1f}M"
        if abs(val) >= 1e3:
            return f"${val/1e3:.0f}K"
        return f"${val:.0f}"

    for key, label in metrics:
        row = []
        for flow in flows:
            for em in [False, True]:
                defaults = get_defaults(results, emission=em)
                mask = ((defaults["sampleFraction"] == flow) &
                        (defaults["startDay"] == 0) &
                        (defaults["adlWorstCase"] == False))
                data = defaults[mask]
                if data.empty:
                    row.append("--")
                else:
                    val = data.iloc[0][key]
                    if key == "finalPaper":
                        if val >= 1e6:
                            row.append(f"{val/1e6:.0f}M")
                        else:
                            row.append(f"{val:,.0f}")
                    else:
                        row.append(fmt_val(val, key))
        cell_data.append(row)

    table = ax.table(cellText=cell_data, rowLabels=row_labels,
                     colLabels=col_labels, loc="center",
                     cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(7)
    table.scale(1, 1.6)

    # Color headers
    for j in range(len(col_labels)):
        table[0, j].set_facecolor("#e8e8e8")
        # Tint emission columns
        if j % 2 == 1:
            for i in range(len(row_labels)):
                table[i + 1, j].set_facecolor("#f0f8ff")

    fig.tight_layout()
    fig.savefig(out / "E06_summary_table.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# E07: Tail progress — emission vs base
# =========================================================================
def plot_e07_tail_progress(results, out: Path):
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle("Tail progress: base vs emission-based volume (ADL off)",
                 fontsize=14, fontweight="bold")

    for ax_idx, (em, title) in enumerate([(False, "Base model"), (True, "Emission model")]):
        ax = axes[ax_idx]
        ax.set_title(title)
        defaults = get_defaults(results, emission=em)
        for flow in FLOW_FRACS:
            mask = ((defaults["sampleFraction"] == flow) &
                    (defaults["adlWorstCase"] == False))
            data = defaults[mask].sort_values("startDay")
            if data.empty:
                continue
            x_dates = [day_to_date(d) for d in data["startDay"]]
            ax.plot(x_dates, data["tailProgress"], color=FLOW_COLORS[flow],
                    lw=2, alpha=0.85, label=FLOW_LABELS[flow])

        ax.yaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
        dates_axis(ax)
        ax.set_ylabel("Tail progress ($)")
        ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out / "E07_tail_progress.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# E08: Staker fees — emission vs base
# =========================================================================
def plot_e08_staker_fees(results, out: Path):
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle("Total staker fees: base vs emission-based volume (ADL off)",
                 fontsize=14, fontweight="bold")

    for ax_idx, (em, title) in enumerate([(False, "Base model"), (True, "Emission model")]):
        ax = axes[ax_idx]
        ax.set_title(title)
        defaults = get_defaults(results, emission=em)
        for flow in FLOW_FRACS:
            mask = ((defaults["sampleFraction"] == flow) &
                    (defaults["adlWorstCase"] == False))
            data = defaults[mask].sort_values("startDay")
            if data.empty:
                continue
            x_dates = [day_to_date(d) for d in data["startDay"]]
            ax.plot(x_dates, data["finalStakers"], color=FLOW_COLORS[flow],
                    lw=2, alpha=0.85, label=FLOW_LABELS[flow])

        ax.yaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
        dates_axis(ax)
        ax.set_ylabel("Total staker fees ($)")
        ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out / "E08_staker_fees.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# Main
# =========================================================================
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=Path("."))
    args = parser.parse_args()

    setup_style()
    results = pd.read_csv(args.dir / "batch_results.csv")
    daily_lp = None
    lp_path = args.dir / "batch_daily_lp.csv"
    if lp_path.exists():
        daily_lp = pd.read_csv(lp_path, index_col=0)

    out = args.dir / "charts_emission"
    out.mkdir(exist_ok=True)

    # Check we have emission data
    if "emissionBased" not in results.columns:
        print("ERROR: batch_results.csv has no 'emissionBased' column. Re-run batch_simulate.py.")
        return

    n_base = len(results[results["emissionBased"] == False])
    n_em = len(results[results["emissionBased"] == True])
    print(f"Loaded {len(results)} scenarios: {n_base} base + {n_em} emission")

    plot_e01_lp_compare(results, daily_lp, out)
    print("  E01  LP balance: emission vs base")

    plot_e02_paper_compare(results, out)
    print("  E02  PAPER minted: emission vs base")

    plot_e03_trader_compare(results, out)
    print("  E03  Trader net PnL: emission vs base")

    plot_e04_volume_compare(results, out)
    print("  E04  Volume: emission vs base")

    plot_e05_emission_curve(out)
    print("  E05  Emission multiplier curve")

    plot_e06_summary_table(results, out)
    print("  E06  Summary table")

    plot_e07_tail_progress(results, out)
    print("  E07  Tail progress: emission vs base")

    plot_e08_staker_fees(results, out)
    print("  E08  Staker fees: emission vs base")

    print(f"\nEmission charts saved to {out}/")


if __name__ == "__main__":
    main()
