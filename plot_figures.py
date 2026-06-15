#!/usr/bin/env python3
"""
plot_figures.py — Generate publication-quality charts (F04-F15 + tables)
from existing PaperTrade LP simulation output.

Uses batch daily CSVs (batch_daily_*.csv) for the CORRECT per-flow daily series,
NOT the single-run simulate_paper_lp.py output (which has a minting bug post-cap).
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore")

from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib
matplotlib.rcParams["mathtext.default"] = "regular"
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import matplotlib.dates as mdates
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd

# ── constants ──
START_DATE = datetime(2025, 8, 1, tzinfo=timezone.utc)
START_MS   = 1754006400000
DAY_MS     = 86_400_000
SIM_DAYS   = 290

FLOWS       = [0.25, 0.50, 0.75, 1.00]
FLOW_COLORS = {0.25: "#a855f7", 0.50: "#f7931a", 0.75: "#1769e0", 1.0: "#18936a"}
FLOW_LABELS = {0.25: "25% flow", 0.50: "50% flow", 0.75: "75% flow", 1.0: "100% flow"}
MINT_COST   = 0.01   # floor

STAKED_FRACS  = [0.10, 0.20, 0.30, 0.50, 0.70, 0.80]
_cmap = plt.cm.viridis
STAKED_COLORS = {s: _cmap(i / (len(STAKED_FRACS) - 1)) for i, s in enumerate(STAKED_FRACS)}
STAKED_LABELS = {s: f"{int(s*100)}% staked" for s in STAKED_FRACS}

OUT = Path("charts")
OUT.mkdir(exist_ok=True)

SUBTITLE_STYLE = dict(fontsize=8.5, color="#666666", style="italic")


def E(s: str) -> str:
    """Escape dollar signs so matplotlib doesn't enter math mode."""
    return s.replace("$", r"\$")


def setup_style():
    plt.rcParams.update({
        "font.family": "sans-serif", "font.size": 10,
        "axes.titlesize": 12, "axes.titleweight": "bold",
        "axes.labelsize": 10, "axes.grid": True,
        "grid.alpha": 0.25, "grid.linewidth": 0.5,
        "figure.facecolor": "white", "axes.facecolor": "white",
        "figure.dpi": 150,
    })


# ── data loading from batch daily CSVs (authoritative source) ──
def _scenario_id(flow: float, em: bool = False) -> str:
    flow_pct = int(flow * 100)
    em_tag = "emOn" if em else "emOff"
    return f"br=0.05_btcRN=100000_ethRN=50000_flow={flow_pct}%_start=d0_adl=off_{em_tag}"


# Cache raw CSVs
_CSV_CACHE: dict[str, pd.DataFrame] = {}

def _get_csv(name: str) -> pd.DataFrame:
    if name not in _CSV_CACHE:
        _CSV_CACHE[name] = pd.read_csv(name, index_col=0)
    return _CSV_CACHE[name]


def load_daily(flow: float, em: bool = False) -> pd.DataFrame:
    sid = _scenario_id(flow, em)
    lp      = _get_csv("batch_daily_lp.csv").loc[sid].values.astype(float)
    paper   = _get_csv("batch_daily_paper.csv").loc[sid].values.astype(float)
    stakers = _get_csv("batch_daily_stakers.csv").loc[sid].values.astype(float)
    tail    = _get_csv("batch_daily_tail.csv").loc[sid].values.astype(float)

    n = len(lp)
    df = pd.DataFrame({
        "day": [START_DATE + timedelta(days=i) for i in range(n)],
        "day_idx": np.arange(n),
        "lp_balance_usd": lp,
        "paper_total_supply": paper,
        "stakers_balance_usd": stakers,
        "tail_progress_usd": tail,
    })
    df["daily_paper_minted"] = df["paper_total_supply"].diff()
    df["daily_staker_fees"]  = df["stakers_balance_usd"].diff()
    df["daily_lp_delta"]     = df["lp_balance_usd"].diff()
    return df


_DAILY_CACHE: dict[tuple, pd.DataFrame] = {}

def load_all_daily() -> dict[float, pd.DataFrame]:
    out = {}
    for f in FLOWS:
        out[f] = load_daily(f)
    return out


def load_emission_daily() -> dict[float, pd.DataFrame]:
    out = {}
    for f in FLOWS:
        out[f] = load_daily(f, em=True)
    return out


def dates_axis(ax, df):
    ax.set_xlim(df["day"].iloc[0], df["day"].iloc[-1])
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)


def find_crossing_day(df, col, threshold):
    above = df[df[col] >= threshold]
    return above.index[0] if len(above) else None


# =========================================================================
# F04: PAPER inflation rate over time
# =========================================================================
def plot_f04(daily_all):
    fig, ax = plt.subplots(figsize=(14, 6))
    ax.set_title(E("PAPER inflation rate over time, by flow"), pad=18)
    ax.text(0.5, 1.02, E("Default params: baseRate 5%, btcRef $100K, ethRef $50K, ADL off"),
            transform=ax.transAxes, ha="center", **SUBTITLE_STYLE)

    for fl in FLOWS:
        df = daily_all[fl].iloc[1:]
        daily_rate = df["daily_paper_minted"] / df["paper_total_supply"]
        annual_rate = daily_rate * 365 * 100
        smooth = annual_rate.rolling(7, min_periods=1).mean()
        ax.plot(df["day"], smooth, color=FLOW_COLORS[fl], lw=1.8,
                label=E(f"{FLOW_LABELS[fl]} (final {smooth.iloc[-1]:.1f}%)"))

    # Mark LP = $2M crossing (100% flow)
    df_full = daily_all[1.0]
    cross_2m = find_crossing_day(df_full, "lp_balance_usd", 2_000_000)
    if cross_2m is not None:
        ax.axvline(df_full.loc[cross_2m, "day"], color="red", ls="--", lw=1.2, alpha=0.7)
        ax.text(df_full.loc[cross_2m, "day"], ax.get_ylim()[1] * 0.85,
                E("  LP = $2M\n  (decay starts)"), fontsize=8, color="red", va="top")

    ax.set_ylabel("Annualized inflation rate (%)")
    ax.set_ylim(bottom=0)
    ax.legend(fontsize=9)
    dates_axis(ax, daily_all[1.0])
    fig.tight_layout()
    fig.savefig(OUT / "F04_inflation_rate.png", bbox_inches="tight")
    plt.close(fig)

    finals = {}
    for fl in FLOWS:
        df = daily_all[fl].iloc[1:]
        smooth = (df["daily_paper_minted"] / df["paper_total_supply"] * 365 * 100).rolling(7, min_periods=1).mean()
        finals[fl] = smooth.iloc[-1]
    print(f"  F04: Finals: " + ", ".join(f"{int(fl*100)}%={finals[fl]:.1f}%" for fl in FLOWS))


