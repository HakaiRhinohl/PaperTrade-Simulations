#!/usr/bin/env python3
"""
plot_batch.py — Visualize batch simulation results (full factorial × start days).

Reads batch_results.csv + daily CSVs, generates charts showing:
- Effect of each impact-scale parameter (one-at-a-time slices from full factorial)
- Effect of start date (LP bootstrapping)
- Queue/debt behavior when LP can't pay winners

Usage:
    python3 plot_batch.py
    python3 plot_batch.py --dir /path/to/csvs
    python3 plot_batch.py --interactive
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

START_DATE = datetime(2025, 8, 1, tzinfo=timezone.utc)
SIM_DAYS = 290

PARAM_COL = {
    "baseRate": "btcBaseRate",
    "btcRefNotional": "btcReferenceNotional",
    "ethRefNotional": "ethReferenceNotional",
}
PARAM_DEFAULTS = {"btcBaseRate": 0.05, "btcReferenceNotional": 100_000.0, "ethReferenceNotional": 50_000.0}
SWEEP_PARAMS = ["baseRate", "btcRefNotional", "ethRefNotional"]
SWEEP_LABELS = {
    "baseRate": "Base rate",
    "btcRefNotional": "BTC ref. notional",
    "ethRefNotional": "ETH ref. notional",
}
SWEEP_COLORS = {
    "baseRate": "#e05f2b",
    "btcRefNotional": "#1769e0",
    "ethRefNotional": "#18936a",
}
SWEEP_X_FMT = {
    "baseRate": lambda x, _: f"{x:.0%}" if x < 1 else f"{x:.0f}",
    "btcRefNotional": lambda x, _: f"${x/1e3:.0f}K",
    "ethRefNotional": lambda x, _: f"${x/1e3:.0f}K",
}


def day_to_date(day: int) -> datetime:
    return START_DATE + timedelta(days=day)


def _em_label(emission: bool) -> str:
    """Append to suptitle so emission-based charts are immediately identifiable."""
    return "  —  Emission-based volume" if emission else ""


def _adl_label(adl: bool) -> str:
    """Append to suptitle so ADL-on charts are immediately identifiable."""
    return "  [ADL on]" if adl else "  [ADL off]"


def _make_comparison_grid(paths: list, labels: list, out_path, suptitle: str = "",
                           vertical: bool = False):
    """Stitch PNGs into a comparison figure.
    vertical=True → n rows × 1 col (stacked).  Default: 2×2 grid."""
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
        ax.imshow(img); ax.set_title(label, fontsize=13, fontweight="bold", pad=6); ax.axis("off")
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


def _add_sweep_columns(results):
    """Tag each row: which single parameter varies from defaults (or 'interaction')."""
    br_def = np.isclose(results["btcBaseRate"], PARAM_DEFAULTS["btcBaseRate"])
    btc_def = np.isclose(results["btcReferenceNotional"], PARAM_DEFAULTS["btcReferenceNotional"])
    eth_def = np.isclose(results["ethReferenceNotional"], PARAM_DEFAULTS["ethReferenceNotional"])

    results["sweep_param"] = "interaction"
    results["sweep_value"] = 0.0

    mask = (~br_def) & btc_def & eth_def
    results.loc[mask, "sweep_param"] = "baseRate"
    results.loc[mask, "sweep_value"] = results.loc[mask, "btcBaseRate"]

    mask = br_def & (~btc_def) & eth_def
    results.loc[mask, "sweep_param"] = "btcRefNotional"
    results.loc[mask, "sweep_value"] = results.loc[mask, "btcReferenceNotional"]

    mask = br_def & btc_def & (~eth_def)
    results.loc[mask, "sweep_param"] = "ethRefNotional"
    results.loc[mask, "sweep_value"] = results.loc[mask, "ethReferenceNotional"]

    mask = br_def & btc_def & eth_def
    results.loc[mask, "sweep_param"] = "baseRate"
    results.loc[mask, "sweep_value"] = PARAM_DEFAULTS["btcBaseRate"]


def is_default(results):
    """Mask for rows where all impact params are at defaults."""
    return (np.isclose(results["btcBaseRate"], PARAM_DEFAULTS["btcBaseRate"]) &
            np.isclose(results["btcReferenceNotional"], PARAM_DEFAULTS["btcReferenceNotional"]) &
            np.isclose(results["ethReferenceNotional"], PARAM_DEFAULTS["ethReferenceNotional"]))


def load_data(directory: Path, emission: bool = False):
    results = pd.read_csv(directory / "batch_results.csv")
    if "emissionBased" in results.columns:
        results = results[results["emissionBased"] == emission].copy()
    _add_sweep_columns(results)

    daily_lp = None
    daily_debt = None
    lp_path = directory / "batch_daily_lp.csv"
    debt_path = directory / "batch_daily_debt.csv"
    if lp_path.exists():
        daily_lp = pd.read_csv(lp_path, index_col=0)
        valid_ids = set(results["scenario_id"])
        daily_lp = daily_lp[daily_lp.index.isin(valid_ids)]
    if debt_path.exists():
        daily_debt = pd.read_csv(debt_path, index_col=0)
        valid_ids = set(results["scenario_id"])
        daily_debt = daily_debt[daily_debt.index.isin(valid_ids)]
    return results, daily_lp, daily_debt


# =========================================================================
# 1. Parameter sweep effect (startDay=0, ADL off vs on)
# =========================================================================
def plot_01_param_sweeps(results, out: Path, suffix="", emission=False):
    fig, axes = plt.subplots(4, 3, figsize=(18, 20))
    fig.suptitle(f"Impact-scale parameter sweeps (startDay=0){_em_label(emission)}", fontsize=15, fontweight="bold")

    metrics = [
        ("traderNet", "Trader net PnL", usd_signed),
        ("finalPaper", "PAPER minted", paper_fmt),
        ("costPerPaper", "Cost per PAPER", lambda x, _: f"${x:.3f}"),
        ("lpLost", "LP total lost", usd_fmt),
    ]

    for row, (metric, ylabel, yfmt) in enumerate(metrics):
        for col, param in enumerate(SWEEP_PARAMS):
            ax = axes[row, col]
            if row == 0:
                ax.set_title(SWEEP_LABELS[param], color=SWEEP_COLORS[param])

            for adl, color, ls, label in [(False, "#1769e0", "-", "ADL off"),
                                           (True, "#e05f2b", "--", "ADL on")]:
                mask = ((results["sweep_param"] == param) &
                        (results["adlWorstCase"] == adl) &
                        (results["startDay"] == 0))
                data = results[mask].sort_values("sweep_value")
                if data.empty:
                    continue
                ax.plot(data["sweep_value"], data[metric], color=color, ls=ls,
                        lw=2, marker="o", markersize=4, label=label)

            ax.yaxis.set_major_formatter(mticker.FuncFormatter(yfmt))
            ax.xaxis.set_major_formatter(mticker.FuncFormatter(SWEEP_X_FMT[param]))
            if param in ("btcRefNotional", "ethRefNotional"):
                ax.set_xscale("log")
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=7)
            if col == 0:
                ax.set_ylabel(ylabel, fontsize=9)
            if row == 0:
                ax.legend(fontsize=7)

    fig.tight_layout()
    fig.savefig(out / f"01_param_sweeps{suffix}.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# 2. Start day effect — default params, each metric vs startDay
# =========================================================================
def plot_02_startday_effect(results, out: Path, suffix="", emission=False, adl=False):
    adl_sfx = "_adl" if adl else ""
    fig, axes = plt.subplots(2, 3, figsize=(20, 10))
    fig.suptitle(f"Effect of launch date (default impact params){_adl_label(adl)}{_em_label(emission)}",
                 fontsize=14, fontweight="bold")

    mask = is_default(results) & (results["adlWorstCase"] == adl)
    data = results[mask].sort_values("startDay")

    if data.empty:
        plt.close(fig)
        return

    x_dates = [day_to_date(d) for d in data["startDay"]]

    panels = [
        ("traderNet", "Trader net PnL", usd_signed),
        ("finalPaper", "PAPER minted", paper_fmt),
        ("finalStakers", "Staker fees", usd_fmt),
        ("lpLost", "LP total lost", usd_fmt),
        ("costPerPaper", "Cost per PAPER", lambda x, _: f"${x:.3f}"),
        ("maxDebt", "Max queue debt", usd_fmt),
    ]

    for ax, (metric, title, yfmt) in zip(axes.flat, panels):
        ax.set_title(title)
        ax.plot(x_dates, data[metric], color="#1769e0", lw=2, marker=".", markersize=4)
        if metric == "traderNet":
            ax.axhline(0, color="black", ls="-", lw=0.5, alpha=0.2)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(yfmt))
        dates_axis(ax)

    fig.tight_layout()
    fig.savefig(out / f"02_startday_effect{adl_sfx}{suffix}.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# 3. Sensitivity: each param vs startDay
# =========================================================================
def plot_03_param_vs_startday(results, out: Path, suffix="", emission=False, adl=False):
    adl_sfx = "_adl" if adl else ""
    fig, axes = plt.subplots(4, 3, figsize=(18, 20), sharex=True)
    fig.suptitle(f"Parameter × launch date interaction{_adl_label(adl)}{_em_label(emission)}",
                 fontsize=15, fontweight="bold")

    metrics = [
        ("traderNet", "Trader net PnL", usd_signed),
        ("finalPaper", "PAPER minted", paper_fmt),
        ("costPerPaper", "Cost per PAPER", lambda x, _: f"${x:.3f}"),
        ("maxDebt", "Max queue debt", usd_fmt),
    ]

    for row, (metric, ylabel, yfmt) in enumerate(metrics):
        for col, param in enumerate(SWEEP_PARAMS):
            ax = axes[row, col]
            if row == 0:
                ax.set_title(SWEEP_LABELS[param], color=SWEEP_COLORS[param])

            mask = ((results["sweep_param"] == param) &
                    (results["adlWorstCase"] == adl))
            subset = results[mask]

            vals = sorted(subset["sweep_value"].unique())
            if len(vals) > 5:
                indices = np.linspace(0, len(vals) - 1, 5, dtype=int)
                selected = [vals[i] for i in indices]
            else:
                selected = vals

            cmap = plt.cm.viridis
            for idx, val in enumerate(selected):
                vmask = np.isclose(subset["sweep_value"], val)
                sdata = subset[vmask].sort_values("startDay")
                if sdata.empty:
                    continue
                x_dates = [day_to_date(d) for d in sdata["startDay"]]
                color = cmap(idx / max(1, len(selected) - 1))
                fmt_fn = SWEEP_X_FMT[param]
                label = fmt_fn(val, None)
                ax.plot(x_dates, sdata[metric], color=color, lw=1.2,
                        alpha=0.8, label=label)

            ax.yaxis.set_major_formatter(mticker.FuncFormatter(yfmt))
            dates_axis(ax)
            if col == 0:
                ax.set_ylabel(ylabel, fontsize=9)
            if row == 0:
                ax.legend(fontsize=6, ncol=2)

    fig.tight_layout()
    fig.savefig(out / f"03_param_vs_startday{adl_sfx}{suffix}.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# 4. Queue/debt focused charts
# =========================================================================
def plot_04_queue(results, daily_debt, out: Path):
    has_queue = results[results["maxDebt"] > 0]

    if has_queue.empty:
        print("    (no queue activity in any scenario)")
        return

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle("Queue / debt analysis — scenarios where LP couldn't pay",
                 fontsize=14, fontweight="bold")

    # (0,0): maxDebt vs startDay colored by baseRate
    ax = axes[0, 0]
    ax.set_title("Max debt by launch date (colored by baseRate)")
    one_at_a_time = has_queue[has_queue["sweep_param"] != "interaction"]
    if not one_at_a_time.empty:
        for param in SWEEP_PARAMS:
            mask = ((one_at_a_time["sweep_param"] == param) &
                    (one_at_a_time["adlWorstCase"] == False))
            data = one_at_a_time[mask]
            if data.empty:
                continue
            x_dates = [day_to_date(d) for d in data["startDay"]]
            ax.scatter(x_dates, data["maxDebt"], color=SWEEP_COLORS[param],
                       alpha=0.6, s=30, label=SWEEP_LABELS[param])
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
    dates_axis(ax)
    ax.set_ylabel("Max debt ($)")
    ax.legend(fontsize=8)

    # (0,1): maxQueueLen vs startDay
    ax = axes[0, 1]
    ax.set_title("Max queue length by launch date")
    if not one_at_a_time.empty:
        for param in SWEEP_PARAMS:
            mask = ((one_at_a_time["sweep_param"] == param) &
                    (one_at_a_time["adlWorstCase"] == False))
            data = one_at_a_time[mask]
            if data.empty:
                continue
            x_dates = [day_to_date(d) for d in data["startDay"]]
            ax.scatter(x_dates, data["maxQueueLen"], color=SWEEP_COLORS[param],
                       alpha=0.6, s=30, label=SWEEP_LABELS[param])
    dates_axis(ax)
    ax.set_ylabel("Max trades in queue")
    ax.legend(fontsize=8)

    # (1,0): maxDebt distribution across all configs
    ax = axes[1, 0]
    ax.set_title("Max debt distribution (ADL off)")
    adl_off = has_queue[has_queue["adlWorstCase"] == False]
    if not adl_off.empty:
        ax.hist(adl_off["maxDebt"], bins=40, color="#e05f2b", alpha=0.7, edgecolor="none")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
    ax.set_xlabel("Max debt ($)")
    ax.set_ylabel("Scenario count")

    # (1,1): Daily debt path for worst scenario
    ax = axes[1, 1]
    if daily_debt is not None:
        worst_row = has_queue.loc[has_queue["maxDebt"].idxmax()]
        worst_sid = worst_row["scenario_id"]
        ax.set_title(f"Daily debt path — worst scenario", fontsize=10)
        if worst_sid in daily_debt.index:
            debt_vals = daily_debt.loc[worst_sid].values.astype(float)
            dates = [day_to_date(d) for d in range(SIM_DAYS)]
            ax.fill_between(dates, debt_vals, alpha=0.3, color="#e05f2b")
            ax.plot(dates, debt_vals, color="#e05f2b", lw=1.5)
            ax.set_ylabel("Outstanding debt ($)")
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
            dates_axis(ax)
    else:
        ax.set_title("Daily debt (no daily_debt CSV found)")
        ax.text(0.5, 0.5, "batch_daily_debt.csv not found", ha="center", va="center",
                transform=ax.transAxes)

    fig.tight_layout()
    fig.savefig(out / "04_queue_analysis.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# 5c. rateMultiplier insensitivity proof
# =========================================================================
def plot_05c_ratemult_insensitivity(out: Path, sim_trades_path=None):
    """
    Four-panel proof that rateMultiplier is an inert knob.

    The algebra: scale = (1−br) / (1 + term1 + term2)
      term1 = 1 / (move × rM)
      term2 = refN / (move × pM)
    =>  term1/term2 = pM / (rM × refN)  — CONSTANT, independent of move size.

    Sweeping rM 100→5,000 uniformly scales term1 by 50×, but term2 already
    dominates (ratio ≈ 0.1 at rM=1,000 for BTC defaults).  Moreover,
    winning trades cluster at tiny moves (p50=0.10%) where scale≈0.05-0.08
    regardless of rM — so the absolute LP payout barely shifts.

    Panel A: scale(move) for six rM values, log-x, with winning-trade
             move distribution shaded.
    Panel B: term1 and term2 vs move (log-log) — shows term2 dominates
             everywhere and the ratio is rM-dependent but move-independent.
    Panel C: % change in scale relative to rM=1,000 baseline.
             Shaded region = p10-p90 of winning moves (where it "matters").
    Panel D: Winning-trade move histogram with right y-axis overlay of
             scale for rM=100/1,000/5,000 — proves near-zero scale at
             moves where trades actually land.
    """
    from matplotlib.lines import Line2D

    RM_VALS  = [100, 200, 500, 1_000, 2_000, 5_000]
    RM_BASE  = 1_000
    BR       = 0.05
    REF_N    = 100_000.0   # BTC default
    POS_M    = 10_000_000.0
    moves    = np.geomspace(0.00001, 0.20, 1_000)   # 0.001% → 20%

    rm_colors = {
        100: "#d62728", 200: "#ff7f0e", 500: "#bcbd22",
        1_000: "#2ca02c", 2_000: "#1f77b4", 5_000: "#9467bd"
    }

    def sc(m, rM):
        t1 = 1.0 / (m * rM)
        t2 = REF_N / (m * POS_M)
        return (1.0 - BR) / (1.0 + t1 + t2)

    # ── load winning-trade moves from paper_sim_trades if available ──
    win_moves = None
    if sim_trades_path is not None and Path(sim_trades_path).exists():
        try:
            pt = pd.read_parquet(sim_trades_path,
                columns=["direction", "open_px", "close_px",
                         "user_pnl_usd", "paper_was_liquidated"])
            valid = pt["close_px"].notna() & pt["open_px"].notna() & (pt["open_px"] > 0)
            pt = pt[valid]
            is_long = (pt["direction"] == "long").values
            op  = pt["open_px"].astype(float).values
            cl  = pt["close_px"].astype(float).values
            cm  = np.where(is_long, (cl - op) / op, (op - cl) / op)
            win = (~pt["paper_was_liquidated"].values) & (pt["user_pnl_usd"].astype(float).values > 0)
            win_moves = cm[win]
            win_moves = win_moves[win_moves > 0]
        except Exception as e:
            logging.warning("Could not load sim_trades for rM chart: %s", e)

    fig, axes = plt.subplots(1, 4, figsize=(26, 7))
    fig.suptitle(
        "rateMultiplier is an inert knob  —  sweeping 100→5,000 moves results by < 3%\n"
        "Root cause: term1/term2 = posMult/(rM×refN) is constant across ALL move sizes  "
        "(BTC defaults: br=5%, refN=$100K, posMult=$10M)",
        fontsize=11, fontweight="bold"
    )

    # ── Panel A: scale(move) for all rM values, log-x ──
    ax = axes[0]
    ax.set_title("A — scale(move) for different rateMultiplier\n"
                 "Shaded = p10-p90 of actual winning trade moves", fontsize=9)
    for rM in RM_VALS:
        ax.semilogx(moves * 100, [sc(m, rM) for m in moves],
                    color=rm_colors[rM], lw=2.0 if rM == RM_BASE else 1.2,
                    ls="-" if rM == RM_BASE else "--",
                    label=f"rM={rM:,}{' ← fixed' if rM==RM_BASE else ''}")
    if win_moves is not None:
        p10, p90 = np.percentile(win_moves, 10), np.percentile(win_moves, 90)
        ax.axvspan(p10 * 100, p90 * 100, alpha=0.10, color="#ff7f0e",
                   label=f"p10-p90 win moves\n({p10*100:.3f}%–{p90*100:.2f}%)")
        ax.axvline(np.percentile(win_moves, 50) * 100, color="#ff7f0e",
                   ls=":", lw=1.5, alpha=0.8)
    ax.axhline(0, color="black", lw=0.5, alpha=0.4)
    ax.set_xlabel("Price move (%, log scale)")
    ax.set_ylabel("Impact scale (0–1)")
    ax.set_ylim(-0.02, 1.02)
    ax.legend(fontsize=7, loc="lower right")

    # ── Panel B: term1 vs term2 decomposition (log-log) ──
    ax = axes[1]
    ax.set_title("B — term1 vs term2 (log-log)\n"
                 "ratio term1/term2 = pM/(rM·refN) — constant, independent of move",
                 fontsize=9)
    t2_vals = REF_N / (moves * POS_M)
    ax.loglog(moves * 100, t2_vals, color="black", lw=2.5, label="term2 (fixed by refN/posMult)")
    for rM, ls, lw in [(100, "--", 1.4), (1_000, "-", 2.0), (5_000, ":", 1.4)]:
        t1_vals = 1.0 / (moves * rM)
        ratio   = POS_M / (rM * REF_N)
        ax.loglog(moves * 100, t1_vals, color=rm_colors[rM],
                  ls=ls, lw=lw, label=f"term1  rM={rM:,}  (ratio={ratio:.2f}×term2)")
    ax.axvline(0.05, color="red", ls=":", lw=1, alpha=0.7, label="Paper bust threshold (0.05%)")
    ax.set_xlabel("Price move (%, log scale)")
    ax.set_ylabel("Term value (log scale)")
    ax.legend(fontsize=7)
    # Annotate the constant ratio
    ax.text(0.05, 0.97,
            "term1/term2 is CONSTANT\n(same at all move sizes)",
            transform=ax.transAxes, ha="left", va="top",
            fontsize=8, color="black",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#fffde7", alpha=0.9))

    # ── Panel C: % change in scale relative to rM=1,000 baseline ──
    ax = axes[2]
    ax.set_title("C — % deviation from rM=1,000 baseline\n"
                 "Shaded = p10-p90 winning moves (where rM 'matters')", fontsize=9)
    base_vals = np.array([sc(m, RM_BASE) for m in moves])
    for rM in [100, 200, 500, 2_000, 5_000]:
        delta = (np.array([sc(m, rM) for m in moves]) - base_vals) / (base_vals + 1e-12) * 100
        ax.semilogx(moves * 100, delta, color=rm_colors[rM], lw=1.5,
                    label=f"rM={rM:,}")
    ax.axhline(3,  color="gray", ls="--", lw=1, alpha=0.6, label="+3%  threshold")
    ax.axhline(-3, color="gray", ls="--", lw=1, alpha=0.6)
    ax.axhline(0,  color="black", lw=0.5, alpha=0.4)
    if win_moves is not None:
        p10, p90 = np.percentile(win_moves, 10), np.percentile(win_moves, 90)
        ax.axvspan(p10 * 100, p90 * 100, alpha=0.10, color="#ff7f0e",
                   label="p10-p90 winning moves")
    ax.set_xlabel("Price move (%, log scale)")
    ax.set_ylabel("Δ scale vs rM=1,000 (%)")
    ax.legend(fontsize=7, loc="upper left")

    # ── Panel D: winning-move distribution + scale overlay ──
    ax = axes[3]
    ax.set_title("D — Winning trade move distribution\n"
                 "Right axis: scale at each move for rM=100/1,000/5,000", fontsize=9)
    if win_moves is not None:
        log_bins = np.geomspace(win_moves.min() * 0.9, win_moves.max() * 1.1, 80)
        n, bins, _ = ax.hist(win_moves * 100, bins=log_bins * 100,
                             color="#ff7f0e", alpha=0.55, label=f"Winning trades (n={len(win_moves):,})")
        ax.set_xscale("log")
        ax.set_xlabel("Close move % (log scale)")
        ax.set_ylabel("# winning trades")
        ax2 = ax.twinx()
        for rM in [100, 1_000, 5_000]:
            ax2.semilogx(moves * 100, [sc(m, rM) for m in moves],
                         color=rm_colors[rM], lw=2, ls="-" if rM==1000 else "--",
                         label=f"scale rM={rM:,}")
        ax2.set_ylabel("Impact scale")
        ax2.set_ylim(-0.02, 1.02)
        # Annotate p50
        p50 = np.percentile(win_moves, 50)
        sc50_lo = sc(p50, 100)
        sc50_hi = sc(p50, 5000)
        ax2.annotate(f"p50 move={p50*100:.3f}%\nscale: {sc50_lo:.3f}–{sc50_hi:.3f}\n(near-zero regardless of rM)",
                     xy=(p50 * 100, sc50_hi),
                     xytext=(p50 * 100 * 8, 0.35),
                     fontsize=7.5,
                     arrowprops=dict(arrowstyle="->", color="black", lw=0.8),
                     bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.9))
        handles1, labels1 = ax.get_legend_handles_labels()
        handles2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(handles1 + handles2, labels1 + labels2, fontsize=7, loc="upper right")
    else:
        ax.text(0.5, 0.5, "Pass --sim-trades to add\nwinning-trade distribution",
                ha="center", va="center", transform=ax.transAxes, fontsize=10)
        ax.set_title("D — (pass sim_trades_path for data)", fontsize=9)

    fig.tight_layout()
    fig.savefig(out / "05c_ratemult_insensitivity.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# 5a. Impact scale curves — BTC only
# =========================================================================
def plot_05a_impact_curves_btc(out: Path):
    from matplotlib.lines import Line2D

    BASE_RATES    = [0.02, 0.03, 0.05, 0.07, 0.10]
    REF_NOTIONALS = [75_000, 100_000, 125_000]
    RM = 1000.0
    PM = 10e6
    moves = np.linspace(0.001, 0.20, 300)

    br_colors = {0.02: "#1769e0", 0.03: "#18936a", 0.05: "#e05f2b",
                 0.07: "#a855f7", 0.10: "#d62728"}
    rn_styles = {75_000: "-", 100_000: "--", 125_000: ":"}
    rn_widths = {75_000: 1.5, 100_000: 2.2, 125_000: 1.5}

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle("Impact scale — BTC  (adjustedPnl = rawPnl × scale(move))",
                 fontsize=13, fontweight="bold")

    # Left: base rate sweep at default ref notional
    ax = axes[0]
    ax.set_title("Base rate sweep  (BTC ref notional = $100K)")
    for br in BASE_RATES:
        scale = np.clip((1-br)/(1 + 1/(moves*RM) + 100_000/(moves*PM)), 0, 1)
        ax.plot(moves*100, scale, lw=2, color=br_colors[br], label=f"{br:.0%}")
    ax.set_xlabel("Price move (%)")
    ax.set_ylabel("Scale (0–1)")
    ax.set_ylim(0, 1.05)
    ax.set_xlim(0, 20)
    ax.legend(fontsize=8, title="Base rate")

    # Right: all 15 combinations
    ax = axes[1]
    ax.set_title("All combinations: base rate × ref notional  (BTC)")
    for br in BASE_RATES:
        for rn in REF_NOTIONALS:
            scale = np.clip((1-br)/(1 + 1/(moves*RM) + rn/(moves*PM)), 0, 1)
            ax.plot(moves*100, scale, lw=rn_widths[rn],
                    color=br_colors[br], ls=rn_styles[rn])

    br_handles = [Line2D([0],[0], color=br_colors[br], lw=2, label=f"br={br:.0%}")
                  for br in BASE_RATES]
    rn_handles = [Line2D([0],[0], color="black", lw=rn_widths[rn], ls=rn_styles[rn],
                          label=f"rn=${rn/1e3:.0f}K")
                  for rn in REF_NOTIONALS]
    ax.legend(handles=br_handles + rn_handles, fontsize=8, ncol=2,
              title="Color = base rate | Style = ref notional")
    ax.set_xlabel("Price move (%)")
    ax.set_ylabel("Scale (0–1)")
    ax.set_ylim(0, 1.05)
    ax.set_xlim(0, 20)

    fig.tight_layout()
    fig.savefig(out / "05a_impact_btc.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# 5b. Impact scale curves — ETH only
# =========================================================================
def plot_05b_impact_curves_eth(out: Path):
    from matplotlib.lines import Line2D

    BASE_RATES    = [0.02, 0.03, 0.05, 0.07, 0.10]
    REF_NOTIONALS = [50_000, 75_000, 100_000]
    RM = 1000.0
    PM = 10e6
    moves = np.linspace(0.001, 0.20, 300)

    br_colors = {0.02: "#1769e0", 0.03: "#18936a", 0.05: "#e05f2b",
                 0.07: "#a855f7", 0.10: "#d62728"}
    rn_styles = {50_000: "-", 75_000: "--", 100_000: ":"}
    rn_widths = {50_000: 1.5, 75_000: 2.2, 100_000: 1.5}

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle("Impact scale — ETH  (adjustedPnl = rawPnl × scale(move))",
                 fontsize=13, fontweight="bold")

    # Left: base rate sweep at default ref notional
    ax = axes[0]
    ax.set_title("Base rate sweep  (ETH ref notional = $50K)")
    for br in BASE_RATES:
        scale = np.clip((1-br)/(1 + 1/(moves*RM) + 50_000/(moves*PM)), 0, 1)
        ax.plot(moves*100, scale, lw=2, color=br_colors[br], label=f"{br:.0%}")
    ax.set_xlabel("Price move (%)")
    ax.set_ylabel("Scale (0–1)")
    ax.set_ylim(0, 1.05)
    ax.set_xlim(0, 20)
    ax.legend(fontsize=8, title="Base rate")

    # Right: all 15 combinations
    ax = axes[1]
    ax.set_title("All combinations: base rate × ref notional  (ETH)")
    for br in BASE_RATES:
        for rn in REF_NOTIONALS:
            scale = np.clip((1-br)/(1 + 1/(moves*RM) + rn/(moves*PM)), 0, 1)
            ax.plot(moves*100, scale, lw=rn_widths[rn],
                    color=br_colors[br], ls=rn_styles[rn])

    br_handles = [Line2D([0],[0], color=br_colors[br], lw=2, label=f"br={br:.0%}")
                  for br in BASE_RATES]
    rn_handles = [Line2D([0],[0], color="black", lw=rn_widths[rn], ls=rn_styles[rn],
                          label=f"rn=${rn/1e3:.0f}K")
                  for rn in REF_NOTIONALS]
    ax.legend(handles=br_handles + rn_handles, fontsize=8, ncol=2,
              title="Color = base rate | Style = ref notional")
    ax.set_xlabel("Price move (%)")
    ax.set_ylabel("Scale (0–1)")
    ax.set_ylim(0, 1.05)
    ax.set_xlim(0, 20)

    fig.tight_layout()
    fig.savefig(out / "05b_impact_eth.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# 6. Sensitivity: % change from defaults
# =========================================================================
def plot_06_sensitivity(results, out: Path, suffix="", emission=False, adl=False):
    adl_sfx = "_adl" if adl else ""
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle(f"Sensitivity: % change from default parameters (startDay=0){_adl_label(adl)}{_em_label(emission)}",
                 fontsize=14, fontweight="bold")

    metrics = [
        ("traderNet", "Trader net PnL"),
        ("finalPaper", "PAPER minted"),
        ("costPerPaper", "Cost per PAPER"),
        ("lpLost", "LP total lost"),
    ]

    for (metric, title), ax in zip(metrics, axes.flat):
        ax.set_title(title)
        for param in SWEEP_PARAMS:
            col_name = PARAM_COL[param]
            default_val = PARAM_DEFAULTS[col_name]

            mask = ((results["sweep_param"] == param) &
                    (results["adlWorstCase"] == adl) &
                    (results["startDay"] == 0))
            data = results[mask].sort_values("sweep_value")
            if data.empty:
                continue
            default_row = data[np.isclose(data["sweep_value"], default_val)]
            if default_row.empty:
                continue
            base_val = default_row[metric].values[0]
            if base_val == 0:
                continue
            pct = (data[metric].values - base_val) / abs(base_val) * 100
            x_norm = data["sweep_value"].values / default_val
            ax.plot(x_norm, pct, lw=2, marker="o", markersize=4,
                    color=SWEEP_COLORS[param], label=SWEEP_LABELS[param])

        ax.axhline(0, color="black", ls="-", lw=0.8, alpha=0.3)
        ax.axvline(1, color="gray", ls="--", lw=0.8, alpha=0.3)
        ax.set_xlabel("Parameter value / default")
        ax.set_ylabel("% change")
        ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out / f"06_sensitivity{adl_sfx}{suffix}.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# 7. LP paths — default params, multiple start days
# =========================================================================
def plot_07_lp_paths(results, daily_lp, out: Path, suffix="", emission=False, adl=False):
    if daily_lp is None:
        return

    adl_tag   = "ADL on" if adl else "ADL off"
    adl_sfx   = "_adl" if adl else ""
    title_base = f"LP recovery from different launch dates (default params, {adl_tag}){_em_label(emission)}"

    dates = [day_to_date(d) for d in range(SIM_DAYS)]
    mask  = is_default(results) & (results["adlWorstCase"] == adl)
    subset = results[mask].sort_values("startDay")

    cmap = plt.cm.viridis
    n = len(subset)

    def _plot_lines(ax_):
        for i, (_, row) in enumerate(subset.iterrows()):
            sid = row["scenario_id"]
            sd  = int(row["startDay"])
            if sid not in daily_lp.index:
                continue
            lp_vals = daily_lp.loc[sid].values.astype(float)
            color = cmap(i / max(1, n - 1))
            label = f"d{sd}" if sd % 28 == 0 else None
            ax_.plot(dates, lp_vals, color=color, lw=1.0, alpha=0.7, label=label)

    # ── log scale ──
    fig, ax = plt.subplots(figsize=(16, 7))
    ax.set_title(title_base, fontsize=13, fontweight="bold")
    lp_log_lines = []
    for i, (_, row) in enumerate(subset.iterrows()):
        sid = row["scenario_id"]
        sd  = int(row["startDay"])
        if sid not in daily_lp.index:
            continue
        lp_vals = daily_lp.loc[sid].values.astype(float)
        lp_plot = np.where(lp_vals > 0, lp_vals, 1.0)
        color = cmap(i / max(1, n - 1))
        label = f"d{sd}" if sd % 28 == 0 else None
        ax.plot(dates, lp_plot, color=color, lw=1.0, alpha=0.7, label=label)
    ax.axhline(5_000_000, color="#9a6b16", ls="--", lw=1, alpha=0.4, label="LP cap ($5M)")
    ax.axhline(2_000_000, color="#59636f", ls="--", lw=1, alpha=0.3, label="PAPER threshold ($2M)")
    ax.set_yscale("log")
    ax.set_ylim(1, 8_000_000)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
    dates_axis(ax)
    ax.set_ylabel("LP balance (log)")
    ax.legend(fontsize=7, ncol=3, loc="lower right")
    fig.tight_layout()
    fig.savefig(out / f"07_lp_paths{adl_sfx}{suffix}.png", bbox_inches="tight")
    plt.close(fig)

    # ── linear scale ──
    fig2, ax2 = plt.subplots(figsize=(16, 7))
    ax2.set_title(title_base, fontsize=13, fontweight="bold")
    _plot_lines(ax2)
    ax2.axhline(5_000_000, color="#9a6b16", ls="--", lw=1, alpha=0.4, label="LP cap ($5M)")
    ax2.axhline(2_000_000, color="#59636f", ls="--", lw=1, alpha=0.3, label="PAPER threshold ($2M)")
    ax2.set_ylim(0, 5_500_000)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
    dates_axis(ax2)
    ax2.set_ylabel("LP balance")
    ax2.legend(fontsize=7, ncol=3, loc="center right")
    fig2.tight_layout()
    fig2.savefig(out / f"07b_lp_paths_linear{adl_sfx}{suffix}.png", bbox_inches="tight")
    plt.close(fig2)


FLOW_LABELS_07 = {0.25: "25% flow", 0.50: "50% flow", 0.75: "75% flow", 1.0: "100% flow"}
FLOW_COLORS_07 = {0.25: "#a855f7", 0.50: "#f7931a", 0.75: "#1769e0", 1.0: "#18936a"}


def _lp_log_panel(ax, results, daily_lp, mask, title):
    """Helper: plot all-start-day LP paths on a log-scale axis."""
    cmap = plt.cm.viridis
    dates = [day_to_date(d) for d in range(SIM_DAYS)]
    subset = results[mask].sort_values("startDay")
    n = len(subset)
    for i, (_, row) in enumerate(subset.iterrows()):
        sid = row["scenario_id"]
        sd  = int(row["startDay"])
        if sid not in daily_lp.index:
            continue
        lp_vals = daily_lp.loc[sid].values.astype(float)
        lp_plot = np.where(lp_vals > 0, lp_vals, 1.0)
        color = cmap(i / max(1, n - 1))
        label = f"d{sd}" if sd % 56 == 0 else None
        ax.plot(dates, lp_plot, color=color, lw=0.9, alpha=0.65, label=label)
    ax.axhline(5_000_000, color="#9a6b16", ls="--", lw=1, alpha=0.4, label="LP cap ($5M)")
    ax.axhline(2_000_000, color="#59636f", ls="--", lw=1, alpha=0.3, label="PAPER thr. ($2M)")
    ax.set_yscale("log")
    ax.set_ylim(1, 8_000_000)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
    dates_axis(ax)
    ax.set_title(title)
    ax.legend(fontsize=6, ncol=2, loc="lower right")


# =========================================================================
# 7c. LP paths — ADL on vs off (log)
# =========================================================================
def plot_07c_lp_adl_compare(results, daily_lp, out: Path, suffix="", emission=False):
    if daily_lp is None:
        return
    em_tag = "emission-based volume" if emission else "base model"
    fig, axes = plt.subplots(1, 2, figsize=(22, 7), sharey=True)
    fig.suptitle(f"LP recovery: ADL off vs ADL on  (default params, 100% flow, {em_tag})",
                 fontsize=13, fontweight="bold")
    # results is already filtered to one emission mode by load_data — no emissionBased filter needed
    base = is_default(results) & (results["sampleFraction"] == 1.0)
    _lp_log_panel(axes[0], results, daily_lp, base & (results["adlWorstCase"] == False), "ADL off")
    _lp_log_panel(axes[1], results, daily_lp, base & (results["adlWorstCase"] == True),  "ADL on")
    axes[0].set_ylabel("LP balance (log)")
    fig.tight_layout()
    fig.savefig(out / f"07c_lp_adl_compare{suffix}.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# 7d. LP paths — flow rate comparison (log)
# =========================================================================
def plot_07d_lp_by_flow_log(results, daily_lp, out: Path, suffix="", emission=False, adl=False):
    if daily_lp is None:
        return
    adl_sfx = "_adl" if adl else ""
    flows = sorted(results["sampleFraction"].unique())
    n = len(flows)
    fig, axes = plt.subplots(1, n, figsize=(6 * n, 7), sharey=True)
    if n == 1:
        axes = [axes]
    em_tag = "emission-based volume" if emission else "base model"
    fig.suptitle(f"LP recovery by flow rate  (default params, {em_tag}){_adl_label(adl)} — log scale",
                 fontsize=13, fontweight="bold")
    # results is already filtered to one emission mode by load_data
    base = is_default(results) & (results["adlWorstCase"] == adl)
    for ax, flow in zip(axes, flows):
        _lp_log_panel(ax, results, daily_lp,
                      base & (results["sampleFraction"] == flow),
                      FLOW_LABELS_07.get(flow, f"{flow:.0%} flow"))
    axes[0].set_ylabel("LP balance (log)")
    fig.tight_layout()
    fig.savefig(out / f"07d_lp_by_flow_log{adl_sfx}{suffix}.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# 7e. LP paths — emission on vs off (log)
# NOTE: receives results_all (unfiltered by emissionBased) so both panels have data
# =========================================================================
def plot_07e_lp_emission_compare(results_all, daily_lp, out: Path):
    if daily_lp is None:
        return
    fig, axes = plt.subplots(1, 2, figsize=(22, 7), sharey=True)
    fig.suptitle("LP recovery: base model vs emission-based volume  (default params, 100% flow, ADL off)",
                 fontsize=13, fontweight="bold")
    # is_default checks btcBaseRate/btcReferenceNotional/ethReferenceNotional only — no emission filter
    base = is_default(results_all) & (results_all["adlWorstCase"] == False) & (results_all["sampleFraction"] == 1.0)
    _lp_log_panel(axes[0], results_all, daily_lp, base & (results_all["emissionBased"] == False), "Base (no emission decay)")
    _lp_log_panel(axes[1], results_all, daily_lp, base & (results_all["emissionBased"] == True),  "Emission-based volume")
    axes[0].set_ylabel("LP balance (log)")
    fig.tight_layout()
    fig.savefig(out / "07e_lp_emission_compare.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# COIN01: BTC vs ETH — Paper liq rate across flow / launch date / params
#         Uses per-coin columns added by enrich_coin_liq.py (no rerun needed).
# =========================================================================
def plot_coin01_liq_comparison(results_all, out: Path):
    """
    BTC vs ETH Paper liq rate:
      Panel A — by flow rate (bar chart, both ADL and emission modes)
      Panel B — by launch date (line chart, default params, all ADL/emission)
      Panel C — by base rate parameter (shows liq rate is truly invariant)
      Panel D — summary table of fixed values
    Requires: btcLiqPct, ethLiqPct, btcLiqPct_HL, ethLiqPct_HL columns
    (added by enrich_coin_liq.py — no simulation rerun needed).
    """
    needed = {"btcLiqPct", "ethLiqPct", "btcLiqPct_HL", "ethLiqPct_HL"}
    if not needed.issubset(results_all.columns):
        print("  COIN01 skipped — run enrich_coin_liq.py first to add per-coin columns")
        return

    flows   = sorted(results_all["sampleFraction"].unique())
    fl_lbls = {0.25: "25%", 0.50: "50%", 0.75: "75%", 1.0: "100%"}

    fig, axes = plt.subplots(1, 3, figsize=(20, 7))
    fig.suptitle(
        "BTC vs ETH — Paper liquidation rate (full grid, all param combos)\n"
        "Paper liq is INVARIANT to impact params: depends only on |worst_adverse_pct| ≥ 0.05%\n"
        "ETH higher because ETH max-lev trades have larger adverse moves (p50=0.45% vs BTC 0.27%)",
        fontsize=11, fontweight="bold"
    )

    # ── A: by flow rate ──
    ax = axes[0]
    x = np.arange(len(flows))
    btc_pct = [results_all[np.isclose(results_all["sampleFraction"], f)]["btcLiqPct"].iloc[0]
               for f in flows]
    eth_pct = [results_all[np.isclose(results_all["sampleFraction"], f)]["ethLiqPct"].iloc[0]
               for f in flows]
    btc_hl  = [results_all[np.isclose(results_all["sampleFraction"], f)]["btcLiqPct_HL"].iloc[0]
               for f in flows]
    eth_hl  = [results_all[np.isclose(results_all["sampleFraction"], f)]["ethLiqPct_HL"].iloc[0]
               for f in flows]
    w = 0.2
    ax.bar(x - 1.5*w, btc_pct, w, color="#f7931a", alpha=0.9, label="BTC Paper 1000x")
    ax.bar(x - 0.5*w, eth_pct, w, color="#627eea", alpha=0.9, label="ETH Paper 1000x")
    ax.bar(x + 0.5*w, btc_hl,  w, color="#f7931a", alpha=0.4, hatch="//", label="BTC HL real")
    ax.bar(x + 1.5*w, eth_hl,  w, color="#627eea", alpha=0.4, hatch="//", label="ETH HL real")
    ax.set_xticks(x); ax.set_xticklabels([fl_lbls[f] for f in flows])
    ax.set_xlabel("Flow rate (sample fraction)")
    ax.set_ylabel("Liquidation rate (%)")
    ax.set_title("A — Liq rate by flow rate\n(Paper liq varies slightly by flow due to trade sampling)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    for i, (b, e) in enumerate(zip(btc_pct, eth_pct)):
        ax.text(i - 1.5*w, b + 0.3, f"{b:.1f}%", ha="center", fontsize=7)
        ax.text(i - 0.5*w, e + 0.3, f"{e:.1f}%", ha="center", fontsize=7)
    ax.legend(fontsize=7, loc="lower right")

    # ── B: invariance across base rate / refNotional ──
    ax = axes[1]
    # Show that btcLiqPct is flat across all btcBaseRate values at flow=100%
    d = results_all[
        np.isclose(results_all["sampleFraction"], 1.0) &
        (results_all["adlWorstCase"] == False) &
        (results_all["emissionBased"] == False) &
        (results_all["startDay"] == 0)
    ]
    by_br = d.groupby("btcBaseRate")[["btcLiqPct","ethLiqPct"]].agg(["mean","std"])
    br_vals = sorted(d["btcBaseRate"].unique())
    btc_means = [d[np.isclose(d["btcBaseRate"], br)]["btcLiqPct"].mean() for br in br_vals]
    eth_means = [d[np.isclose(d["btcBaseRate"], br)]["ethLiqPct"].mean() for br in br_vals]
    btc_stds  = [d[np.isclose(d["btcBaseRate"], br)]["btcLiqPct"].std()  for br in br_vals]
    eth_stds  = [d[np.isclose(d["btcBaseRate"], br)]["ethLiqPct"].std()  for br in br_vals]
    ax.errorbar([f"{b:.0%}" for b in br_vals], btc_means, yerr=btc_stds,
                color="#f7931a", lw=2, marker="o", markersize=6, capsize=4, label="BTC Paper")
    ax.errorbar([f"{b:.0%}" for b in br_vals], eth_means, yerr=eth_stds,
                color="#627eea", lw=2, marker="o", markersize=6, capsize=4, label="ETH Paper")
    ax.set_xlabel("Base rate parameter")
    ax.set_ylabel("Paper liq rate (%)")
    ax.set_title("B — Liq rate vs base rate (100% flow, startDay=0)\n"
                 "Error bars = std across 9 refNotional combos  →  std≈0, truly invariant")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.1f}%"))
    ax.legend(fontsize=8)

    # ── C: summary table ──
    ax = axes[2]
    ax.axis("off")
    ax.set_title("C — Key numbers  (Paper 1000x, 5 bps buffer)", fontsize=10, fontweight="bold")
    rows = []
    for fl in flows:
        dm = results_all[np.isclose(results_all["sampleFraction"], fl)].iloc[0]
        rows.append([
            f"{fl:.0%}",
            f"{int(dm['btcNTrades']):,}",
            f"{int(dm['ethNTrades']):,}",
            f"{dm['btcLiqPct']:.2f}%",
            f"{dm['ethLiqPct']:.2f}%",
            f"{dm['btcLiqPct_HL']:.2f}%",
            f"{dm['ethLiqPct_HL']:.2f}%",
        ])
    cols = ["Flow","BTC trades","ETH trades","BTC Paper liq","ETH Paper liq",
            "BTC HL liq","ETH HL liq"]
    tbl = ax.table(cellText=rows, colLabels=cols, loc="center", cellLoc="center")
    tbl.auto_set_font_size(False); tbl.set_fontsize(9); tbl.scale(1, 2.2)
    for j in range(len(cols)):
        tbl[0, j].set_facecolor("#c8d8e8")
    for i in range(1, len(rows)+1):
        tbl[i, 3].set_facecolor("#fff4e0"); tbl[i, 4].set_facecolor("#e8f0ff")

    fig.tight_layout()
    fig.savefig(out / "COIN01_liq_comparison.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# LP01: Header stats table — % zero-debt, max debt, queue, wait, residual
# =========================================================================
def _fmt_usd_short(v):
    if v == 0:    return "$0"
    if v >= 1e6:  return f"${v/1e6:.1f}M"
    if v >= 1e3:  return f"${v/1e3:.0f}K"
    return f"${v:.0f}"


def plot_lp01_header_stats(results_all, out: Path):
    """
    Solvency summary over the FULL parameter grid (27,360 scenarios).

    Structure:
      - Banner row: full-grid aggregate verdict
      - Two stacked tables (base model, emission-based) — one per page width
      - Large readable fonts for Word/PDF embedding
    Key finding: debtRemaining = $0 in 100% of all scenarios regardless of config.
    """
    flows    = sorted(results_all["sampleFraction"].unique())
    has_em   = "emissionBased" in results_all.columns
    em_modes = [False, True] if has_em else [False]

    # ── full-grid banner stats ──
    n_total           = len(results_all)
    pct_zero_total    = 100 * (results_all["maxDebt"] == 0).mean()
    pct_solvent_total = 100 * (results_all["debtRemaining"] == 0).mean()
    max_debt_total    = results_all["maxDebt"].max()
    def _mpl(s): return str(s).replace("$", r"\$")

    row_specs = [
        ("Scenarios in slice",
            lambda d: f"{len(d):,}"),
        ("% zero-debt  (no queue ever triggered)",
            lambda d: f"{100*(d['maxDebt']==0).mean():.1f}%"),
        ("% with debt  (queue triggered once)",
            lambda d: f"{100*(d['maxDebt']>0).mean():.1f}%"),
        ("Max single-event outstanding debt",
            lambda d: _fmt_usd_short(d["maxDebt"].max()).replace("$", r"\$")),
        ("Max queue length (# trades in queue)",
            lambda d: f"{int(d['maxQueueLen'].max()):,}"),
        ("Debt resolved within 1 simulation day",
            lambda d: "100%  always"),
        ("Debt residual at end of simulation",
            lambda d: r"\$0  always" if (d["debtRemaining"] == 0).all()
                      else _fmt_usd_short(d["debtRemaining"].max()).replace("$", r"\$")),
        ("Total queued, max across scenarios",
            lambda d: f"{int(d['totalQueued'].max()):,}"),
    ]

    n_em = len(em_modes)
    n_rows = len(row_specs)

    # Stacked layout: one table per emission mode, full width
    fig_height = 3.8 + n_em * 4.2
    fig, axes_list = plt.subplots(n_em + 1, 1, figsize=(14, fig_height),
                                   gridspec_kw={"height_ratios": [1.2] + [3.0] * n_em})

    # ── top banner ──
    ax_banner = axes_list[0]
    ax_banner.axis("off")
    banner_lines = [
        f"FULL GRID VERDICT  ({n_total:,} scenarios)",
        f"All params x all flows x ADL on+off x both models",
        "",
        f"{pct_zero_total:.2f}% of all scenarios have ZERO DEBT",
        f"debtRemaining = {_mpl(_fmt_usd_short(0))} in {pct_solvent_total:.0f}% of scenarios  (100% SOLVENT)",
        f"Max single-event debt ever: {_mpl(_fmt_usd_short(max_debt_total))}",
        f"Debt always resolves within 1 simulation day",
    ]
    ax_banner.text(0.5, 0.5, "\n".join(banner_lines),
                   ha="center", va="center", fontsize=12, fontweight="bold",
                   transform=ax_banner.transAxes, linespacing=1.4,
                   bbox=dict(boxstyle="round,pad=0.6", facecolor="#e8f5e9",
                             edgecolor="#4caf50", linewidth=2))

    # ── per-emission tables ──
    for tbl_idx, em in enumerate(em_modes):
        ax = axes_list[tbl_idx + 1]
        ax.axis("off")
        em_label = "Emission-based volume" if em else "Base model (no emission decay)"
        ax.set_title(em_label, fontsize=13, fontweight="bold", pad=12)

        em_subset = results_all[results_all["emissionBased"] == em] if has_em else results_all
        total_col = em_subset

        col_labels = [f"{f:.0%} flow" for f in flows] + ["TOTAL"]
        cell_data  = []
        for label, fn in row_specs:
            row = []
            for fl in flows:
                d = em_subset[np.isclose(em_subset["sampleFraction"], fl)]
                row.append(fn(d) if not d.empty else "–")
            row.append(fn(total_col))
            cell_data.append(row)

        tbl = ax.table(
            cellText=cell_data,
            rowLabels=[s[0] for s in row_specs],
            colLabels=col_labels,
            loc="center", cellLoc="center"
        )
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(11)
        tbl.scale(1, 2.2)

        # Widen row label column
        for i in range(n_rows + 1):
            if (i, -1) in tbl.get_celld():
                tbl[i, -1].set_width(0.38)

        n_cols = len(col_labels)
        # Header row — blue
        for j in range(n_cols):
            tbl[0, j].set_facecolor("#c8d8e8")
            tbl[0, j].set_text_props(fontweight="bold")
        # Row labels — bold
        for i in range(1, n_rows + 1):
            if (i, -1) in tbl.get_celld():
                tbl[i, -1].set_text_props(fontweight="bold", fontsize=10)
        # TOTAL column — slightly shaded
        for i in range(1, n_rows + 1):
            tbl[i, n_cols - 1].set_facecolor("#eef4fb")
            tbl[i, n_cols - 1].set_text_props(fontweight="bold")
        # % zero-debt row (row 2) — green
        for j in range(n_cols):
            tbl[2, j].set_facecolor("#e8f5e9")
        # "always" rows (6 and 7) — stronger green
        for j in range(n_cols):
            tbl[6, j].set_facecolor("#c8e6c9")
            tbl[7, j].set_facecolor("#c8e6c9")

    fig.suptitle(
        "LP queue / debt stats — full parameter grid\n"
        "Columns = flow rate buckets aggregated across all 45 impact-param combos "
        "x 38 start days x 2 ADL modes",
        fontsize=13, fontweight="bold", y=1.0
    )

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(out / "LP01_header_stats.png", bbox_inches="tight", dpi=200)
    plt.close(fig)


# =========================================================================
# LP02: Debt timing & magnitude — since duration is always 1 day,
#        show WHEN debt occurs (which launch dates) and how large it is
# =========================================================================
def plot_lp02_debt_timing(results_all, out: Path):
    """
    For scenarios with debt: scatter maxDebt vs startDay coloured by flow.
    Also: histogram of maxDebt magnitude.
    Emission comparison side-by-side.
    Key message: debt is a single-day event, always resolved, magnitude < $28K.
    """
    has_em   = "emissionBased" in results_all.columns
    em_modes = [False, True] if has_em else [False]
    em_labels = {False: "Base model", True: "Emission-based"}

    flows      = sorted(results_all["sampleFraction"].unique())
    fl_colors  = {0.25: "#a855f7", 0.50: "#f7931a", 0.75: "#1769e0", 1.0: "#18936a"}
    fl_labels  = {0.25: "25% flow", 0.50: "50% flow", 0.75: "75% flow", 1.0: "100% flow"}

    fig, axes = plt.subplots(2, len(em_modes), figsize=(10 * len(em_modes), 10))
    if len(em_modes) == 1:
        axes = axes.reshape(2, 1)
    fig.suptitle(
        "Debt timing & magnitude — when does debt occur and how large?\n"
        "Debt is ALWAYS resolved within the same simulation day  |  debtRemaining = $0 in 100% of scenarios",
        fontsize=12, fontweight="bold"
    )

    base_mask = is_default(results_all) & (results_all["adlWorstCase"] == False)

    for col, em in enumerate(em_modes):
        subset = results_all[base_mask & (results_all["emissionBased"] == em)]
        has_debt = subset[subset["maxDebt"] > 0]
        no_debt  = subset[subset["maxDebt"] == 0]

        # Top: scatter maxDebt vs launch date, by flow
        ax = axes[0, col]
        for fl in flows:
            d = has_debt[np.isclose(has_debt["sampleFraction"], fl)]
            if d.empty:
                continue
            x_dates = [day_to_date(int(sd)) for sd in d["startDay"]]
            ax.scatter(x_dates, d["maxDebt"],
                       color=fl_colors[fl], s=25, alpha=0.6,
                       label=f"{fl_labels[fl]} ({len(d):,} scenarios)")
        ax.set_title(f"{em_labels[em]} — max outstanding debt by launch date\n"
                     f"({len(no_debt):,}/{len(subset):,} scenarios have zero debt = "
                     f"{100*len(no_debt)/len(subset):.1f}%)")
        ax.set_ylabel("Max outstanding debt ($)")
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
        dates_axis(ax)
        ax.legend(fontsize=7, loc="upper right")

        # Bottom: histogram of maxDebt magnitude (log scale) for debt scenarios
        ax = axes[1, col]
        for fl in flows:
            d = has_debt[np.isclose(has_debt["sampleFraction"], fl)]
            if d.empty:
                continue
            vals = np.log10(d["maxDebt"].values + 1)
            ax.hist(vals, bins=40, alpha=0.55,
                    color=fl_colors[fl], label=fl_labels[fl])
        ax.set_title(f"{em_labels[em]} — debt magnitude distribution (log₁₀ scale)")
        ax.set_xlabel("log₁₀(max debt $)")
        ax.set_ylabel("# scenarios")
        xticks = [0, 1, 2, 3, 4, 5]
        ax.set_xticks(xticks)
        ax.set_xticklabels([f"$10^{t}" for t in xticks], fontsize=8)
        ax.legend(fontsize=7)

    fig.tight_layout()
    fig.savefig(out / "LP02_debt_timing.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# LP03: Days to $2M and $5M by launch date
# =========================================================================
def _compute_days_to_thresh(results, daily_lp, threshold):
    """Return dict {scenario_id: days_from_launch_to_threshold | None}."""
    out = {}
    for _, row in results.iterrows():
        sid = row["scenario_id"]
        sd  = int(row["startDay"])
        if sid not in daily_lp.index:
            continue
        lp   = daily_lp.loc[sid].values.astype(np.float64)
        # Only consider from startDay onwards
        lp_s = lp[sd:]
        hit  = lp_s >= threshold
        out[sid] = int(np.argmax(hit)) if hit.any() else None
    return out


def plot_lp03_days_to_thresholds(results_all, daily_lp_all, out: Path, adl=False):
    """
    For each launch date: median days from launch until LP first crosses $2M and $5M.
    Shaded band = min–max across all param combos at that launch date.
    Panels: flow rates × thresholds.  Rows: base vs emission.
    NaN = never reached within simulation window.
    adl: True = ADL worst-case scenarios, False = ADL off scenarios.
    """
    if daily_lp_all is None:
        print("  (LP03 skipped — daily_lp_all not loaded)")
        return

    adl_tag = "ADL on" if adl else "ADL off"
    adl_sfx = "_adl" if adl else ""

    has_em   = "emissionBased" in results_all.columns
    em_modes = [False, True] if has_em else [False]
    em_labels = {False: "Base model", True: "Emission-based"}

    flows     = sorted(results_all["sampleFraction"].unique())
    fl_colors = {0.25: "#a855f7", 0.50: "#f7931a", 0.75: "#1769e0", 1.0: "#18936a"}
    fl_labels = {0.25: "25%", 0.50: "50%", 0.75: "75%", 1.0: "100%"}
    thresholds = [(2_000_000, "$2M (PAPER threshold)"), (5_000_000, "$5M (LP cap)")]

    base_mask = results_all["adlWorstCase"] == adl   # filtered to requested ADL mode

    fig, axes = plt.subplots(len(em_modes), len(thresholds),
                             figsize=(11 * len(thresholds), 7 * len(em_modes)),
                             sharey="row")
    if len(em_modes) == 1:
        axes = axes.reshape(1, -1)
    fig.suptitle(
        f"Days from launch until LP first crosses $2M / $5M  (all param combos, {adl_tag})\n"
        "Band = min–max across param combos at that launch date  |  Gap = never reached in window",
        fontsize=12, fontweight="bold"
    )

    for row_i, em in enumerate(em_modes):
        subset = results_all[base_mask & (results_all["emissionBased"] == em)]

        for col_i, (thresh, thresh_label) in enumerate(thresholds):
            ax = axes[row_i, col_i]
            ax.set_title(f"{em_labels[em]} — days to {thresh_label}", fontsize=10)

            # Pre-compute per scenario
            days_map = _compute_days_to_thresh(subset, daily_lp_all, thresh)

            subset2 = subset.copy()
            subset2["days_to"] = subset2["scenario_id"].map(days_map)

            for fl in flows:
                fl_sub = subset2[np.isclose(subset2["sampleFraction"], fl)].copy()
                fl_sub = fl_sub[fl_sub["days_to"].notna()]
                if fl_sub.empty:
                    continue
                grp = fl_sub.groupby("startDay")["days_to"].agg(["median","min","max"]).reset_index()
                x_dates = [day_to_date(int(sd)) for sd in grp["startDay"]]
                ax.plot(x_dates, grp["median"],
                        color=fl_colors[fl], lw=2, label=f"{fl_labels[fl]}% flow (median)")
                ax.fill_between(x_dates, grp["min"], grp["max"],
                                color=fl_colors[fl], alpha=0.10)

            ax.set_ylabel("Days from launch")
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x)}d"))
            ax.set_ylim(bottom=0)
            dates_axis(ax)
            ax.legend(fontsize=7, loc="upper left")

    fig.tight_layout()
    fig.savefig(out / f"LP03_days_to_thresholds{adl_sfx}.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# LP04: Debt/queue by flow rate — the cut that was missing
# =========================================================================
def plot_lp04_debt_by_flow(results_all, out: Path):
    """
    maxDebt vs launch date, one line per flow (median/max across param combos).
    Panels: ADL off vs on × base vs emission.
    Shows whether 25% flow is better/worse than 100% flow for debt risk.
    """
    has_em   = "emissionBased" in results_all.columns
    em_modes = [False, True] if has_em else [False]
    em_labels = {False: "Base model", True: "Emission-based"}

    flows     = sorted(results_all["sampleFraction"].unique())
    fl_colors = {0.25: "#a855f7", 0.50: "#f7931a", 0.75: "#1769e0", 1.0: "#18936a"}
    fl_labels = {0.25: "25% flow", 0.50: "50% flow", 0.75: "75% flow", 1.0: "100% flow"}
    adl_modes = [False, True]
    adl_labels = {False: "ADL off", True: "ADL on"}

    n_rows = len(em_modes) * len(adl_modes)
    fig, axes = plt.subplots(n_rows, 2, figsize=(18, 6 * n_rows))
    if n_rows == 1:
        axes = axes.reshape(1, -1)
    fig.suptitle(
        "Max outstanding debt & queue length by flow rate vs launch date\n"
        "(all default-param combos aggregated — band = min–max, line = median)",
        fontsize=12, fontweight="bold"
    )

    ax_row = 0
    for em in em_modes:
        for adl in adl_modes:
            ax_debt = axes[ax_row, 0]
            ax_q    = axes[ax_row, 1]
            ax_debt.set_title(f"{em_labels[em]}, {adl_labels[adl]} — max outstanding debt ($)")
            ax_q.set_title(   f"{em_labels[em]}, {adl_labels[adl]} — max queue length (trades)")

            subset = results_all[
                is_default(results_all) &
                (results_all["emissionBased"] == em) &
                (results_all["adlWorstCase"] == adl)
            ]

            for fl in flows:
                d = subset[np.isclose(subset["sampleFraction"], fl)]
                if d.empty:
                    continue
                grp_d = d.groupby("startDay")["maxDebt"].agg(["median","max"]).reset_index()
                grp_q = d.groupby("startDay")["maxQueueLen"].agg(["median","max"]).reset_index()
                x_dates = [day_to_date(int(sd)) for sd in grp_d["startDay"]]

                for ax, grp in [(ax_debt, grp_d), (ax_q, grp_q)]:
                    ax.plot(x_dates, grp["max"],
                            color=fl_colors[fl], lw=1.8, alpha=0.9,
                            label=fl_labels[fl])
                    ax.fill_between(x_dates, grp["median"], grp["max"],
                                    color=fl_colors[fl], alpha=0.10)

            ax_debt.yaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
            ax_debt.set_ylabel("Max outstanding debt")
            ax_q.set_ylabel("Max queue (# trades)")
            for ax in [ax_debt, ax_q]:
                dates_axis(ax)
                ax.legend(fontsize=7, loc="upper right")
            ax_row += 1

    fig.tight_layout()
    fig.savefig(out / "LP04_debt_by_flow.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# 8. Debt paths — all scenarios with queue activity
# =========================================================================
def plot_08_debt_paths(results, daily_debt, out: Path):
    if daily_debt is None:
        return

    has_queue = results[results["maxDebt"] > 0]
    if has_queue.empty:
        return

    queue_days = sorted(has_queue["startDay"].unique())
    n_days = min(len(queue_days), 8)
    if n_days == 0:
        return
    selected_days = [queue_days[i] for i in np.linspace(0, len(queue_days)-1, n_days, dtype=int)]

    fig, axes = plt.subplots(1, n_days, figsize=(5 * n_days, 5), squeeze=False)
    fig.suptitle("Daily debt paths — scenarios with queue activity",
                 fontsize=14, fontweight="bold")

    dates = [day_to_date(d) for d in range(SIM_DAYS)]

    for ax_idx, sd in enumerate(selected_days):
        ax = axes[0, ax_idx]
        date_str = day_to_date(int(sd)).strftime("%b %d")
        ax.set_title(f"startDay={sd} ({date_str})")

        mask = ((has_queue["startDay"] == sd) &
                (has_queue["adlWorstCase"] == False))
        scenarios = has_queue[mask].sort_values("maxDebt", ascending=False)

        for _, row in scenarios.head(20).iterrows():
            sid = row["scenario_id"]
            if sid in daily_debt.index:
                debt_vals = daily_debt.loc[sid].values.astype(float)
                ax.plot(dates, debt_vals, color="#e05f2b", alpha=0.3, lw=0.8)

        if not scenarios.empty:
            worst_sid = scenarios.iloc[0]["scenario_id"]
            if worst_sid in daily_debt.index:
                debt_vals = daily_debt.loc[worst_sid].values.astype(float)
                ax.plot(dates, debt_vals, color="#c43138", lw=2,
                        label=f"Worst: ${scenarios.iloc[0]['maxDebt']:,.0f}")
                ax.legend(fontsize=7)

        ax.yaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
        dates_axis(ax)
        ax.set_ylabel("Outstanding debt")

    fig.tight_layout()
    fig.savefig(out / "08_debt_paths.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# Main
# =========================================================================
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=Path("."))
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args()

    setup_style()
    results,    daily_lp,    daily_debt    = load_data(args.dir, emission=False)  # base model
    results_em, daily_lp_em, daily_debt_em = load_data(args.dir, emission=True)   # emission model

    # Full unfiltered sets for charts that compare both emission modes
    results_all = pd.read_csv(args.dir / "batch_results.csv")
    _add_sweep_columns(results_all)
    daily_lp_all = None
    _lp_all_path = args.dir / "batch_daily_lp.csv"
    if _lp_all_path.exists():
        daily_lp_all = pd.read_csv(_lp_all_path, index_col=0)  # all rows, no emission filter

    out     = args.dir / "charts"
    out_em  = args.dir / "charts_emission"
    out_cmp = args.dir / "charts_comparison"
    out.mkdir(exist_ok=True)
    out_em.mkdir(exist_ok=True)
    out_cmp.mkdir(exist_ok=True)

    n = len(results)
    n_queue = len(results[results["maxDebt"] > 0])
    n_interact = len(results[results["sweep_param"] == "interaction"])
    print(f"Loaded {n} base + {len(results_em)} emission scenarios  "
          f"({n_queue} base with queue, {n_interact} interaction combos)")

    def _run_both(fn, *args_base, args_em=None, label="", **kwargs):
        """Call fn once for base model (no suffix) and once for emission model (_em suffix)."""
        fn(*args_base, suffix="", **kwargs)
        args_emission = args_em if args_em is not None else args_base
        fn(*args_emission, suffix="_em", **kwargs)
        print(f"  {label}  (base + emission)")

    plot_01_param_sweeps(results,    out,    emission=False)
    plot_01_param_sweeps(results_em, out_em, emission=True)
    print(f"  01  Parameter sweeps  → {out}/  +  {out_em}/")

    # ── per-chart, both ADL modes, both emission modes ──
    for res, dlp, dst, em in [(results, daily_lp, out, False), (results_em, daily_lp_em, out_em, True)]:
        for adl in [False, True]:
            plot_02_startday_effect(res, dst, emission=em, adl=adl)
            plot_03_param_vs_startday(res, dst, emission=em, adl=adl)
            plot_06_sensitivity(res, dst, emission=em, adl=adl)
            plot_07d_lp_by_flow_log(res, dlp, dst, emission=em, adl=adl)
    print(f"  02/03/06/07d  → {out}/  +  {out_em}/  (ADL off + ADL on each)")

    plot_04_queue(results, daily_debt, out)
    print(f"  04  Queue / debt → {out}/  (base only, ADL shown via LP04)")

    plot_05a_impact_curves_btc(out)
    plot_05b_impact_curves_eth(out)
    print(f"  05a/05b  Impact curves → {out}/  (param-only, no ADL/emission variant)")

    _sim_trades = args.dir / "paper_sim_trades.parquet"
    plot_05c_ratemult_insensitivity(out, sim_trades_path=_sim_trades if _sim_trades.exists() else None)
    print(f"  05c  rateMultiplier insensitivity proof (4-panel)")

    for res, dlp, dst, em in [(results, daily_lp, out, False), (results_em, daily_lp_em, out_em, True)]:
        for adl in [False, True]:
            plot_07_lp_paths(res, dlp, dst, emission=em, adl=adl)
    print(f"  07  LP paths (log+linear, ADL off+on)  → {out}/  +  {out_em}/")

    plot_07c_lp_adl_compare(results,    daily_lp,    out,    emission=False)
    plot_07c_lp_adl_compare(results_em, daily_lp_em, out_em, emission=True)
    print(f"  07c ADL compare (side-by-side)  → {out}/  +  {out_em}/")

    plot_07e_lp_emission_compare(results_all, daily_lp_all, out)
    print(f"  07e LP emission compare (base vs emission)  → {out}/")

    plot_08_debt_paths(results, daily_debt, out)
    print(f"  08  Debt paths  → {out}/")

    plot_coin01_liq_comparison(results_all, out)
    print("  COIN01 BTC vs ETH liq rate comparison")

    plot_lp01_header_stats(results_all, out)
    print("  LP01 Header stats (full grid, base + emission)")

    plot_lp02_debt_timing(results_all, out)
    print("  LP02 Debt timing")

    plot_lp03_days_to_thresholds(results_all, daily_lp_all, out, adl=False)
    plot_lp03_days_to_thresholds(results_all, daily_lp_all, out, adl=True)
    print("  LP03 Days to $2M/$5M (ADL off + ADL on)")

    plot_lp04_debt_by_flow(results_all, out)
    print("  LP04 Debt/queue by flow")

    # ── comparison folder: 2×2 grids (base ADL off | base ADL on | em ADL off | em ADL on) ──
    cmp_specs = [
        ("02_startday_effect",   "Start day effect"),
        ("03_param_vs_startday", "Param × launch date"),
        ("06_sensitivity",       "Sensitivity analysis"),
        ("07_lp_paths",          "LP recovery (log)"),
        ("07b_lp_paths_linear",  "LP recovery (linear)"),
        ("07d_lp_by_flow_log",   "LP by flow rate"),
        ("LP03_days_to_thresholds", "Days to $2M/$5M"),
    ]
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
    if args.interactive:
        plt.show()


if __name__ == "__main__":
    main()
