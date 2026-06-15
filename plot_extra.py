#!/usr/bin/env python3
"""
plot_extra.py — Volume, OI, liquidation rate, and distribution charts.

Charts 5-10:
  15  Daily volume by flow %
  16  Daily OI by flow %
  17  Liquidation rate by flow % vs start day
  18  LP gains distribution per flow %
  19  LP losses distribution per flow %
  20  Position notional distribution (before/after P99.9 normalization)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

START_MS = 1754006400000
DAY_MS = 86_400_000
SIM_DAYS = 290
START_DATE = datetime(2025, 8, 1, tzinfo=timezone.utc)

FLOW_FRACS = [0.25, 0.50, 0.75, 1.0]
FLOW_COLORS = {0.25: "#a855f7", 0.50: "#f7931a", 0.75: "#1769e0", 1.0: "#18936a"}
FLOW_LABELS = {0.25: "25% flow", 0.50: "50% flow", 0.75: "75% flow", 1.0: "100% flow"}


def setup_style():
    plt.rcParams.update({
        "font.family": "sans-serif", "font.size": 10,
        "axes.titlesize": 12, "axes.titleweight": "bold",
        "axes.labelsize": 10, "axes.grid": True,
        "grid.alpha": 0.25, "grid.linewidth": 0.5,
        "figure.facecolor": "white", "axes.facecolor": "white",
        "figure.dpi": 150,
    })


def day_to_date(day: int) -> datetime:
    return START_DATE + timedelta(days=int(day))


def dates_axis(ax):
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)


def usd_fmt(x, _):
    if abs(x) >= 1e9: return f"${x/1e9:.1f}B"
    if abs(x) >= 1e6: return f"${x/1e6:.1f}M"
    if abs(x) >= 1e3: return f"${x/1e3:.0f}K"
    return f"${x:.0f}"


def load_trades(path: Path):
    """Load raw trade data and prepare arrays."""
    print("Loading trades...")
    df = pd.read_parquet(path, columns=[
        "coin", "direction", "open_time_ms", "close_time_ms",
        "open_px", "close_px", "notional_at_entry_usd", "worst_adverse_pct",
    ])

    df["open_px"] = df["open_px"].astype(np.float64)
    df["close_px"] = df["close_px"].astype(np.float64)
    df["notional"] = df["notional_at_entry_usd"].astype(np.float64)
    df["adversePct"] = df["worst_adverse_pct"].astype(np.float64).abs()

    df["openDay"] = ((df["open_time_ms"] - START_MS) / DAY_MS).astype(int).clip(0, SIM_DAYS - 1)
    df["closeDay"] = ((df["close_time_ms"] - START_MS) / DAY_MS).astype(int).clip(0, SIM_DAYS - 1)

    is_long = df["direction"] == "long"
    df["closeMovePct"] = np.where(
        is_long,
        (df["close_px"] - df["open_px"]) / df["open_px"],
        (df["open_px"] - df["close_px"]) / df["open_px"],
    )
    df["is_btc"] = df["coin"] == "BTC"

    mask = df[["closeMovePct", "adversePct", "notional"]].notna().all(axis=1) & (df["open_px"] > 0)
    df = df[mask].reset_index(drop=True)

    # Deterministic sample key
    rng = np.random.default_rng(42)
    df["sampleKey"] = rng.random(len(df))

    print(f"  {len(df):,} valid trades loaded")
    return df


# =========================================================================
# Chart 5 (15): Daily volume by flow %
# =========================================================================
def plot_daily_volume(df, out: Path):
    fig, ax = plt.subplots(figsize=(16, 6))
    ax.set_title("Daily trading volume by flow % (notional at entry)", fontsize=13, fontweight="bold")

    dates = [day_to_date(d) for d in range(SIM_DAYS)]
    max_open = 10_000_000

    for flow in FLOW_FRACS:
        mask = df["sampleKey"] <= flow
        sub = df[mask]
        paper_notional = np.minimum(sub["notional"].values, max_open)
        vol = np.zeros(SIM_DAYS)
        for d, pn in zip(sub["openDay"].values, paper_notional):
            if 0 <= d < SIM_DAYS:
                vol[d] += pn

        # 7-day moving average for readability
        kernel = np.ones(7) / 7
        vol_smooth = np.convolve(vol, kernel, mode="same")
        ax.plot(dates, vol_smooth, color=FLOW_COLORS[flow], lw=1.8,
                alpha=0.85, label=f"{FLOW_LABELS[flow]} (avg ${vol[vol>0].mean()/1e6:.0f}M/day)")

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
    dates_axis(ax)
    ax.set_ylabel("Daily volume (7-day MA)")
    ax.legend(fontsize=9)

    fig.tight_layout()
    fig.savefig(out / "X15_daily_volume_by_flow.png", bbox_inches="tight")
    plt.close(fig)
    print("  15  Daily volume by flow %")


# =========================================================================
# Chart 6 (16): Daily OI by flow %
# =========================================================================
def plot_daily_oi(df, out: Path):
    fig, ax = plt.subplots(figsize=(16, 6))
    ax.set_title("Daily open interest by flow %", fontsize=13, fontweight="bold")

    dates = [day_to_date(d) for d in range(SIM_DAYS)]
    max_open = 10_000_000

    for flow in FLOW_FRACS:
        mask = df["sampleKey"] <= flow
        sub = df[mask]
        paper_notional = np.minimum(sub["notional"].values, max_open)

        oi_delta = np.zeros(SIM_DAYS + 1)
        for od, cd, pn in zip(sub["openDay"].values, sub["closeDay"].values, paper_notional):
            if od < 0 or od >= SIM_DAYS:
                continue
            oi_delta[od] += pn
            oi_delta[min(SIM_DAYS, cd + 1)] -= pn

        oi = np.cumsum(oi_delta[:SIM_DAYS])
        ax.plot(dates, oi, color=FLOW_COLORS[flow], lw=1.8, alpha=0.85,
                label=f"{FLOW_LABELS[flow]} (peak ${oi.max()/1e9:.1f}B)")

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(usd_fmt))
    dates_axis(ax)
    ax.set_ylabel("Open interest")
    ax.legend(fontsize=9)

    fig.tight_layout()
    fig.savefig(out / "X16_daily_oi_by_flow.png", bbox_inches="tight")
    plt.close(fig)
    print("  16  Daily OI by flow %")


# =========================================================================
# Chart 7 (17): Liquidation rate by flow % vs start day
# =========================================================================
def plot_liq_rate(results, out: Path):
    fig, ax = plt.subplots(figsize=(16, 6))
    ax.set_title("Liquidation rate by flow % (default params, ADL off)",
                 fontsize=13, fontweight="bold")

    mask_base = (np.isclose(results["btcBaseRate"], 0.05) &
                 np.isclose(results["btcReferenceNotional"], 100_000) &
                 np.isclose(results["ethReferenceNotional"], 50_000) &
                 (results["adlWorstCase"] == False))
    if "emissionBased" in results.columns:
        mask_base &= (results["emissionBased"] == False)

    for flow in FLOW_FRACS:
        mask = mask_base & (np.isclose(results["sampleFraction"], flow))
        data = results[mask].sort_values("startDay")
        if data.empty:
            continue
        x_dates = [day_to_date(d) for d in data["startDay"]]
        ax.plot(x_dates, data["liqPct"], color=FLOW_COLORS[flow], lw=2,
                alpha=0.85, marker=".", markersize=3,
                label=f"{FLOW_LABELS[flow]} (avg {data['liqPct'].mean():.1f}%)")

    ax.set_ylabel("Liquidation rate (%)")
    ax.set_ylim(80, 90)
    dates_axis(ax)
    ax.legend(fontsize=9)

    fig.tight_layout()
    fig.savefig(out / "X17_liq_rate_by_flow.png", bbox_inches="tight")
    plt.close(fig)
    print("  17  Liquidation rate by flow %")


# =========================================================================
# Charts 8-9 (18-19): LP gains/losses distribution per flow %
# =========================================================================
def plot_lp_distributions(df, out: Path):
    max_open = 10_000_000
    leverage = 1000.0
    tolerance = 1.0 / leverage - 5.0 / 10_000  # 0.00095

    # Impact scale (default params)
    def impact_scale(move_pct, is_btc):
        if move_pct <= 0:
            return 0.0
        base = 0.05
        rm = 1000.0
        pm = 10_000_000.0
        rn = 100_000.0 if is_btc else 50_000.0
        t1 = 1.0 / (move_pct * rm)
        t2 = rn / (move_pct * pm)
        return max(0.0, min(1.0, (1.0 - base) / (1.0 + t1 + t2)))

    fig, axes = plt.subplots(2, len(FLOW_FRACS), figsize=(5 * len(FLOW_FRACS), 8))
    fig.suptitle("LP gains & losses distribution by flow %\n(log₁₀ scale, default params)",
                 fontsize=14, fontweight="bold")

    for col, flow in enumerate(FLOW_FRACS):
        mask = df["sampleKey"] <= flow
        sub = df[mask]

        notional = sub["notional"].values
        paper_not = np.minimum(notional, max_open)
        margin = paper_not / leverage
        close_move = sub["closeMovePct"].values
        adverse = sub["adversePct"].values
        is_btc = sub["is_btc"].values

        gains = []
        losses = []

        for i in range(len(sub)):
            liq = adverse[i] >= tolerance
            if liq:
                gains.append(margin[i])
            elif close_move[i] * paper_not[i] >= 0:
                # Winner — LP pays
                raw = close_move[i] * paper_not[i]
                sc = impact_scale(abs(close_move[i]), is_btc[i])
                losses.append(raw * sc)
            else:
                # Loser — LP gains
                gains.append(-close_move[i] * paper_not[i])

        gains = np.array(gains)
        losses = np.array(losses)

        # LP gains histogram
        ax = axes[0, col]
        ax.set_title(f"{FLOW_LABELS[flow]}", fontsize=11)
        g_pos = gains[gains > 0]
        if len(g_pos):
            ax.hist(np.log10(g_pos), bins=60, color="#1769e0", alpha=0.7, edgecolor="none")
        ax.set_xlabel("log₁₀(gain $)")
        if col == 0:
            ax.set_ylabel(f"LP gains\n({len(g_pos):,} trades)")
        else:
            ax.set_ylabel(f"({len(g_pos):,} trades)")

        # LP losses histogram
        ax = axes[1, col]
        l_pos = losses[losses > 0]
        if len(l_pos):
            ax.hist(np.log10(l_pos), bins=60, color="#e05f2b", alpha=0.7, edgecolor="none")
        ax.set_xlabel("log₁₀(loss $)")
        if col == 0:
            ax.set_ylabel(f"LP losses\n({len(l_pos):,} trades)")
        else:
            ax.set_ylabel(f"({len(l_pos):,} trades)")

    fig.tight_layout()
    fig.savefig(out / "X18_lp_gains_losses_dist.png", bbox_inches="tight")
    plt.close(fig)
    print("  18  LP gains & losses distribution per flow %")


# =========================================================================
# Chart 10 (20): Position notional distribution — before/after P99.9
# =========================================================================
def plot_notional_distribution(df, out: Path):
    notional = df["notional"].values
    notional = notional[notional > 0]

    p999 = np.percentile(notional, 99.9)
    scale_factor = 10_000_000 / p999

    # Current: hard cap at $10M
    capped = np.minimum(notional, 10_000_000)

    # Proposed: remove outliers > P99.9, scale rest
    keep_mask = notional <= p999
    normalized = notional[keep_mask] * scale_factor

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    fig.suptitle("Position notional distribution — normalization comparison",
                 fontsize=14, fontweight="bold")

    # Raw
    ax = axes[0]
    ax.set_title("Raw (from Hyperliquid)")
    ax.hist(np.log10(notional[notional > 0]), bins=80, color="#59636f", alpha=0.7, edgecolor="none")
    ax.axvline(np.log10(10_000_000), color="#e05f2b", ls="--", lw=1.5, label="$10M cap")
    ax.axvline(np.log10(p999), color="#1769e0", ls="--", lw=1.5, label=f"P99.9 (${p999/1e6:.1f}M)")
    ax.set_xlabel("log₁₀(notional $)")
    ax.set_ylabel("Trade count")
    ax.legend(fontsize=8)

    # Current: hard cap
    ax = axes[1]
    ax.set_title("Current: hard cap at $10M")
    ax.hist(np.log10(capped[capped > 0]), bins=80, color="#f7931a", alpha=0.7, edgecolor="none")
    ax.axvline(np.log10(10_000_000), color="#e05f2b", ls="--", lw=1.5, label="$10M cap")
    ax.set_xlabel("log₁₀(notional $)")
    n_capped = (notional > 10_000_000).sum()
    ax.text(0.95, 0.95, f"{n_capped:,} trades capped\n({100*n_capped/len(notional):.2f}%)",
            transform=ax.transAxes, ha="right", va="top", fontsize=9,
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))
    ax.legend(fontsize=8)

    # Proposed: P99.9 normalized
    ax = axes[2]
    ax.set_title(f"Proposed: P99.9 norm (×{scale_factor:.3f})")
    ax.hist(np.log10(normalized[normalized > 0]), bins=80, color="#18936a", alpha=0.7, edgecolor="none")
    ax.axvline(np.log10(10_000_000), color="#e05f2b", ls="--", lw=1.5, label="$10M")
    ax.set_xlabel("log₁₀(notional $)")
    ax.text(0.95, 0.95, f"{(~keep_mask).sum():,} outliers removed\n({100*(~keep_mask).sum()/len(notional):.2f}%)",
            transform=ax.transAxes, ha="right", va="top", fontsize=9,
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))
    ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out / "X19_notional_distribution.png", bbox_inches="tight")
    plt.close(fig)
    print("  19  Position notional distribution (raw / cap / P99.9)")


# =========================================================================
# Main
# =========================================================================
def main():
    setup_style()

    trades_path = Path("/Volumes/External/HyperliquidData/max_lev_trades_v3.parquet")
    results_path = Path("batch_results.csv")
    out = Path("charts")
    out.mkdir(exist_ok=True)

    results = pd.read_csv(results_path)
    df = load_trades(trades_path)

    plot_daily_volume(df, out)
    plot_daily_oi(df, out)
    plot_liq_rate(results, out)
    plot_lp_distributions(df, out)
    plot_notional_distribution(df, out)

    print(f"\nAll extra charts saved to {out}/")


if __name__ == "__main__":
    main()