# =========================================================================
# F05: Cumulative staker fees — base model vs emission-based
# =========================================================================
def plot_f05(daily_all, daily_em):
    fig, (ax_l, ax_r) = plt.subplots(1, 2, figsize=(20, 7), sharey=True)
    fig.suptitle(E("Cumulative staker fees over time (USDC)"),
                 fontsize=14, fontweight="bold", y=1.0)

    # ── Left: Base model ──
    ax_l.set_title("Base model", fontsize=12)
    for fl in FLOWS:
        df = daily_all[fl]
        ax_l.plot(df["day"], df["stakers_balance_usd"] / 1e6,
                  color=FLOW_COLORS[fl], lw=2.2,
                  label=E(f"{FLOW_LABELS[fl]} (${df['stakers_balance_usd'].iloc[-1]/1e6:.0f}M)"))
    ax_l.set_ylabel(E("Cumulative staker fees ($M)"))
    ax_l.set_ylim(bottom=0)
    ax_l.legend(fontsize=9)
    dates_axis(ax_l, daily_all[1.0])

    # ── Right: Emission-based (volume-based / pessimistic) ──
    ax_r.set_title("Emission-based (pessimistic)", fontsize=12)
    for fl in FLOWS:
        df = daily_em[fl]
        ax_r.plot(df["day"], df["stakers_balance_usd"] / 1e6,
                  color=FLOW_COLORS[fl], lw=2.2,
                  label=E(f"{FLOW_LABELS[fl]} (${df['stakers_balance_usd'].iloc[-1]/1e6:.0f}M)"))
    ax_r.legend(fontsize=9)
    dates_axis(ax_r, daily_em[1.0])

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(OUT / "F05_staker_base_vs_emission.png", bbox_inches="tight")
    plt.close(fig)

    for fl in FLOWS:
        b = daily_all[fl]["stakers_balance_usd"].iloc[-1]
        e = daily_em[fl]["stakers_balance_usd"].iloc[-1]
        print(f"  F05: {int(fl*100)}% flow: base=${b/1e6:.0f}M, emission=${e/1e6:.0f}M ({e/b*100:.0f}%)")


# =========================================================================
# F05b: Cumulative PAPER supply — base model vs emission-based
# =========================================================================
def plot_f05b(daily_all, daily_em):
    fig, (ax_l, ax_r) = plt.subplots(1, 2, figsize=(20, 7), sharey=True)
    fig.suptitle(E("Cumulative PAPER supply over time"),
                 fontsize=14, fontweight="bold", y=1.0)

    # ── Left: Base model ──
    ax_l.set_title("Base model", fontsize=12)
    for fl in FLOWS:
        df = daily_all[fl]
        ax_l.plot(df["day"], df["paper_total_supply"] / 1e9,
                  color=FLOW_COLORS[fl], lw=2.2,
                  label=E(f"{FLOW_LABELS[fl]} ({df['paper_total_supply'].iloc[-1]/1e9:.2f}B)"))
    ax_l.set_ylabel("PAPER supply (billions)")
    ax_l.set_ylim(bottom=0)
    ax_l.legend(fontsize=9)
    dates_axis(ax_l, daily_all[1.0])

    # ── Right: Emission-based ──
    ax_r.set_title("Emission-based (pessimistic)", fontsize=12)
    for fl in FLOWS:
        df = daily_em[fl]
        ax_r.plot(df["day"], df["paper_total_supply"] / 1e9,
                  color=FLOW_COLORS[fl], lw=2.2,
                  label=E(f"{FLOW_LABELS[fl]} ({df['paper_total_supply'].iloc[-1]/1e9:.2f}B)"))
    ax_r.legend(fontsize=9)
    dates_axis(ax_r, daily_em[1.0])

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(OUT / "F05b_paper_supply_base_vs_emission.png", bbox_inches="tight")
    plt.close(fig)

    for fl in FLOWS:
        b = daily_all[fl]["paper_total_supply"].iloc[-1]
        e = daily_em[fl]["paper_total_supply"].iloc[-1]
        print(f"  F05b: {int(fl*100)}% flow: base={b/1e9:.2f}B, emission={e/1e9:.2f}B ({e/b*100:.0f}%)")


