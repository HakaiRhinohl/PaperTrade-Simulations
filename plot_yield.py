#!/usr/bin/env python3
"""
plot_yield.py — Staker yield & PAPER emission charts from batch results.

Charts (stakerPct fixed at 2% per docs):
  09  Yield per staked PAPER by flow % vs start day (different % staked assumptions)
  10  PAPER emissions & cost by flow %
  11  LP balance paths by flow %
  12  Yield summary table (startDay=0)

Usage:
    python3 plot_yield.py
    python3 plot_yield.py --dir /path/to/csvs
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

STAKED_FRACTIONS = [0.10, 0.20, 0.30, 0.50]
STAKED_COLORS = {0.10: "#e05f2b", 0.20: "#f7931a", 0.30: "#1769e0", 0.50: "#18936a"}
STAKED_LABELS = {0.10: "10% staked", 0.20: "20% staked", 0.30: "30% staked", 0.50: "50% staked"}

FLOW_FRACS = [0.25, 0.50, 0.75, 1.0]
FLOW_COLORS = {0.25: "#a855f7", 0.50: "#f7931a", 0.75: "#1769e0", 1.0: "#18936a"}
FLOW_LABELS = {0.25: "25% flow", 0.50: "50% flow", 0.75: "75% flow", 1.0: "100% flow"}


def day_to_date(day: int) -> datetime:
    return START_DATE + timedelta(days=int(day))


def _em_label(emission: bool) -> str:
    """Append to suptitle so emission-based charts are immediately identifiable."""
    return "  —  Emission-based volume" if emission else ""


def _adl_label(adl: bool) -> str:
    """Append to suptitle so ADL-on charts are immediately identifiable."""
    return "  [ADL on]" if adl else "  [ADL off]"


def _make_comparison_grid(paths: list, labels: list, out_path, suptitle: str = "",
                           vertical: bool = False):
    """
    Stitch existing PNGs into a comparison figure.
    vertical=False (default): 2×2 grid layout.
    vertical=True: stack images one above the other (n rows × 1 column).
    """
    valid = [(p, l) for p, l in zip(paths, labels) if Path(p).exists()]
    if not valid:
        return
    n = len(valid)
    if vertical:
        nrows, ncols = n, 1
        fig_w, fig_h = 20, 10 * n
    else:
        nrows = 2 if n > 2 else 1
        ncols = 2 if n > 1 else 1
        fig_w, fig_h = 18 * ncols, 8 * nrows
    fig, axes = plt.subplots(nrows, ncols, figsize=(fig_w, fig_h))
    axes_flat = np.array(axes).flatten() if n > 1 else [axes]
    for ax, (path, label) in zip(axes_flat, valid):
        img = plt.imread(str(path))
        ax.imshow(img)
        ax.set_title(label, fontsize=13, fontweight="bold", pad=6)
        ax.axis("off")
    for ax in axes_flat[len(valid):]:
        ax.axis("off")
    if suptitle:
        fig.suptitle(suptitle, fontsize=12, fontweight="bold", y=1.01)
    fig.tight_layout()
    fig.savefig(str(out_path), bbox_inches="tight", dpi=130)
    plt.close(fig)


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


def yield_fmt(x, _):
    """Formatter for sub-dollar yield values (cents per PAPER)."""
    if abs(x) >= 1e6: return f"${x/1e6:.1f}M"
    if abs(x) >= 1e3: return f"${x/1e3:.0f}K"
    if abs(x) >= 1.0: return f"${x:.2f}"
    if abs(x) >= 0.001: return f"${x:.4f}"
    return f"${x:.6f}"


def paper_fmt(x, _):
    if abs(x) >= 1e9: return f"{x/1e9:.2f}B"
    if abs(x) >= 1e6: return f"{x/1e6:.0f}M"
    return f"{x:,.0f}"


def get_defaults(r, emission=False):
    """Get rows where all impact params are at docs defaults."""
    mask = (np.isclose(r["btcBaseRate"], 0.05) &
            np.isclose(r["btcReferenceNotional"], 100_000) &
            np.isclose(r["ethReferenceNotional"], 50_000))
    if "emissionBased" in r.columns:
        mask &= (r["emissionBased"] == emission)
    return r[mask]


# =========================================================================
# Chart 09: Yield per staked PAPER by flow % vs start day
#   Lines = different % staked assumptions, panels = flow %
# =========================================================================
def plot_yield_by_flow(r, out: Path, emission=False, adl=False):
    suf = ""; adl_sfx = "_adl" if adl else ""
    defaults = get_defaults(r, emission=emission)
    flows = sorted(defaults["sampleFraction"].unique())

    if not len(flows):
        print("  (no default-param data for yield chart)")
        return

    ncols = len(flows)
    fig, axes = plt.subplots(1, ncols, figsize=(5 * ncols, 5), sharey=True)
    fig.suptitle(f"Yield per staked PAPER by launch date (stakerPct=2%, ADL off){_adl_label(adl)}{_em_label(emission)}",
                 fontsize=14, fontweight="bold")

    for col, flow in enumerate(flows):
        ax = axes[col] if ncols > 1 else axes

        mask = ((defaults["sampleFraction"] == flow) &
                (defaults["adlWorstCase"] == adl))
        data = defaults[mask].sort_values("startDay")
        if data.empty:
            continue

        x_dates = [day_to_date(d) for d in data["startDay"]]

        for sf in STAKED_FRACTIONS:
            yield_per = data["finalStakers"].values / (data["finalPaper"].values * sf + 1e-9)
            ax.plot(x_dates, yield_per, color=STAKED_COLORS[sf],
                    lw=1.8, alpha=0.85, label=STAKED_LABELS[sf])

        ax.set_title(FLOW_LABELS[flow], fontsize=11)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(yield_fmt))
        dates_axis(ax)
        if col == 0:
            ax.set_ylabel("Yield per staked PAPER ($)")
        if col == ncols - 1:
            ax.legend(fontsize=7, loc="upper right")

    fig.tight_layout()
    fig.savefig(out / f"09_yield_by_flow{adl_sfx}{suf}.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# Chart 10: PAPER emissions & cost — flow comparison
#   2x2: PAPER minted / cost per PAPER / staker fees / trader net
# =========================================================================
def plot_paper_by_flow(r, out: Path, emission=False, adl=False):
    suf = ""; adl_sfx = "_adl" if adl else ""
    defaults = get_defaults(r, emission=emission)
    flows = sorted(defaults["sampleFraction"].unique())

    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle(f"PAPER emissions & cost by flow % (default params, ADL off){_adl_label(adl)}{_em_label(emission)}\n"
                 "x-axis = launch date: later launch → fewer trading days → all totals smaller",
                 fontsize=13, fontweight="bold")

    # traderLoss (always positive) instead of traderNet to avoid sign confusion.
    # traderNet = traderWin - traderLoss ≈ -(traderLoss) because losses >> wins.
    # Both are correct; losses magnitude is more intuitive.
    # NOTE ON X-AXIS: each point = one LAUNCH DATE scenario, not a moment in time.
    # Earlier launch (left) → more trading days → higher cumulative totals.
    # "Decaying" curves are expected and correct — it's not time decay, it's fewer days.
    metrics = [
        ("finalPaper",
         "Cumulative PAPER minted at end of sim by launch date\n"
         "(earlier launch = more days = more total PAPER — NOT a decay over time)",
         paper_fmt),
        ("costPerPaper",
         "Avg cost per PAPER ($) by launch date\n"
         "(earlier launch → more tail-decay time → higher avg cost; all approach $0.01 for late launch)",
         lambda x, _: f"${x:.3f}"),
        ("finalStakers",
         "Cumulative staker fees ($) at end of sim by launch date",
         usd_fmt),
        ("traderLoss",
         "Cumulative trader losses ($) at end of sim by launch date\n"
         "(always positive; earlier launch = more trades = more total loss)",
         usd_fmt),
    ]

    for ax, (metric, title, yfmt) in zip(axes.flat, metrics):
        ax.set_title(title, fontsize=9)
        for flow in flows:
            mask = ((defaults["sampleFraction"] == flow) &
                    (defaults["adlWorstCase"] == adl))
            data = defaults[mask].sort_values("startDay")
            if data.empty:
                continue
            x_dates = [day_to_date(d) for d in data["startDay"]]
            ax.plot(x_dates, data[metric], color=FLOW_COLORS.get(flow, "#333"),
                    lw=2, alpha=0.85, label=FLOW_LABELS.get(flow, f"{flow:.0%}"))

        ax.yaxis.set_major_formatter(mticker.FuncFormatter(yfmt))
        dates_axis(ax)
        ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out / f"10_paper_by_flow{adl_sfx}{suf}.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# Chart 13: Cumulative PAPER minted + staker fees as time-series
# =========================================================================
def plot_cumulative_timeseries(r, daily_paper, daily_stakers, out: Path, emission=False, adl=False):
    """Time-series of cumulative PAPER supply and staker fees (startDay=0, vary flow)."""
    suf = ""; adl_sfx = "_adl" if adl else ""
    if daily_paper is None or daily_stakers is None:
        print("  (skipping cumulative timeseries — missing batch_daily_paper/stakers CSV)")
        return

    defaults = get_defaults(r, emission=emission)
    flows    = sorted(defaults["sampleFraction"].unique())
    dates    = [day_to_date(d) for d in range(SIM_DAYS)]

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle(f"Cumulative PAPER minted & staker fees over time{_adl_label(adl)}{_em_label(emission)}\n"
                 "(startDay=0, default params, ADL off)",
                 fontsize=13, fontweight="bold")

    ax = axes[0]
    ax.set_title("Cumulative PAPER supply over time")
    for flow in flows:
        mask = ((defaults["sampleFraction"] == flow) &
                (defaults["startDay"] == 0) &
                (defaults["adlWorstCase"] == adl))
        subset = defaults[mask]
        if subset.empty:
            continue
        sid = subset.iloc[0]["scenario_id"]
        if sid not in daily_paper.index:
            continue
        ax.plot(dates, daily_paper.loc[sid].values.astype(float),
                color=FLOW_COLORS.get(flow, "#333"), lw=2,
                label=FLOW_LABELS.get(flow, f"{flow:.0%}"))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(paper_fmt))
    dates_axis(ax)
    ax.set_ylabel("PAPER supply")
    ax.legend(fontsize=8)

    ax = axes[1]
    ax.set_title("Cumulative staker fees over time (USDC)")
    for flow in flows:
        mask = ((defaults["sampleFraction"] == flow) &
                (defaults["startDay"] == 0) &
                (defaults["adlWorstCase"] == adl))
        subset = defaults[mask]
        if subset.empty:
            continue
        sid = subset.iloc[0]["scenario_id"]
        if sid not in daily_stakers.index:
            continue
        ax.plot(dates, daily_stakers.loc[sid].values.astype(float),
                color=FLOW_COLORS.get(flow, "#333"), lw=2,
                label=FLOW_LABELS.get(flow, f"{flow:.0%}"))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
    dates_axis(ax)
    ax.set_ylabel("Cumulative fees ($)")
    ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out / f"13_cumulative_timeseries{adl_sfx}{suf}.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# Chart 14: Instantaneous cost per PAPER over time (via tail progress)
# =========================================================================
def plot_cost_per_paper_timeseries(r, daily_tail, out: Path, emission=False, adl=False):
    """Show how the marginal PAPER mint cost evolves from $0.01 upward as LP enters tail."""
    suf = ""; adl_sfx = "_adl" if adl else ""
    if daily_tail is None:
        print("  (skipping cost timeseries — missing batch_daily_tail CSV)")
        return

    S          = 120_000_000   # tail_decay_scale_usd (matches batch_simulate default)
    FLAT_RATE  = 100.0         # PAPER per $ in flat region → $0.01 per PAPER
    defaults   = get_defaults(r, emission=emission)
    flows      = sorted(defaults["sampleFraction"].unique())
    dates      = [day_to_date(d) for d in range(SIM_DAYS)]

    fig, ax = plt.subplots(figsize=(14, 6))
    ax.set_title(
        f"Instantaneous cost per PAPER over time{_adl_label(adl)}{_em_label(emission)}\n"
        "(all scenarios start at $0.01 when LP < $2M flat region;\n"
        " cost rises as LP enters tail decay — higher flow reaches tail sooner)",
        fontsize=11
    )

    for flow in flows:
        mask = ((defaults["sampleFraction"] == flow) &
                (defaults["startDay"] == 0) &
                (defaults["adlWorstCase"] == adl))
        subset = defaults[mask]
        if subset.empty:
            continue
        sid = subset.iloc[0]["scenario_id"]
        if sid not in daily_tail.index:
            continue
        tail_vals = daily_tail.loc[sid].values.astype(float)
        # marginal rate = FLAT_RATE * (S/(S+tail))^2  → cost = 1/rate
        rate = FLAT_RATE * (S / (S + tail_vals)) ** 2
        cost = 1.0 / rate
        ax.plot(dates, cost, color=FLOW_COLORS.get(flow, "#333"), lw=2,
                label=FLOW_LABELS.get(flow, f"{flow:.0%}"))

    ax.axhline(1.0 / FLAT_RATE, color="black", ls="--", lw=1, alpha=0.5,
               label=f"Flat-region floor: ${1/FLAT_RATE:.2f} per PAPER")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: f"${x:.4f}" if x < 0.1 else f"${x:.3f}"))
    dates_axis(ax)
    ax.set_ylabel("Marginal cost per PAPER ($)")
    ax.legend(fontsize=9)

    fig.tight_layout()
    fig.savefig(out / f"14_cost_per_paper_timeseries{adl_sfx}{suf}.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# Chart 11: LP paths by flow (startDay=0)
# =========================================================================
def plot_lp_by_flow(r, daily_lp, out: Path, emission=False, adl=False):
    suf = ""; adl_sfx = "_adl" if adl else ""
    if daily_lp is None:
        return

    defaults = get_defaults(r, emission=emission)
    flows = sorted(defaults["sampleFraction"].unique())

    fig, ax = plt.subplots(figsize=(16, 7))
    ax.set_title(f"LP balance by flow % (startDay=0, default params, ADL off){_adl_label(adl)}{_em_label(emission)}",
                 fontsize=13, fontweight="bold")

    dates = [day_to_date(d) for d in range(SIM_DAYS)]

    for flow in flows:
        mask = ((defaults["sampleFraction"] == flow) &
                (defaults["startDay"] == 0) &
                (defaults["adlWorstCase"] == adl))
        subset = defaults[mask]
        if subset.empty:
            continue
        sid = subset.iloc[0]["scenario_id"]
        if sid not in daily_lp.index:
            continue
        lp_vals = daily_lp.loc[sid].values.astype(float)
        ax.plot(dates, lp_vals, color=FLOW_COLORS.get(flow, "#333"), lw=2,
                alpha=0.85, label=FLOW_LABELS.get(flow, f"{flow:.0%}"))

    ax.axhline(5_000_000, color="#9a6b16", ls="--", lw=1, alpha=0.4, label="LP cap ($5M)")
    ax.axhline(2_000_000, color="#59636f", ls="--", lw=1, alpha=0.3, label="PAPER threshold ($2M)")
    ax.set_ylim(0, 5_500_000)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
    dates_axis(ax)
    ax.set_ylabel("LP balance")
    ax.legend(fontsize=9)

    fig.tight_layout()
    fig.savefig(out / f"11_lp_by_flow{adl_sfx}{suf}.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# Chart 12: Summary table — yield at startDay=0
# =========================================================================
def plot_yield_table(r, out: Path, emission=False, adl=False):
    suf = ""; adl_sfx = "_adl" if adl else ""
    defaults = get_defaults(r, emission=emission)
    flows = sorted(defaults["sampleFraction"].unique())

    fig, ax = plt.subplots(figsize=(14, 6))
    ax.set_title(f"Yield per staked PAPER — summary (startDay=0, stakerPct=2%, ADL off){_adl_label(adl)}{_em_label(emission)}",
                 fontsize=13, fontweight="bold")
    ax.axis("off")

    col_labels = [f"{f:.0%} flow" for f in flows]
    row_labels = []
    cell_data = []

    for sf in STAKED_FRACTIONS:
        row_labels.append(f"{sf:.0%} staked")
        row = []
        for flow in flows:
            mask = ((defaults["sampleFraction"] == flow) &
                    (defaults["startDay"] == 0) &
                    (defaults["adlWorstCase"] == adl))
            data = defaults[mask]
            if data.empty:
                row.append("--")
            else:
                d = data.iloc[0]
                paper = d["finalPaper"]
                stakers = d["finalStakers"]
                if paper > 0:
                    y = stakers / (paper * sf)
                    row.append(f"${y:.4f}")
                else:
                    row.append("--")
        cell_data.append(row)

    # Add extra rows: total PAPER, total staker fees, LP final
    row_labels.append("PAPER minted")
    row = []
    for flow in flows:
        mask = ((defaults["sampleFraction"] == flow) &
                (defaults["startDay"] == 0) &
                (defaults["adlWorstCase"] == adl))
        data = defaults[mask]
        if data.empty:
            row.append("--")
        else:
            p = data.iloc[0]["finalPaper"]
            if p >= 1e6:
                row.append(f"{p/1e6:.0f}M")
            else:
                row.append(f"{p:,.0f}")
    cell_data.append(row)

    row_labels.append("Staker fees ($)")
    row = []
    for flow in flows:
        mask = ((defaults["sampleFraction"] == flow) &
                (defaults["startDay"] == 0) &
                (defaults["adlWorstCase"] == adl))
        data = defaults[mask]
        if data.empty:
            row.append("--")
        else:
            s = data.iloc[0]["finalStakers"]
            if abs(s) >= 1e6:
                row.append(f"${s/1e6:.1f}M")
            elif abs(s) >= 1e3:
                row.append(f"${s/1e3:.0f}K")
            else:
                row.append(f"${s:.0f}")
    cell_data.append(row)

    row_labels.append("Final LP ($)")
    row = []
    for flow in flows:
        mask = ((defaults["sampleFraction"] == flow) &
                (defaults["startDay"] == 0) &
                (defaults["adlWorstCase"] == adl))
        data = defaults[mask]
        if data.empty:
            row.append("--")
        else:
            lp = data.iloc[0]["finalLp"]
            if abs(lp) >= 1e6:
                row.append(f"${lp/1e6:.1f}M")
            elif abs(lp) >= 1e3:
                row.append(f"${lp/1e3:.0f}K")
            else:
                row.append(f"${lp:.0f}")
    cell_data.append(row)

    table = ax.table(cellText=cell_data, rowLabels=row_labels,
                     colLabels=col_labels, loc="center",
                     cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.5)

    # Color header
    for j in range(len(col_labels)):
        table[0, j].set_facecolor("#e8e8e8")
    for i in range(len(row_labels)):
        table[i + 1, -1].set_facecolor("#f5f5f5")

    fig.tight_layout()
    fig.savefig(out / f"12_yield_table{adl_sfx}{suf}.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# Chart 15: Trader losses over time (cumulative, time-series)
# =========================================================================
def plot_trader_loss_timeseries(r, daily_traderloss, out: Path, emission=False, adl=False):
    """Cumulative trader losses over time for different flow rates and start days."""
    suf = ""; adl_sfx = "_adl" if adl else ""
    if daily_traderloss is None:
        print("  (skipping trader loss timeseries — batch_daily_traderloss.csv not found;"
              " re-run batch_simulate.py to generate it)")
        return

    defaults = get_defaults(r, emission=emission)
    flows    = sorted(defaults["sampleFraction"].unique())
    dates    = [day_to_date(d) for d in range(SIM_DAYS)]

    # 1 panel: startDay=0, all flows  (daily cumulative losses over time)
    fig, axes = plt.subplots(1, 2, figsize=(18, 6))
    fig.suptitle(f"Cumulative trader losses over time  (default params, ADL off){_adl_label(adl)}{_em_label(emission)}\n"
                 "This shows HOW FAST traders lose money day-by-day, not by launch date",
                 fontsize=12, fontweight="bold")

    ax = axes[0]
    ax.set_title("startDay=0 — 4 flow rates")
    for flow in flows:
        mask = ((defaults["sampleFraction"] == flow) &
                (defaults["startDay"] == 0) &
                (defaults["adlWorstCase"] == adl))
        subset = defaults[mask]
        if subset.empty:
            continue
        sid = subset.iloc[0]["scenario_id"]
        if sid not in daily_traderloss.index:
            continue
        ax.plot(dates, daily_traderloss.loc[sid].values.astype(float),
                color=FLOW_COLORS.get(flow, "#333"), lw=2,
                label=FLOW_LABELS.get(flow, f"{flow:.0%}"))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
    dates_axis(ax)
    ax.set_ylabel("Cumulative trader losses ($)")
    ax.legend(fontsize=8)

    # 2nd panel: 100% flow, several start days
    ax = axes[1]
    ax.set_title("100% flow — multiple launch dates")
    mask_base = ((defaults["sampleFraction"] == 1.0) &
                 (defaults["adlWorstCase"] == adl))
    start_days_to_show = [0, 28, 56, 84, 112, 140, 168]
    cmap = plt.cm.viridis
    for i, sd in enumerate(start_days_to_show):
        mask = mask_base & (defaults["startDay"] == sd)
        subset = defaults[mask]
        if subset.empty:
            continue
        sid = subset.iloc[0]["scenario_id"]
        if sid not in daily_traderloss.index:
            continue
        color = cmap(i / max(1, len(start_days_to_show) - 1))
        ax.plot(dates, daily_traderloss.loc[sid].values.astype(float),
                color=color, lw=1.8, label=f"launch d{sd}")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
    dates_axis(ax)
    ax.set_ylabel("Cumulative trader losses ($)")
    ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out / f"15_trader_loss_timeseries{adl_sfx}{suf}.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# Chart 16: LP paths for ALL parameter combinations
# =========================================================================
def plot_lp_all_params(r, daily_lp, out: Path, emission=False, adl=False):
    """LP balance over time for every (base_rate × btcRefN × ethRefN) at startDay=0."""
    suf = ""; adl_sfx = "_adl" if adl else ""
    if daily_lp is None:
        return

    from matplotlib.lines import Line2D

    BASE_RATES = sorted(r["btcBaseRate"].unique())
    dates      = [day_to_date(d) for d in range(SIM_DAYS)]

    br_colors = {0.02: "#1769e0", 0.03: "#18936a", 0.05: "#e05f2b",
                 0.07: "#a855f7", 0.10: "#d62728"}

    flows = sorted(r["sampleFraction"].unique())
    n_flows = len(flows)

    fig, axes = plt.subplots(1, n_flows, figsize=(6 * n_flows, 7), sharey=True)
    if n_flows == 1:
        axes = [axes]
    em_tag = "emission-based volume" if emission else "base model (no emission decay)"
    fig.suptitle(f"LP recovery — all parameter combinations (startDay=0, ADL off, {em_tag})\n"
                 "Color = base rate | Line style = BTC refNotional | all ETH refNotional overlaid",
                 fontsize=12, fontweight="bold")

    btc_rns     = sorted(r["btcReferenceNotional"].unique())
    rn_styles   = dict(zip(btc_rns, ["-", "--", ":"]))
    rn_widths   = dict(zip(btc_rns, [1.8, 1.5, 1.2]))

    for ax, flow in zip(axes, flows):
        ax.set_title(FLOW_LABELS.get(flow, f"{flow:.0%} flow"))
        mask_base = ((r["startDay"] == 0) &
                     (r["adlWorstCase"] == adl) &
                     (r["emissionBased"] == emission) &
                     (r["sampleFraction"] == flow))
        subset = r[mask_base]

        for _, row in subset.iterrows():
            sid = row["scenario_id"]
            if sid not in daily_lp.index:
                continue
            br  = row["btcBaseRate"]
            rn  = row["btcReferenceNotional"]
            lp  = daily_lp.loc[sid].values.astype(float)
            lp_plot = np.where(lp > 0, lp, 1.0)
            ax.plot(dates, lp_plot,
                    color=br_colors.get(br, "#888"),
                    ls=rn_styles.get(rn, "-"),
                    lw=rn_widths.get(rn, 1.0),
                    alpha=0.55)

        ax.axhline(5_000_000, color="#9a6b16", ls="--", lw=1, alpha=0.4)
        ax.axhline(2_000_000, color="#59636f", ls="--", lw=1, alpha=0.3)
        ax.set_yscale("log")
        ax.set_ylim(1, 8_000_000)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
        dates_axis(ax)

    axes[0].set_ylabel("LP balance (log)")

    # Legend outside plots
    br_handles = [Line2D([0],[0], color=br_colors[br], lw=2, label=f"br={br:.0%}")
                  for br in BASE_RATES]
    rn_handles = [Line2D([0],[0], color="black", lw=rn_widths[rn], ls=rn_styles[rn],
                          label=f"btcRN=${rn/1e3:.0f}K")
                  for rn in btc_rns]
    fig.legend(handles=br_handles + rn_handles,
               loc="lower center", ncol=len(br_handles) + len(rn_handles),
               fontsize=8, bbox_to_anchor=(0.5, -0.04))

    fig.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(out / f"16_lp_all_params{adl_sfx}{suf}.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# Chart 17: Fastest-to-$5M table
# =========================================================================
def plot_fastest_5m_table(r, daily_lp, out: Path, emission=False, adl=False):
    """Table: which param combo reaches LP ≥ $5M fastest, by flow rate."""
    suf     = ""
    adl_sfx = "_adl" if adl else ""
    adl_tag = "ADL on" if adl else "ADL off"
    if daily_lp is None:
        return

    LP_CAP = 5_000_000.0
    flows  = sorted(r["sampleFraction"].unique())
    dates  = [day_to_date(d) for d in range(SIM_DAYS)]

    rows_data = []
    for _, row in r.iterrows():
        if (row["startDay"] != 0
                or (row["adlWorstCase"] != adl)
                or (row["emissionBased"] != emission)):
            continue
        sid = row["scenario_id"]
        if sid not in daily_lp.index:
            continue
        lp_vals = daily_lp.loc[sid].values.astype(float)
        hit_idx = np.argmax(lp_vals >= LP_CAP)
        if lp_vals[hit_idx] < LP_CAP:
            days_to_5m = None   # never reached
        else:
            days_to_5m = int(hit_idx)
        rows_data.append({
            "flow":    float(row["sampleFraction"]),
            "br":      float(row["btcBaseRate"]),
            "btcRN":   float(row["btcReferenceNotional"]),
            "ethRN":   float(row["ethReferenceNotional"]),
            "days_to_5m": days_to_5m,
            "finalLp": float(row["finalLp"]),
        })

    df = pd.DataFrame(rows_data)
    df = df[df["days_to_5m"].notna()]
    if df.empty:
        print("  (fastest-$5M table: no scenario reached $5M)")
        return

    # Best (fastest) per flow
    best = df.sort_values("days_to_5m").groupby("flow").first().reset_index()
    # Worst (slowest that still made it) per flow
    worst = df.sort_values("days_to_5m", ascending=False).groupby("flow").first().reset_index()

    fig, ax = plt.subplots(figsize=(16, 6))
    ax.set_title(f"Fastest vs slowest parameter combo to reach LP ≥ $5M  [{adl_tag}]{_adl_label(adl)}{_em_label(emission)}\n"
                 f"(startDay=0, {adl_tag} — among combos that DID reach $5M)",
                 fontsize=12, fontweight="bold")
    ax.axis("off")

    col_labels = ["Flow", "Fastest: params",
                  "Days to $5M", "Date reached",
                  "Slowest: params", "Days to $5M", "Date reached"]

    cell_data = []
    for flow in sorted(df["flow"].unique()):
        b = best[best["flow"] == flow]
        w = worst[worst["flow"] == flow]
        def param_str(sub):
            if sub.empty:
                return "–"
            s = sub.iloc[0]
            return f"br={s['br']:.0%} btcRN=${s['btcRN']/1e3:.0f}K ethRN=${s['ethRN']/1e3:.0f}K"
        def days_str(sub):
            if sub.empty:
                return "–"
            d = sub.iloc[0]["days_to_5m"]
            return f"{int(d)} days"
        def date_str(sub):
            if sub.empty:
                return "–"
            d = int(sub.iloc[0]["days_to_5m"])
            return dates[d].strftime("%Y-%m-%d") if d < len(dates) else "–"

        cell_data.append([
            f"{flow:.0%}",
            param_str(b), days_str(b), date_str(b),
            param_str(w), days_str(w), date_str(w),
        ])

    table = ax.table(cellText=cell_data, colLabels=col_labels,
                     loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 2.0)
    for j in range(len(col_labels)):
        table[0, j].set_facecolor("#d0d8e8")
    for i in range(1, len(cell_data) + 1):
        for j in range(len(col_labels)):
            table[i, j].set_facecolor("#f5f5f5" if i % 2 == 0 else "white")

    fig.tight_layout()
    fig.savefig(out / f"17_fastest_5m_table{adl_sfx}{suf}.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# Chart 18: Yield per PAPER over time (cumulative, time-series)
# =========================================================================
def plot_yield_per_paper_timeseries(r, daily_paper, daily_stakers, out: Path, emission=False, adl=False):
    """Cumulative USDC yield per staked PAPER as it accumulates over time."""
    suf = ""; adl_sfx = "_adl" if adl else ""
    if daily_paper is None or daily_stakers is None:
        print("  (skipping yield-per-paper timeseries — missing daily CSVs)")
        return

    defaults = get_defaults(r, emission=emission)
    flows    = sorted(defaults["sampleFraction"].unique())
    dates    = [day_to_date(d) for d in range(SIM_DAYS)]

    fig, axes = plt.subplots(1, 2, figsize=(18, 6))
    fig.suptitle(f"Cumulative yield per staked PAPER over time{_adl_label(adl)}{_em_label(emission)}\n"
                 "(startDay=0, default params, ADL off)",
                 fontsize=13, fontweight="bold")

    for ax_idx, sf in enumerate([0.20, 0.50]):
        ax = axes[ax_idx]
        ax.set_title(f"Assuming {sf:.0%} of PAPER is staked")
        for flow in flows:
            mask = ((defaults["sampleFraction"] == flow) &
                    (defaults["startDay"] == 0) &
                    (defaults["adlWorstCase"] == adl))
            subset = defaults[mask]
            if subset.empty:
                continue
            sid = subset.iloc[0]["scenario_id"]
            if sid not in daily_paper.index or sid not in daily_stakers.index:
                continue
            paper   = daily_paper.loc[sid].values.astype(float)
            stakers = daily_stakers.loc[sid].values.astype(float)
            # Avoid division by zero in early days when paper is 0
            staked_supply = paper * sf
            yield_per = np.where(staked_supply > 0, stakers / staked_supply, 0.0)
            ax.plot(dates, yield_per,
                    color=FLOW_COLORS.get(flow, "#333"), lw=2,
                    label=FLOW_LABELS.get(flow, f"{flow:.0%}"))

        ax.yaxis.set_major_formatter(mticker.FuncFormatter(yield_fmt))
        dates_axis(ax)
        ax.set_ylabel("Cumulative yield per staked PAPER ($)")
        ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out / f"18_yield_per_paper_timeseries{adl_sfx}{suf}.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# Chart 19: PAPER front-loading analysis
#   No rerun needed — computed entirely from batch_daily_paper.csv and
#   batch_daily_tail.csv that already exist.
#
#   Metrics:
#     a) % PAPER minted in first 90 days  (hard cutoff)
#     b) % PAPER minted before marginal cost doubled ($0.01 → $0.02)
#        i.e. before tail_progress ≥ S*(1/√2 − 1) ≈ $49.7M
#     c) Day when cost doubled, by launch date and flow
#     d) Concentration curve: cumulative % PAPER vs day (for startDay=0)
# =========================================================================
def plot_paper_frontloading(r, daily_paper, daily_tail, out: Path,
                             emission=False, adl=False, overlay_both=False):
    """
    Show that early losers received the bulk of PAPER.

    overlay_both=False (default): single emission mode, 4 lines per panel.
    overlay_both=True : both emission modes on same panels — 8 lines each.
      Solid lines = base model, dashed = emission-based volume.
      Saves as 19_paper_frontloading{adl_sfx}_overlay.png in `out`.
    """
    suf = ""; adl_sfx = "_adl" if adl else ""
    if daily_paper is None or daily_tail is None:
        print("  (skipping front-loading chart — need batch_daily_paper + batch_daily_tail)")
        return

    S         = 120_000_000.0
    FLAT_RATE = 100.0
    TAIL_2X   = S * (1.0 / np.sqrt(0.5) - 1.0)   # ≈ $49.7M
    TAIL_4X   = S * (1.0 / np.sqrt(0.25) - 1.0)  # ≈ $120M

    # Determine which emission modes to plot
    em_modes  = [False, True] if overlay_both else [emission]
    em_ls     = {False: "-", True: "--"}   # solid = base, dashed = emission
    em_lw     = {False: 2.0, True: 1.6}
    em_alpha  = {False: 0.90, True: 0.70}
    em_label_suffix = {False: " (base)", True: " (em)"}

    flows     = sorted(get_defaults(r, emission=False)["sampleFraction"].unique())
    dates_all = [day_to_date(d) for d in range(SIM_DAYS)]

    fl_colors = {0.25: "#a855f7", 0.50: "#f7931a", 0.75: "#1769e0", 1.0: "#18936a"}
    fl_labels = {0.25: "25% flow", 0.50: "50% flow", 0.75: "75% flow", 1.0: "100% flow"}

    # ── pre-compute per scenario for each emission mode ──
    data_by_em = {}
    for em in em_modes:
        defaults = get_defaults(r, emission=em)
        defaults = defaults[defaults["adlWorstCase"] == adl]
        rows = []
        for _, row in defaults.iterrows():
            sid = row["scenario_id"]
            fl  = float(row["sampleFraction"])
            sd  = int(row["startDay"])
            if sid not in daily_paper.index or sid not in daily_tail.index:
                continue
            p = daily_paper.loc[sid].values.astype(float)
            t = daily_tail.loc[sid].values.astype(float)
            p_final = p[SIM_DAYS - 1]
            if p_final <= 0:
                continue

            day90 = min(sd + 90, SIM_DAYS - 1)
            pct_90 = 100.0 * p[day90] / p_final

            t_from_launch = t[sd:]
            hit_2x = np.argmax(t_from_launch >= TAIL_2X)
            if t_from_launch[hit_2x] < TAIL_2X:
                day_2x_from_launch = None
                pct_before_2x = 100.0
            else:
                day_2x_from_launch = int(hit_2x)
                pct_before_2x = 100.0 * p[sd + hit_2x] / p_final

            rows.append({"flow": fl, "startDay": sd,
                         "pct_90d": pct_90,
                         "day_2x_from_launch": day_2x_from_launch,
                         "pct_before_2x": pct_before_2x})

        df = pd.DataFrame(rows)
        if df.empty:
            continue
        data_by_em[em] = (df, defaults)

    if not data_by_em:
        print("  (front-loading: no matching scenarios)")
        return

    # ── Figure ──
    adl_tag = _adl_label(adl)
    if overlay_both:
        title_em = "  —  Base (solid) vs Emission-based (dashed)"
        fname    = f"19_paper_frontloading{adl_sfx}_overlay.png"
    else:
        title_em = _em_label(emission)
        fname    = f"19_paper_frontloading{adl_sfx}{suf}.png"

    fig = plt.figure(figsize=(20, 16))
    fig.suptitle(
        f"PAPER front-loading: early losers captured the bulk of emissions{adl_tag}{title_em}\n"
        f"Cost-doubled threshold: tail progress ≥ ${TAIL_2X/1e6:.1f}M  "
        f"(marginal rate drops from 100 to 50 PAPER/$  →  cost per PAPER: $0.01→$0.02)",
        fontsize=12, fontweight="bold"
    )
    gs = fig.add_gridspec(2, 2, hspace=0.38, wspace=0.28)
    ax_a = fig.add_subplot(gs[0, 0])
    ax_b = fig.add_subplot(gs[0, 1])
    ax_c = fig.add_subplot(gs[1, 0])
    ax_d = fig.add_subplot(gs[1, 1])

    ax_a.set_title("A.  % of total PAPER minted within 90 days of launch", fontsize=10)
    ax_b.set_title("B.  % of total PAPER minted BEFORE marginal cost doubled ($0.01→$0.02)", fontsize=10)
    ax_c.set_title("C.  Days from launch until marginal cost doubled (never = $0.01 floor holds)", fontsize=10)
    ax_d.set_title("D.  Concentration curve: cumulative % PAPER minted over time\n"
                   "(startDay=0 — shows HOW FAST PAPER was minted)", fontsize=10)

    first_em_for_annotation = True

    for em, (df, defaults_em) in data_by_em.items():
        ls    = em_ls[em]
        lw    = em_lw[em]
        alpha = em_alpha[em]
        lbl_sfx = em_label_suffix[em] if overlay_both else ""

        # Panel A
        for fl in flows:
            d = df[np.isclose(df["flow"], fl)].sort_values("startDay")
            x = [day_to_date(int(sd)) for sd in d["startDay"]]
            ax_a.plot(x, d["pct_90d"], color=fl_colors[fl], lw=lw,
                      ls=ls, alpha=alpha,
                      label=fl_labels[fl] + lbl_sfx)

        # Panel B
        for fl in flows:
            d = df[np.isclose(df["flow"], fl)].sort_values("startDay")
            x = [day_to_date(int(sd)) for sd in d["startDay"]]
            ax_b.plot(x, d["pct_before_2x"], color=fl_colors[fl], lw=lw,
                      ls=ls, alpha=alpha,
                      label=fl_labels[fl] + lbl_sfx)

        # Panel C
        for fl in flows:
            d = df[np.isclose(df["flow"], fl)].sort_values("startDay")
            d_hit = d[d["day_2x_from_launch"].notna()]
            d_no  = d[d["day_2x_from_launch"].isna()]
            if not d_hit.empty:
                x = [day_to_date(int(sd)) for sd in d_hit["startDay"]]
                ax_c.plot(x, d_hit["day_2x_from_launch"], color=fl_colors[fl],
                          lw=lw, ls=ls, alpha=alpha,
                          label=fl_labels[fl] + lbl_sfx)
            if not d_no.empty:
                x_no = [day_to_date(int(sd)) for sd in d_no["startDay"]]
                ax_c.scatter(x_no, [SIM_DAYS] * len(d_no), color=fl_colors[fl],
                             marker="x", s=40, alpha=alpha * 0.6)

        # Panel D — concentration curve (startDay=0)
        annotated_d = False
        for fl in flows:
            d0 = defaults_em[(np.isclose(defaults_em["sampleFraction"], fl)) &
                              (defaults_em["startDay"] == 0)]
            if d0.empty:
                continue
            sid = d0.iloc[0]["scenario_id"]
            if sid not in daily_paper.index:
                continue
            p_vals = daily_paper.loc[sid].values.astype(float)
            p_final = p_vals[SIM_DAYS - 1]
            if p_final <= 0:
                continue
            cum_pct = 100.0 * p_vals / p_final
            ax_d.plot(dates_all, cum_pct, color=fl_colors[fl], lw=lw,
                      ls=ls, alpha=alpha, label=fl_labels[fl] + lbl_sfx)

            # Annotate cost thresholds once (first emission mode, first flow)
            if first_em_for_annotation and not annotated_d and sid in daily_tail.index:
                t_vals = daily_tail.loc[sid].values.astype(float)
                for thresh, tlabel, tcol in [(TAIL_2X, "cost ×2", "#e05f2b"),
                                              (TAIL_4X, "cost ×4", "#d62728")]:
                    hit = np.argmax(t_vals >= thresh)
                    if t_vals[hit] >= thresh:
                        ax_d.axvline(dates_all[hit], color=tcol, ls=":", lw=1.2, alpha=0.7)
                        ax_d.text(dates_all[hit], 5, f"  {tlabel}\n  d{hit}",
                                  fontsize=7, color=tcol)
                annotated_d = True
        first_em_for_annotation = False

    # ── Shared formatting ──
    for ax in [ax_a, ax_b]:
        ax.axhline(50, color="black", ls="--", lw=0.8, alpha=0.4)
        ax.set_ylabel("% of total PAPER")
        ax.set_ylim(0, 105)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
        dates_axis(ax)
        ax.legend(fontsize=7 if overlay_both else 8)
    ax_b.axhline(50, color="gray", ls="--", lw=0.8, alpha=0.4, label="50% mark")

    ax_c.set_ylabel("Days from launch")
    ax_c.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x)}d"))
    ax_c.set_ylim(bottom=0)
    dates_axis(ax_c)
    ax_c.legend(fontsize=7 if overlay_both else 8)

    ax_d.axhline(50, color="black", ls="--", lw=0.8, alpha=0.4)
    ax_d.set_ylabel("% of total PAPER minted")
    ax_d.set_ylim(0, 105)
    ax_d.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    dates_axis(ax_d)
    ax_d.legend(fontsize=7 if overlay_both else 8, loc="lower right")

    # ── Callout annotation (base model, 100% flow, startDay=0) ──
    base_df = data_by_em.get(False, data_by_em.get(emission, (pd.DataFrame(), None)))[0]
    kn = base_df[(np.isclose(base_df["flow"], 1.0)) & (base_df["startDay"] == 0)]
    if not kn.empty and kn.iloc[0]["day_2x_from_launch"] is not None:
        kn = kn.iloc[0]
        callout = (
            f"100% flow, startDay=0  (base model):\n"
            f"  {kn['pct_90d']:.1f}% of PAPER in first 90 days\n"
            f"  {kn['pct_before_2x']:.1f}% before cost doubled (day {int(kn['day_2x_from_launch'])})\n"
            f"  → first losers captured the bulk"
        )
        fig.text(0.01, 0.01, callout, fontsize=9,
                 bbox=dict(boxstyle="round,pad=0.4", facecolor="#fff9c4", edgecolor="#f0ad00"),
                 verticalalignment="bottom")

    if overlay_both:
        from matplotlib.lines import Line2D
        legend_handles = [
            Line2D([0], [0], color="black", lw=2.0, ls="-",  label="Base model (solid)"),
            Line2D([0], [0], color="black", lw=1.6, ls="--", label="Emission-based (dashed)"),
        ]
        fig.legend(handles=legend_handles, loc="lower right",
                   bbox_to_anchor=(0.99, 0.01), fontsize=9,
                   framealpha=0.9, title="Line style")

    fig.savefig(out / fname, bbox_inches="tight")
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

    def _load_daily(name):
        p = args.dir / name
        return pd.read_csv(p, index_col=0) if p.exists() else None

    daily_lp          = _load_daily("batch_daily_lp.csv")
    daily_paper       = _load_daily("batch_daily_paper.csv")
    daily_stakers     = _load_daily("batch_daily_stakers.csv")
    daily_tail        = _load_daily("batch_daily_tail.csv")
    daily_traderloss  = _load_daily("batch_daily_traderloss.csv")

    out    = args.dir / "charts"
    out_em = args.dir / "charts_emission"
    out.mkdir(exist_ok=True)
    out_em.mkdir(exist_ok=True)

    n = len(results)
    flows = sorted(results["sampleFraction"].unique())
    print(f"Loaded {n} scenarios, flows: {flows}")

    out_cmp = args.dir / "charts_comparison"
    out_cmp.mkdir(exist_ok=True)

    for em, out_dir in [(False, out), (True, out_em)]:
        tag = "emission" if em else "base"
        for adl in [False, True]:
            plot_yield_by_flow(results, out_dir, emission=em, adl=adl)
            plot_paper_by_flow(results, out_dir, emission=em, adl=adl)
            plot_lp_by_flow(results, daily_lp, out_dir, emission=em, adl=adl)
            plot_yield_table(results, out_dir, emission=em, adl=adl)
            plot_cumulative_timeseries(results, daily_paper, daily_stakers, out_dir, emission=em, adl=adl)
            plot_cost_per_paper_timeseries(results, daily_tail, out_dir, emission=em, adl=adl)
            plot_trader_loss_timeseries(results, daily_traderloss, out_dir, emission=em, adl=adl)
            plot_lp_all_params(results, daily_lp, out_dir, emission=em, adl=adl)
            plot_fastest_5m_table(results, daily_lp, out_dir, emission=em, adl=adl)
            plot_yield_per_paper_timeseries(results, daily_paper, daily_stakers, out_dir, emission=em, adl=adl)
            plot_paper_frontloading(results, daily_paper, daily_tail, out_dir, emission=em, adl=adl)
    # Overlay version: both models on same 4 panels (8 lines each)
    for adl in [False, True]:
        plot_paper_frontloading(results, daily_paper, daily_tail, out_cmp,
                                emission=False, adl=adl, overlay_both=True)
        print(f"  09-19  [{tag}] ADL off + ADL on → {out_dir}/")

    # ── comparison grids ──
    cmp_specs = [
        ("09_yield_by_flow",              "Yield per staked PAPER by launch date"),
        ("10_paper_by_flow",              "PAPER emissions & cost by launch date"),
        ("11_lp_by_flow",                 "LP balance by flow %"),
        ("12_yield_table",                "Yield summary table"),
        ("13_cumulative_timeseries",      "Cumulative PAPER + staker fees"),
        ("14_cost_per_paper_timeseries",  "Marginal cost per PAPER"),
        ("16_lp_all_params",              "LP all parameter combinations"),
        ("17_fastest_5m_table",           "Fastest to LP $5M table"),
        ("18_yield_per_paper_timeseries", "Yield per PAPER over time"),
        ("19_paper_frontloading",         "PAPER front-loading analysis"),
    ]

    # ── Vertical stacks: emission on top, base below ──
    for adl in [False, True]:
        adl_sfx = "_adl" if adl else ""
        adl_tag = "ADL on" if adl else "ADL off"
        for stub, title in [
            ("19_paper_frontloading", "PAPER front-loading"),
            ("10_paper_by_flow",      "PAPER emissions & cost"),
            ("13_cumulative_timeseries", "Cumulative PAPER + staker fees"),
            ("18_yield_per_paper_timeseries", "Yield per staked PAPER"),
        ]:
            _make_comparison_grid(
                paths=[out_em / f"{stub}{adl_sfx}.png",
                       out    / f"{stub}{adl_sfx}.png"],
                labels=["Emission-based volume", "Base model"],
                out_path=out_cmp / f"{stub}{adl_sfx}_stacked.png",
                suptitle=f"{title}  [{adl_tag}]  —  Emission (top) vs Base (bottom)",
                vertical=True,
            )
    print(f"  Vertical stacks (emission/base)  → {out_cmp}/")
    for stub, title in cmp_specs:
        _make_comparison_grid(
            paths=[out    / f"{stub}.png",     out    / f"{stub}_adl.png",
                   out_em / f"{stub}.png",     out_em / f"{stub}_adl.png"],
            labels=["Base  |  ADL off", "Base  |  ADL on",
                    "Emission  |  ADL off", "Emission  |  ADL on"],
            out_path=out_cmp / f"{stub}.png",
            suptitle=f"{title}  —  2×2 comparison (emission rows × ADL columns)"
        )
    print(f"  Comparison grids  → {out_cmp}/  ({len(cmp_specs)} charts)")

    print(f"\nBase     → {out}/")
    print(f"Emission → {out_em}/")
    print(f"Compare  → {out_cmp}/")


if __name__ == "__main__":
    main()