# =========================================================================
# F06: Staker yield split at $5M cap
# =========================================================================
def plot_f06(daily_all):
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.set_title(E("Staker yield split: pre-cap vs post-cap overflow"), pad=18)
    ax.text(0.5, 1.02, E("Pre-cap = fees while LP < $5M (2% slice); Post-cap = overflow after LP = $5M"),
            transform=ax.transAxes, ha="center", **SUBTITLE_STYLE)

    pre_caps, post_caps = [], []
    labels_list, colors = [], []

    for fl in FLOWS:
        df = daily_all[fl]
        cross_idx = find_crossing_day(df, "lp_balance_usd", 5_000_000)
        if cross_idx is not None:
            pre_cap = df.loc[cross_idx, "stakers_balance_usd"]
            post_cap = df["stakers_balance_usd"].iloc[-1] - pre_cap
        else:
            pre_cap = df["stakers_balance_usd"].iloc[-1]
            post_cap = 0
        pre_caps.append(pre_cap)
        post_caps.append(post_cap)
        labels_list.append(FLOW_LABELS[fl])
        colors.append(FLOW_COLORS[fl])

    x = np.arange(len(FLOWS))
    width = 0.55
    ax.bar(x, pre_caps, width, label=E("Pre-cap (LP < $5M, 2% slice)"),
           color=colors, alpha=0.4, edgecolor="black", linewidth=0.5)
    ax.bar(x, post_caps, width, bottom=pre_caps,
           label=E("Post-cap overflow (LP = $5M)"),
           color=colors, alpha=0.85, edgecolor="black", linewidth=0.5)

    for i, (pre, post) in enumerate(zip(pre_caps, post_caps)):
        total = pre + post
        pct_pre = 100 * pre / total if total > 0 else 0
        ax.text(i, total + total * 0.01, f"Pre-cap: {pct_pre:.2f}%",
                ha="center", fontsize=9, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(labels_list, fontsize=11)
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(
        lambda v, _: E(f"${v/1e6:.0f}M")))
    ax.set_ylabel("Cumulative staker fees (USD)")
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "F06_fee_split_cap.png", bbox_inches="tight")
    plt.close(fig)


# =========================================================================
# F07: Early zoom — emission vs staker fees, ALL flows (2×2)
# =========================================================================
def plot_f07(daily_all):
    fig, axes = plt.subplots(2, 2, figsize=(20, 14))
    fig.suptitle(E("Early window: daily emission peak vs cumulative staker fees"),
                 fontsize=14, fontweight="bold", y=0.99)

    EARLY_DAYS = 91  # first 90 days

    for idx, fl in enumerate(FLOWS):
        ax1 = axes[idx // 2, idx % 2]
        df_full = daily_all[fl]
        df = df_full.iloc[1:EARLY_DAYS]

        ax1.set_title(FLOW_LABELS[fl], fontsize=12, fontweight="bold")

        # Daily minting (left axis)
        ax1.fill_between(df["day"], df["daily_paper_minted"] / 1e6, alpha=0.25, color="#a855f7")
        ax1.plot(df["day"], df["daily_paper_minted"] / 1e6, color="#a855f7", lw=1.5,
                 label=E("Daily PAPER minted (M)"))
        ax1.set_ylabel(E("Daily PAPER minted (M)"), color="#a855f7", fontsize=9)
        ax1.tick_params(axis="y", labelcolor="#a855f7")
        ax1.set_ylim(bottom=0)

        # Peak annotation
        peak_idx = df["daily_paper_minted"].idxmax()
        peak_val = df.loc[peak_idx, "daily_paper_minted"]
        peak_date = df.loc[peak_idx, "day"]
        peak_day_num = df.loc[peak_idx, "day_idx"]
        ax1.plot(peak_date, peak_val / 1e6, "v", color="#7c3aed", markersize=8, zorder=5)
        ax1.annotate(E(f"Peak: {peak_val/1e6:.0f}M (d{peak_day_num})"),
                    (peak_date, peak_val / 1e6),
                    textcoords="offset points", xytext=(8, 6), fontsize=7.5,
                    color="#7c3aed", fontweight="bold",
                    arrowprops=dict(arrowstyle="->", color="#7c3aed", lw=0.8))

        # Cumulative staker fees (right axis)
        ax2 = ax1.twinx()
        ax2.plot(df["day"], df["stakers_balance_usd"] / 1e6, color="#18936a", lw=2,
                 label=E("Cum. staker fees ($M)"))
        ax2.set_ylabel(E("Cum. staker fees ($M)"), color="#18936a", fontsize=9)
        ax2.tick_params(axis="y", labelcolor="#18936a")
        ax2.set_ylim(bottom=0)

        # $2M and $5M crossings
        cross_2m = find_crossing_day(df_full, "lp_balance_usd", 2_000_000)
        cross_5m = find_crossing_day(df_full, "lp_balance_usd", 5_000_000)
        ylim_top = ax1.get_ylim()[1]
        if cross_2m is not None:
            ax1.axvline(df_full.loc[cross_2m, "day"], color="red", ls="--", lw=1.3, alpha=0.7)
            ax1.text(df_full.loc[cross_2m, "day"], ylim_top * 0.92,
                     E(f" $2M (d{df_full.loc[cross_2m, 'day_idx']})"),
                     fontsize=7, color="red", va="top")
        if cross_5m is not None:
            ax1.axvline(df_full.loc[cross_5m, "day"], color="blue", ls="--", lw=1.3, alpha=0.7)
            ax1.text(df_full.loc[cross_5m, "day"], ylim_top * 0.78,
                     E(f" $5M (d{df_full.loc[cross_5m, 'day_idx']})"),
                     fontsize=7, color="blue", va="top")

        # Combined legend
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=7.5, loc="upper right")

        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax1.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=7)

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(OUT / "F07_early_zoom.png", bbox_inches="tight")
    plt.close(fig)

    for fl in FLOWS:
        df = daily_all[fl].iloc[1:EARLY_DAYS]
        pk = df["daily_paper_minted"].max()
        pkd = df.loc[df["daily_paper_minted"].idxmax(), "day_idx"]
        c2 = find_crossing_day(daily_all[fl], "lp_balance_usd", 2_000_000)
        c5 = find_crossing_day(daily_all[fl], "lp_balance_usd", 5_000_000)
        d2 = daily_all[fl].loc[c2, "day_idx"] if c2 is not None else "—"
        d5 = daily_all[fl].loc[c5, "day_idx"] if c5 is not None else "—"
        print(f"  F07: {int(fl*100)}% flow: peak={pk/1e6:.0f}M (d{pkd}), "
              f"$2M=d{d2}, $5M=d{d5}")


# =========================================================================
# F09: Real yield — 2×2 grid (flow × staked fraction)
# =========================================================================
def plot_f09(daily_all):
    fig, axes = plt.subplots(2, 2, figsize=(18, 14))
    fig.suptitle(E("Inflation-adjusted real yield per staked token over time"),
                 fontsize=14, fontweight="bold", y=0.99)

    for idx, fl in enumerate(FLOWS):
        ax = axes[idx // 2, idx % 2]
        ax.set_title(FLOW_LABELS[fl], fontsize=12, fontweight="bold")
        df = daily_all[fl].copy()

        for sf in STAKED_FRACS:
            staked_supply = sf * df["paper_total_supply"]
            daily_yield = df["daily_staker_fees"].fillna(0) / staked_supply
            real_yield = daily_yield.cumsum()
            nominal_yield = df["stakers_balance_usd"] / staked_supply
            ax.plot(df["day"], real_yield, color=STAKED_COLORS[sf], lw=1.8,
                    label=E(f"{STAKED_LABELS[sf]} (${real_yield.iloc[-1]:.3f})") if idx == 0 else
                          E(f"{STAKED_LABELS[sf]} (${real_yield.iloc[-1]:.3f})"))
            ax.plot(df["day"], nominal_yield, color=STAKED_COLORS[sf], lw=0.8, ls="--", alpha=0.4)

        if idx == 0:
            ax.plot([], [], color="gray", ls="--", lw=0.8, alpha=0.4, label="Nominal (dashed)")
        ax.set_ylabel(E("Yield per staked token ($)"))
        ax.legend(fontsize=7.5, loc="upper left")
        dates_axis(ax, df)

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(OUT / "F09_real_yield.png", bbox_inches="tight")
    plt.close(fig)

    for fl in FLOWS:
        df = daily_all[fl]
        for sf in [0.10, 0.20, 0.50, 0.80]:
            ss = sf * df["paper_total_supply"]
            r = (df["daily_staker_fees"].fillna(0) / ss).cumsum().iloc[-1]
            n = df["stakers_balance_usd"].iloc[-1] / ss.iloc[-1]
            print(f"  F09: {int(fl*100)}% flow / {int(sf*100)}% staked -> real=${r:.3f}, nominal=${n:.3f}")


# =========================================================================
# F10: Payback multiples — 2×2 grid (flow × staked fraction)
# =========================================================================
def plot_f10(daily_all):
    fig, axes = plt.subplots(2, 2, figsize=(18, 14))
    fig.suptitle(E("Cumulative fee yield vs mint cost: payback in multiples of $0.01 floor"),
                 fontsize=14, fontweight="bold", y=0.99)

    for idx, fl in enumerate(FLOWS):
        ax = axes[idx // 2, idx % 2]
        ax.set_title(FLOW_LABELS[fl], fontsize=12, fontweight="bold")
        df = daily_all[fl].copy()

        max_mult = 0
        for sf in STAKED_FRACS:
            staked_supply = sf * df["paper_total_supply"]
            real_yield = (df["daily_staker_fees"].fillna(0) / staked_supply).cumsum()
            multiple = real_yield / MINT_COST
            ax.plot(df["day"], multiple, color=STAKED_COLORS[sf], lw=1.8,
                    label=E(f"{STAKED_LABELS[sf]} ({multiple.iloc[-1]:.1f}x)"))
            max_mult = max(max_mult, multiple.iloc[-1])

        for ref, label in [(1, "1x"), (6, "6x"), (15, "15x"), (30, "30x")]:
            if ref <= max_mult * 1.3:
                ax.axhline(ref, color="gray", ls=":", lw=0.8, alpha=0.5)
                ax.text(df["day"].iloc[-1], ref, f"  {label}",
                        va="bottom", fontsize=7, color="gray")
        ax.set_ylabel(E("Payback multiple (x of $0.01)"))
        ax.set_ylim(bottom=0)
        ax.legend(fontsize=7.5, loc="upper left")
        dates_axis(ax, df)

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(OUT / "F10_payback.png", bbox_inches="tight")
    plt.close(fig)

    for fl in FLOWS:
        df = daily_all[fl]
        for sf in [0.10, 0.20, 0.50, 0.80]:
            ss = sf * df["paper_total_supply"]
            m = (df["daily_staker_fees"].fillna(0) / ss).cumsum().iloc[-1] / MINT_COST
            print(f"  F10: {int(fl*100)}% flow / {int(sf*100)}% staked -> {m:.1f}x")


# =========================================================================
# F11: Lifetime staker yield by entry-day cohort — 2×2 grid
# =========================================================================
def _cohort_curve(df, staked_frac):
    """Return (dates_arr, rev_cumsum) for a cohort yield curve."""
    n = len(df)
    staked_supply = staked_frac * df["paper_total_supply"].values
    daily_fee_pt = df["daily_staker_fees"].fillna(0).values / staked_supply
    rev_cumsum = np.flip(np.cumsum(np.flip(daily_fee_pt)))
    dates_arr = [START_DATE + timedelta(days=int(d)) for d in range(n)]
    return dates_arr, rev_cumsum


def plot_f11(daily_all):
    fig, axes = plt.subplots(2, 2, figsize=(18, 14))
    fig.suptitle(E("Lifetime staker yield by entry-day cohort"),
                 fontsize=14, fontweight="bold", y=0.99)

    for idx, fl in enumerate(FLOWS):
        ax = axes[idx // 2, idx % 2]
        ax.set_title(FLOW_LABELS[fl], fontsize=12, fontweight="bold")
        df = daily_all[fl]

        for sf in STAKED_FRACS:
            dates_arr, rev = _cohort_curve(df, sf)
            ax.plot(dates_arr, rev, color=STAKED_COLORS[sf], lw=1.8,
                    label=E(f"{STAKED_LABELS[sf]} (d0: ${rev[0]:.3f})"))

        # Annotate day reference points for 20% staked
        dates_arr, rev = _cohort_curve(df, 0.20)
        for lbl, didx in [("d0", 0), ("d30", 30), ("d90", 90), ("d180", 180)]:
            if didx < len(rev):
                ax.plot(dates_arr[didx], rev[didx], "o", color=STAKED_COLORS[0.20],
                        markersize=3, zorder=5)
                ax.annotate(E(f"{lbl}:${rev[didx]:.3f}"),
                           (dates_arr[didx], rev[didx]),
                           textcoords="offset points", xytext=(6, 3), fontsize=6.5)

        ax.set_ylabel(E("Lifetime yield per staked token ($)"))
        ax.legend(fontsize=7.5, loc="upper right")
        dates_axis(ax, df)

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(OUT / "F11_cohort_yield.png", bbox_inches="tight")
    plt.close(fig)

    for fl in FLOWS:
        for sf in [0.10, 0.20, 0.50, 0.80]:
            _, rev = _cohort_curve(daily_all[fl], sf)
            print(f"  F11: {int(fl*100)}% flow / {int(sf*100)}% staked -> d0=${rev[0]:.3f}, "
                  f"d30=${rev[30]:.3f}, d90=${rev[90]:.3f}")


# =========================================================================
# F12: Concentration (Lorenz) — all 4 flows
# =========================================================================
def plot_f12(daily_all):
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.set_title(E("Share of total staker fees captured by\nthe first X% of losers to arrive"), pad=18)
    ax.text(0.5, 1.01, "Default params. Lorenz-style curve by arrival order (trade-level, all flows).",
            transform=ax.transAxes, ha="center", **SUBTITLE_STYLE)

    # Load trades for per-day trade counts (NOT their buggy minting amounts)
    trades = pd.read_parquet("sim_flow_1.00/paper_sim_trades.parquet",
                             columns=["open_time_ms"])
    trades["day"] = ((trades["open_time_ms"] - START_MS) / DAY_MS).astype(int).clip(0, SIM_DAYS - 1)
    trades_per_day_100 = trades.groupby("day").size()

    pct_vals_all = {}

    for fl in FLOWS:
        df = daily_all[fl].copy()
        n_days = len(df)
        staked_supply = 0.20 * df["paper_total_supply"].values
        daily_fee_pt = df["daily_staker_fees"].fillna(0).values / staked_supply
        rev_cumsum = np.flip(np.cumsum(np.flip(daily_fee_pt)))
        daily_minted = df["daily_paper_minted"].fillna(0).values
        daily_minted = np.maximum(daily_minted, 0)

        # Scale trade counts by flow fraction
        fee_list = []
        for d in range(n_days):
            n_trades = int(trades_per_day_100.get(d, 0) * fl)
            if n_trades == 0 or daily_minted[d] <= 0:
                continue
            per_trade_fee = (daily_minted[d] / n_trades) * rev_cumsum[d]
            fee_list.extend([per_trade_fee] * n_trades)

        fees_arr = np.array(fee_list)
        if len(fees_arr) == 0:
            continue
        total = fees_arr.sum()
        cum_pct = np.cumsum(fees_arr) / total * 100
        x_pct = np.arange(1, len(cum_pct) + 1) / len(cum_pct) * 100

        ax.plot(x_pct, cum_pct, color=FLOW_COLORS[fl], lw=2,
                label=FLOW_LABELS[fl])

        pvs = {}
        for pct in [5, 10, 25]:
            idx = int(len(cum_pct) * pct / 100)
            pvs[pct] = cum_pct[min(idx, len(cum_pct) - 1)]
        pct_vals_all[fl] = pvs

    ax.plot([0, 100], [0, 100], "k--", lw=0.8, alpha=0.4, label="Perfect equality")

    # Annotate 100% flow callouts
    if 1.0 in pct_vals_all:
        for pct, val in pct_vals_all[1.0].items():
            ax.plot(pct, val, "o", color="#e05f2b", markersize=7, zorder=5)
            ax.annotate(f"{val:.1f}%", (pct, val),
                       textcoords="offset points", xytext=(8, -8), fontsize=8.5,
                       fontweight="bold", color="#e05f2b")

    ax.set_xlabel("Percentile of losers by arrival time (%)")
    ax.set_ylabel("Cumulative share of total staker fees (%)")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "F12_concentration.png", bbox_inches="tight")
    plt.close(fig)

    for fl in FLOWS:
        if fl in pct_vals_all:
            p = pct_vals_all[fl]
            print(f"  F12: {int(fl*100)}% flow: 5%={p[5]:.1f}%, 10%={p[10]:.1f}%, 25%={p[25]:.1f}%")


# =========================================================================
# F13: Equilibrium implied price — all 4 flows
# =========================================================================
def plot_f13(daily_all):
    fig, axes = plt.subplots(2, 2, figsize=(16, 12), sharex=True)
    fig.suptitle(E("Equilibrium implied price per PAPER token at target annual yields"),
                 fontsize=14, fontweight="bold", y=1.0)

    target_yields = np.array([0.10, 0.20, 0.30, 0.40, 0.50])
    staked_shares = [0.20, 0.30, 0.50]
    share_colors = {0.20: "#a855f7", 0.30: "#f7931a", 0.50: "#1769e0"}

    batch = pd.read_csv("batch_results.csv")

    for idx, fl in enumerate(FLOWS):
        ax = axes[idx // 2, idx % 2]
        ax.set_title(FLOW_LABELS[fl], fontsize=11)

        df = daily_all[fl]
        cross_5m = find_crossing_day(df, "lp_balance_usd", 5_000_000)
        if cross_5m is not None and cross_5m + 1 < len(df):
            post_cap = df.iloc[cross_5m + 1:]
            daily_fee = post_cap["daily_staker_fees"].mean()
        else:
            daily_fee = df["daily_staker_fees"].iloc[-30:].mean()
        annual_fee = daily_fee * 365
        final_supply = df["paper_total_supply"].iloc[-1]

        # Get avg cost from batch
        mask = (np.isclose(batch["sampleFraction"], fl) &
                np.isclose(batch["btcBaseRate"], 0.05) &
                np.isclose(batch["btcReferenceNotional"], 100000) &
                np.isclose(batch["ethReferenceNotional"], 50000) &
                (batch["adlWorstCase"] == False) &
                (batch["emissionBased"] == False) &
                (batch["startDay"] == 0))
        row = batch[mask].iloc[0]
        avg_cost = row["costPerPaper"]

        for s in staked_shares:
            implied = annual_fee / (target_yields * s * final_supply)
            ax.plot(target_yields * 100, implied, "o-", color=share_colors[s],
                    lw=2, markersize=7,
                    label=f"{s:.0%} staked" if idx == 0 else None)

        ax.axhline(MINT_COST, color="red", ls="--", lw=1.2, alpha=0.7)
        ax.axhline(avg_cost, color="#18936a", ls=":", lw=1.2, alpha=0.7)
        if idx % 2 == 1:
            ax.text(50.5, MINT_COST, E("  $0.01 floor"), fontsize=7, color="red", va="bottom")
            ax.text(50.5, avg_cost, E(f"  ${avg_cost:.4f} avg cost"), fontsize=7, color="#18936a", va="bottom")

        ax.set_yscale("log")
        ax.set_ylabel(E("Implied price ($)"))
        ax.set_xlabel("Target annual yield (%)")
        ax.yaxis.set_major_formatter(mtick.FuncFormatter(
            lambda v, _: E(f"${v:.3f}") if v < 1 else E(f"${v:.1f}")))
        ax.set_xticks(target_yields * 100)

    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, fontsize=11,
               bbox_to_anchor=(0.5, 0.98))
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(OUT / "F13_equilibrium_yield.png", bbox_inches="tight")
    plt.close(fig)

    for fl in FLOWS:
        df = daily_all[fl]
        cross_5m = find_crossing_day(df, "lp_balance_usd", 5_000_000)
        if cross_5m is not None:
            af = df.iloc[cross_5m+1:]["daily_staker_fees"].mean() * 365
        else:
            af = df["daily_staker_fees"].iloc[-30:].mean() * 365
        p = af / (0.20 * 0.20 * df["paper_total_supply"].iloc[-1])
        print(f"  F13: {int(fl*100)}% flow: annual_fee=${af/1e6:.0f}M, "
              f"implied@20%yield/20%staked=${p:.3f}")


# =========================================================================
# F14: NPV per token across discount rates — 2×2 (flow × staked %)
# =========================================================================
def plot_f14(daily_all):
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle(E("NPV per staked token across discount rates"),
                 fontsize=14, fontweight="bold", y=1.0)

    discount_rates = np.array([0.20, 0.40, 0.60, 0.80])
    staked_shares = [0.20, 0.30, 0.50]
    share_colors = {0.20: "#a855f7", 0.30: "#f7931a", 0.50: "#1769e0"}

    for idx, fl in enumerate(FLOWS):
        ax = axes[idx // 2, idx % 2]
        ax.set_title(FLOW_LABELS[fl], fontsize=12, fontweight="bold")

        df = daily_all[fl]
        cross_5m = find_crossing_day(df, "lp_balance_usd", 5_000_000)
        if cross_5m is not None and cross_5m + 1 < len(df):
            daily_fee = df.iloc[cross_5m + 1:]["daily_staker_fees"].mean()
        else:
            daily_fee = df["daily_staker_fees"].iloc[-30:].mean()
        annual_fee = daily_fee * 365
        supply = df["paper_total_supply"].iloc[-1]

        for s in staked_shares:
            apt = annual_fee / (s * supply)
            npv_cents = (apt / discount_rates) * 100
            ax.plot(discount_rates * 100, npv_cents, "o-", color=share_colors[s],
                    lw=2, markersize=7,
                    label=E(f"{s:.0%} staked (${apt:.3f}/yr)") if idx == 0 else
                          E(f"{s:.0%} staked (${apt:.3f}/yr)"))

        ax.axhline(MINT_COST * 100, color="red", ls="--", lw=1.2, alpha=0.7)
        ax.text(81, MINT_COST * 100, E("  1c floor"), fontsize=7, color="red", va="bottom")

        ax.set_xlabel("Discount rate (%)")
        ax.set_ylabel("NPV per staked token (cents)")
        ax.legend(fontsize=8)
        ax.set_xticks(discount_rates * 100)

    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, fontsize=11,
               bbox_to_anchor=(0.5, 0.98))
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(OUT / "F14_npv.png", bbox_inches="tight")
    plt.close(fig)

    for fl in FLOWS:
        df = daily_all[fl]
        cross_5m = find_crossing_day(df, "lp_balance_usd", 5_000_000)
        if cross_5m is not None:
            af = df.iloc[cross_5m+1:]["daily_staker_fees"].mean() * 365
        else:
            af = df["daily_staker_fees"].iloc[-30:].mean() * 365
        for s in staked_shares:
            apt = af / (s * df["paper_total_supply"].iloc[-1])
            print(f"  F14: {int(fl*100)}% flow / {int(s*100)}% staked: "
                  f"fee/token=${apt:.3f}/yr, NPV@20%=${apt/0.20:.3f}")


# =========================================================================
# F15: Sensitivity — yield & inflation across grid
# =========================================================================
def plot_f15():
    batch = pd.read_csv("batch_results.csv")
    batch["yield_per_staked"] = batch["finalStakers"] / (0.20 * batch["finalPaper"])

    param_mask = (np.isclose(batch["btcBaseRate"], 0.05) &
                  np.isclose(batch["btcReferenceNotional"], 100000) &
                  np.isclose(batch["ethReferenceNotional"], 50000))

    fig, axes = plt.subplots(2, 2, figsize=(16, 10), sharex=True)
    fig.suptitle("Yield and inflation sensitivity to flow, ADL, and launch window",
                 fontsize=14, fontweight="bold", y=1.0)

    titles = [("ADL off, Base model", False, False),
              ("ADL off, Emission-based", False, True),
              ("ADL on, Base model", True, False),
              ("ADL on, Emission-based", True, True)]

    for idx, (title, adl, em) in enumerate(titles):
        ax = axes[idx // 2, idx % 2]
        ax.set_title(title, fontsize=11)
        mask = param_mask & (batch["adlWorstCase"] == adl) & (batch["emissionBased"] == em)
        sub = batch[mask]
        for fl in FLOWS:
            fl_data = sub[np.isclose(sub["sampleFraction"], fl)].sort_values("startDay")
            if fl_data.empty:
                continue
            x_dates = [START_DATE + timedelta(days=int(d)) for d in fl_data["startDay"]]
            ax.plot(x_dates, fl_data["yield_per_staked"],
                    color=FLOW_COLORS[fl], lw=1.8, marker=".", markersize=3,
                    label=f"{FLOW_LABELS[fl]}" if idx == 0 else None)
        ax.set_ylabel(E("Yield per staked token ($)"))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)

    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=4, fontsize=10,
               bbox_to_anchor=(0.5, 0.98))
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(OUT / "F15_sensitivity.png", bbox_inches="tight")
    plt.close(fig)
    print("  F15: done")


# =========================================================================
# Summary Tables
# =========================================================================
def _make_table_fig(data, col_labels, row_labels, title, filename, col_widths=None):
    """Create a publication-quality table as PNG."""
    n_rows = len(row_labels)
    n_cols = len(col_labels)
    fig_h = 1.0 + n_rows * 0.45
    fig_w = max(10, n_cols * 1.8)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.axis("off")
    ax.set_title(title, fontsize=12, fontweight="bold", pad=12)

    table = ax.table(cellText=data, colLabels=col_labels, rowLabels=row_labels,
                     loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.0, 1.6)

    # Style header
    for j in range(n_cols):
        cell = table[0, j]
        cell.set_facecolor("#2c3e50")
        cell.set_text_props(color="white", fontweight="bold")
    for i in range(n_rows):
        cell = table[i + 1, -1]
        cell.set_facecolor("#ecf0f1")

    fig.tight_layout()
    fig.savefig(OUT / filename, bbox_inches="tight", dpi=200)
    plt.close(fig)


def generate_tables(daily_all):
    # ── Table T09: Real yield per staked token ──
    col_labels = [f"{int(sf*100)}% staked" for sf in STAKED_FRACS]
    row_labels = [f"{int(fl*100)}% flow" for fl in FLOWS]
    data = []
    for fl in FLOWS:
        df = daily_all[fl]
        row = []
        for sf in STAKED_FRACS:
            ss = sf * df["paper_total_supply"]
            r = (df["daily_staker_fees"].fillna(0) / ss).cumsum().iloc[-1]
            row.append(f"${r:.3f}")
        data.append(row)
    _make_table_fig(data, col_labels, row_labels,
                    E("Real yield per staked token ($) — flow x staked fraction"),
                    "T09_real_yield_table.png")

    # ── Table T10: Payback multiples ──
    data = []
    for fl in FLOWS:
        df = daily_all[fl]
        row = []
        for sf in STAKED_FRACS:
            ss = sf * df["paper_total_supply"]
            m = (df["daily_staker_fees"].fillna(0) / ss).cumsum().iloc[-1] / MINT_COST
            row.append(f"{m:.1f}x")
        data.append(row)
    _make_table_fig(data, col_labels, row_labels,
                    E("Payback multiples (x of $0.01 mint cost) — flow x staked fraction"),
                    "T10_payback_table.png")

    # ── Table T11: Cohort yield (day 0) ──
    data = []
    for fl in FLOWS:
        df = daily_all[fl]
        row = []
        for sf in STAKED_FRACS:
            _, rev = _cohort_curve(df, sf)
            row.append(f"${rev[0]:.3f}")
        data.append(row)
    _make_table_fig(data, col_labels, row_labels,
                    E("Day-0 cohort lifetime yield ($) — flow x staked fraction"),
                    "T11_cohort_d0_table.png")

    # ── Table T11b: Cohort yield at key days (100% flow, 20% staked) ──
    days_check = [0, 30, 60, 90, 120, 150, 180, 210, 240, 270]
    col_labels2 = [f"Day {d}" for d in days_check]
    row_labels2 = [f"{int(fl*100)}% flow" for fl in FLOWS]
    data = []
    for fl in FLOWS:
        _, rev = _cohort_curve(daily_all[fl], 0.20)
        row = [f"${rev[d]:.4f}" if d < len(rev) else "—" for d in days_check]
        data.append(row)
    _make_table_fig(data, col_labels2, row_labels2,
                    E("Cohort yield by entry day ($, 20% staked) — flow x entry day"),
                    "T11b_cohort_by_day_table.png")

    # ── Table T12: Concentration ──
    col_labels3 = ["First 5%", "First 10%", "First 25%", "First 50%"]
    row_labels3 = [f"{int(fl*100)}% flow" for fl in FLOWS]
    # Recompute from batch daily
    trades = pd.read_parquet("sim_flow_1.00/paper_sim_trades.parquet",
                             columns=["open_time_ms"])
    trades["day"] = ((trades["open_time_ms"] - START_MS) / DAY_MS).astype(int).clip(0, SIM_DAYS - 1)
    tpd = trades.groupby("day").size()

    data = []
    for fl in FLOWS:
        df = daily_all[fl].copy()
        n = len(df)
        staked = 0.20 * df["paper_total_supply"].values
        dfpt = df["daily_staker_fees"].fillna(0).values / staked
        rcs = np.flip(np.cumsum(np.flip(dfpt)))
        dm = np.maximum(df["daily_paper_minted"].fillna(0).values, 0)
        fee_list = []
        for d in range(n):
            nt = int(tpd.get(d, 0) * fl)
            if nt == 0 or dm[d] <= 0:
                continue
            ptf = (dm[d] / nt) * rcs[d]
            fee_list.extend([ptf] * nt)
        fa = np.array(fee_list)
        if len(fa) == 0:
            data.append(["—"] * 4)
            continue
        cp = np.cumsum(fa) / fa.sum() * 100
        row = []
        for pct in [5, 10, 25, 50]:
            idx = int(len(cp) * pct / 100)
            row.append(f"{cp[min(idx, len(cp)-1)]:.1f}%")
        data.append(row)
    _make_table_fig(data, col_labels3, row_labels3,
                    E("Fee concentration: share captured by first X% of losers"),
                    "T12_concentration_table.png")

    # ── Table T13: Equilibrium implied price ──
    batch = pd.read_csv("batch_results.csv")
    target_yields = [0.10, 0.20, 0.30, 0.50]
    staked_shares = [0.20, 0.30, 0.50]
    col_labels4 = [f"{int(ty*100)}% yield / {int(ss*100)}% stk"
                   for ty in target_yields for ss in staked_shares]
    row_labels4 = [f"{int(fl*100)}% flow" for fl in FLOWS]
    data = []
    for fl in FLOWS:
        df = daily_all[fl]
        cross_5m = find_crossing_day(df, "lp_balance_usd", 5_000_000)
        if cross_5m is not None and cross_5m + 1 < len(df):
            af = df.iloc[cross_5m+1:]["daily_staker_fees"].mean() * 365
        else:
            af = df["daily_staker_fees"].iloc[-30:].mean() * 365
        supply = df["paper_total_supply"].iloc[-1]
        row = []
        for ty in target_yields:
            for ss in staked_shares:
                p = af / (ty * ss * supply)
                row.append(E(f"${p:.3f}"))
        data.append(row)
    _make_table_fig(data, col_labels4, row_labels4,
                    E("Implied equilibrium price ($) — yield target x staked fraction x flow"),
                    "T13_equilibrium_table.png")

    # ── Table T14: NPV per staked token ──
    disc_rates = [0.20, 0.40, 0.60, 0.80]
    col_labels5 = [f"r={int(dr*100)}%" for dr in disc_rates]
    row_labels5 = [f"{int(fl*100)}% flow" for fl in FLOWS]
    data = []
    for fl in FLOWS:
        df = daily_all[fl]
        cross_5m = find_crossing_day(df, "lp_balance_usd", 5_000_000)
        if cross_5m is not None and cross_5m + 1 < len(df):
            af = df.iloc[cross_5m+1:]["daily_staker_fees"].mean() * 365
        else:
            af = df["daily_staker_fees"].iloc[-30:].mean() * 365
        supply = df["paper_total_supply"].iloc[-1]
        apt = af / (0.20 * supply)
        row = [E(f"${apt/dr:.3f}") for dr in disc_rates]
        data.append(row)
    _make_table_fig(data, col_labels5, row_labels5,
                    E("NPV per staked token ($, 20% staked) by discount rate"),
                    "T14_npv_table.png")

    print("  Tables: T09, T10, T11, T11b, T12, T13, T14 saved")


# =========================================================================
# Main
# =========================================================================
def main():
    setup_style()
    print("Loading per-flow daily timeseries from batch CSVs...")
    daily_all = load_all_daily()
    daily_em = load_emission_daily()

    for fl in FLOWS:
        df = daily_all[fl]
        print(f"  {FLOW_LABELS[fl]}: supply={df['paper_total_supply'].iloc[-1]/1e9:.3f}B, "
              f"stakers=${df['stakers_balance_usd'].iloc[-1]/1e6:.1f}M, "
              f"tail=${df['tail_progress_usd'].iloc[-1]/1e6:.0f}M")
    print()

    print("Generating figures:\n")
    plot_f04(daily_all)
    plot_f05(daily_all, daily_em)
    plot_f05b(daily_all, daily_em)
    plot_f06(daily_all)
    plot_f07(daily_all)
    plot_f09(daily_all)
    plot_f10(daily_all)
    plot_f11(daily_all)
    plot_f12(daily_all)
    plot_f13(daily_all)
    plot_f14(daily_all)
    plot_f15()

    print("\nGenerating summary tables:\n")
    generate_tables(daily_all)

    print(f"\nAll figures and tables saved to {OUT}/")


if __name__ == "__main__":
    main()
