#!/usr/bin/env python3
"""
make_charts.py — Build a self-contained HTML report AND individual PNG charts
to inspect the Paper LP simulation output.

Reads:
  - paper_sim_trades.parquet    (per-trade outcomes)
  - paper_sim_state.parquet     (daily state)
  - paper_sim_stats.json        (summary stats)
  - paper_config.yaml           (thresholds + staking assumption)
  - max_lev_trades.parquet      (OPTIONAL — for ADL events)

Writes:
  - paper_sim_report.html       (single self-contained HTML)
  - charts/01_lp_balance.png    (individual PNGs, openable at full resolution)
  - charts/02_paper_supply.png
  - ...
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import sys
from html import escape
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mtick
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
import yaml


# -----------------------------------------------------------------------------
# Style
# -----------------------------------------------------------------------------
plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.titlesize": 12,
    "axes.titleweight": "bold",
    "axes.labelsize": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linestyle": "-",
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
})

COL_LP        = "#1f77b4"
COL_PAPER     = "#d62728"
COL_STAKERS   = "#2ca02c"
COL_TAIL      = "#9467bd"
COL_TRADERS   = "#ff7f0e"
COL_WINS      = "#17becf"
COL_NET       = "#8c564b"
COL_BTC       = "#f7931a"
COL_ETH       = "#627eea"
COL_THRESH    = "#888888"
COL_LIQ       = "#d62728"
COL_ADL       = "#5b2c87"   # deeper purple — darker base for the variable bands

# Variable-intensity ADL bands: log-scaled alpha
ADL_ALPHA_MIN = 0.10
ADL_ALPHA_MAX = 0.70


def fmt_dollars(x, _pos=None):
    ax = abs(x)
    if ax >= 1e12: return f"${x/1e12:.1f}T"
    if ax >= 1e9:  return f"${x/1e9:.1f}B"
    if ax >= 1e6:  return f"${x/1e6:.1f}M"
    if ax >= 1e3:  return f"${x/1e3:.0f}K"
    return f"${x:.0f}"


def fmt_count(x, _pos=None):
    ax = abs(x)
    if ax >= 1e12: return f"{x/1e12:.1f}T"
    if ax >= 1e9:  return f"{x/1e9:.1f}B"
    if ax >= 1e6:  return f"{x/1e6:.1f}M"
    if ax >= 1e3:  return f"{x/1e3:.0f}K"
    return f"{x:.0f}"


def add_threshold(ax, y, label, color=COL_THRESH, linestyle="--"):
    ax.axhline(y, color=color, linestyle=linestyle, linewidth=1, alpha=0.7)
    ax.text(0.99, y, f" {label}", transform=ax.get_yaxis_transform(),
            ha="right", va="bottom", fontsize=8, color=color, alpha=0.9)


def style_time_axis(ax, days):
    n = len(days) if hasattr(days, "__len__") else 0
    if n > 60:
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    else:
        ax.xaxis.set_major_locator(mdates.WeekdayLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    plt.setp(ax.get_xticklabels(), rotation=0, ha="center")


def fig_save(fig, png_path=None):
    """Save figure as PNG to png_path (if given) and return base64 string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    data = buf.getvalue()
    plt.close(fig)
    if png_path is not None:
        Path(png_path).parent.mkdir(parents=True, exist_ok=True)
        Path(png_path).write_bytes(data)
    return base64.b64encode(data).decode()


def mark_adl_bands(ax, daily, color=COL_ADL, min_adl=1):
    """Variable-intensity vertical bands for days with ADL events.
    Days with more ADLs get darker bands (log-scaled alpha)."""
    if "n_adl" not in daily.columns:
        return False, 0, 0
    df = daily.loc[daily["n_adl"] >= min_adl, ["day", "n_adl"]]
    if df.empty:
        return False, 0, 0

    max_n = int(df["n_adl"].max())
    log_max = np.log10(max_n + 1)
    days_arr = df["day"].values
    n_arr    = df["n_adl"].values.astype(np.int64)

    for d, n in zip(days_arr, n_arr):
        if log_max > 0:
            intensity = np.log10(n + 1) / log_max
        else:
            intensity = 1.0
        alpha = ADL_ALPHA_MIN + (ADL_ALPHA_MAX - ADL_ALPHA_MIN) * intensity
        ax.axvspan(d - np.timedelta64(12, "h"),
                   d + np.timedelta64(12, "h"),
                   color=color, alpha=alpha, zorder=0, linewidth=0)
    return True, max_n, int(df["n_adl"].min())


def adl_legend_handle(daily):
    if "n_adl" not in daily.columns:
        return None
    if not (daily["n_adl"] > 0).any():
        return None
    max_n = int(daily["n_adl"].max())
    return Patch(color=COL_ADL, alpha=(ADL_ALPHA_MIN + ADL_ALPHA_MAX) / 2,
                 label=f"HL ADL events (darker = more; max={max_n:,} on a day)")


# -----------------------------------------------------------------------------
# Chart builders — each accepts png_path for standalone export
# -----------------------------------------------------------------------------

def chart_lp_balance(state, cfg, daily, png_path=None):
    threshold = cfg["paper_mint"]["lp_flat_threshold_usd"]
    lp_cap    = cfg["stakers"]["lp_excess_cap_usd"]
    fig, axes = plt.subplots(2, 1, figsize=(12, 7.6), sharex=True)

    for idx, ax in enumerate(axes):
        mark_adl_bands(ax, daily)
        ax.plot(state["day"], state["lp_balance_usd"], color=COL_LP, linewidth=1.8, zorder=2)
        if idx == 0:
            ax.fill_between(state["day"], 0, state["lp_balance_usd"],
                            where=state["lp_balance_usd"] >= 0,
                            color=COL_LP, alpha=0.15, zorder=1)
            ax.fill_between(state["day"], 0, state["lp_balance_usd"],
                            where=state["lp_balance_usd"] < 0,
                            color="red", alpha=0.15, zorder=1)
        ax.axhline(0, color="black", linewidth=0.6, alpha=0.6, zorder=1)
        add_threshold(ax, threshold, "flat→tail ($2M)", color="#666")
        add_threshold(ax, lp_cap, "stakers sweep ($5M)", color="#999")

    axes[0].set_title("LP balance — linear scale")
    axes[0].set_ylabel("LP balance (USD)")
    axes[0].yaxis.set_major_formatter(mtick.FuncFormatter(fmt_dollars))

    axes[1].set_yscale("symlog", linthresh=1000)
    axes[1].set_title("LP balance — symlog scale (early oscillation around $0 visible)")
    axes[1].set_ylabel("LP balance (USD, symlog)")
    axes[1].yaxis.set_major_formatter(mtick.FuncFormatter(fmt_dollars))

    crossings = []
    if (state["lp_balance_usd"] > 0).any():
        crossings.append(("first > $0", state.loc[state["lp_balance_usd"] > 0, "day"].iloc[0], "green"))
    if (state["lp_balance_usd"] >= threshold).any():
        crossings.append(("first ≥ $2M", state.loc[state["lp_balance_usd"] >= threshold, "day"].iloc[0], "#666"))
    if (state["lp_balance_usd"] >= lp_cap).any():
        crossings.append(("first ≥ $5M", state.loc[state["lp_balance_usd"] >= lp_cap, "day"].iloc[0], "#999"))
    for ax in axes:
        for _, day, color in crossings:
            ax.axvline(day, color=color, linestyle=":", alpha=0.7, linewidth=1, zorder=1)

    legend_items = [Patch(facecolor=c, alpha=0.5, label=f"{lab}: {d.strftime('%Y-%m-%d')}")
                    for lab, d, c in crossings]
    adl_h = adl_legend_handle(daily)
    if adl_h:
        legend_items.append(adl_h)
    if legend_items:
        axes[0].legend(handles=legend_items, loc="best", framealpha=0.9, fontsize=8)

    style_time_axis(axes[1], state["day"])
    fig.tight_layout()
    return fig_save(fig, png_path)


def chart_paper_supply(state, daily, png_path=None):
    fig, ax = plt.subplots(figsize=(12, 4.4))
    ax.plot(state["day"], state["paper_total_supply"], color=COL_PAPER, linewidth=1.8)
    ax.fill_between(state["day"], 0, state["paper_total_supply"],
                    color=COL_PAPER, alpha=0.12)
    ax.set_title("PAPER total supply over time")
    ax.set_ylabel("PAPER")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(fmt_count))
    style_time_axis(ax, state["day"])
    return fig_save(fig, png_path)


def chart_stakers_balance(state, daily, png_path=None):
    fig, ax = plt.subplots(figsize=(12, 4.4))
    ax.plot(state["day"], state["stakers_balance_usd"], color=COL_STAKERS, linewidth=1.8)
    ax.fill_between(state["day"], 0, state["stakers_balance_usd"],
                    color=COL_STAKERS, alpha=0.12)
    ax.set_title("Cumulative fees to stakers (USDC)")
    ax.set_ylabel("USDC accumulated")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(fmt_dollars))
    style_time_axis(ax, state["day"])
    return fig_save(fig, png_path)


def chart_tail_progress(state, daily, png_path=None):
    fig, ax = plt.subplots(figsize=(12, 4.4))
    ax.plot(state["day"], state["tail_progress_usd"], color=COL_TAIL, linewidth=1.8)
    ax.fill_between(state["day"], 0, state["tail_progress_usd"],
                    color=COL_TAIL, alpha=0.12)
    ax.set_title("Tail-region HWM (PAPER mint ratchet) — strictly increasing")
    ax.set_ylabel("Cumulative tail-region LP gain (USD)")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(fmt_dollars))
    style_time_axis(ax, state["day"])
    return fig_save(fig, png_path)


def chart_paper_mint_rate(state, cfg, daily, png_path=None):
    flat_rate = cfg["paper_mint"]["flat_rate"]
    threshold = cfg["paper_mint"]["lp_flat_threshold_usd"]
    S         = cfg["paper_mint"]["tail_decay_scale_usd"]
    rate = np.where(
        state["lp_balance_usd"].values < threshold,
        flat_rate,
        flat_rate * (S / (S + state["tail_progress_usd"].values)) ** 2,
    )
    fig, ax = plt.subplots(figsize=(12, 4.4))
    ax.plot(state["day"], rate, color=COL_PAPER, linewidth=1.8)
    ax.fill_between(state["day"], 0, rate, color=COL_PAPER, alpha=0.12)
    add_threshold(ax, flat_rate, f"flat rate ({flat_rate} PAPER/$)", color="#888")
    ax.set_title("Marginal PAPER mint rate over time")
    ax.set_ylabel("PAPER per $1 of LP gain")
    style_time_axis(ax, state["day"])
    return fig_save(fig, png_path)


def chart_cumulative_trader_pnl(daily, png_path=None):
    fig, ax = plt.subplots(figsize=(12, 5.0))
    has_adl, _, _ = mark_adl_bands(ax, daily)
    ax.plot(daily["day"], daily["cum_trader_loss"], color=COL_TRADERS, linewidth=1.7,
            label="Cumulative trader losses (paid)", zorder=2)
    ax.plot(daily["day"], daily["cum_trader_win"], color=COL_WINS, linewidth=1.7,
            label="Cumulative trader wins (received)", zorder=2)
    ax.plot(daily["day"], daily["cum_trader_net"], color=COL_NET, linewidth=1.7,
            linestyle="--", label="Cumulative net trader P&L", zorder=2)
    ax.axhline(0, color="black", linewidth=0.6, alpha=0.6)
    handles, _ = ax.get_legend_handles_labels()
    adl_h = adl_legend_handle(daily)
    if adl_h:
        handles.append(adl_h)
    ax.legend(handles=handles, loc="best", framealpha=0.9, fontsize=9)
    ax.set_title("Trader P&L (cumulative) — ADL days highlighted (darker = more ADLs)")
    ax.set_ylabel("USD")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(fmt_dollars))
    style_time_axis(ax, daily["day"])
    return fig_save(fig, png_path)


def chart_cost_and_fees_per_paper(merged, staked_fraction, png_path=None):
    eps = 1e-9
    cost = merged["cum_trader_loss"] / (merged["paper_total_supply"] + eps)
    fees_per_staked = merged["stakers_balance_usd"] / (
        merged["paper_total_supply"] * staked_fraction + eps)

    fig, axes = plt.subplots(1, 2, figsize=(14, 4.6))

    ax = axes[0]
    ax.plot(merged["day"], cost, color="#7a5230", linewidth=1.8)
    ax.fill_between(merged["day"], 0, cost, color="#7a5230", alpha=0.10)
    ax.set_title("Cost to mint 1 PAPER over time\n(cum. trader losses ÷ cum. PAPER supply)")
    ax.set_ylabel("USD lost by traders per PAPER")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(
        lambda x, _: f"${x:.4f}" if x < 1 else f"${x:.2f}"))
    style_time_axis(ax, merged["day"])

    ax = axes[1]
    ax.plot(merged["day"], fees_per_staked, color=COL_STAKERS, linewidth=1.8)
    ax.fill_between(merged["day"], 0, fees_per_staked, color=COL_STAKERS, alpha=0.10)
    pct = staked_fraction * 100
    ax.set_title(
        f"Cumulative fees per STAKED PAPER over time\n"
        f"(assuming {pct:.0f}% of PAPER is staked)"
    )
    ax.set_ylabel("USDC per staked PAPER")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(
        lambda x, _: f"${x:.6f}" if x < 0.001 else (f"${x:.4f}" if x < 1 else f"${x:.2f}")))
    style_time_axis(ax, merged["day"])
    fig.tight_layout()
    return fig_save(fig, png_path)


def chart_daily_activity(daily, png_path=None):
    has_adl = "n_adl" in daily.columns and (daily["n_adl"] > 0).any()
    n_panels = 3 if has_adl else 2
    fig, axes = plt.subplots(n_panels, 1, figsize=(12, 2.8 * n_panels + 0.6),
                             sharex=True)
    if n_panels == 2:
        axes = list(axes)

    ax = axes[0]
    mark_adl_bands(ax, daily)
    ax.bar(daily["day"], daily["n_trades"], color=COL_LP, alpha=0.75, width=1.0, zorder=2)
    ax.set_title("Daily trades  (1 trade = 1 HL position episode = 1 Paper position)")
    ax.set_ylabel("trades / day")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(fmt_count))

    ax = axes[1]
    mark_adl_bands(ax, daily)
    ax.plot(daily["day"], daily["liq_pct"], color=COL_LIQ, linewidth=1.5, zorder=2)
    ax.fill_between(daily["day"], 0, daily["liq_pct"], color=COL_LIQ, alpha=0.10, zorder=1)
    ax.set_title("Daily Paper liquidation rate — ADL days highlighted (darker = more ADLs)")
    ax.set_ylabel("% trades liq'd in Paper")
    ax.set_ylim(0, max(100, daily["liq_pct"].max() * 1.05))

    if has_adl:
        ax = axes[2]
        ax.bar(daily["day"], daily["n_adl"], color=COL_ADL, alpha=0.9, width=1.0, zorder=2)
        ax.set_title("Daily HL ADL events (handled as normal closes in Paper)")
        ax.set_ylabel("ADL events / day")
        ax.yaxis.set_major_formatter(mtick.FuncFormatter(fmt_count))

    style_time_axis(axes[-1], daily["day"])
    fig.tight_layout()
    return fig_save(fig, png_path)


def chart_daily_volume(trades, daily, png_path=None):
    t = trades[["open_time_ms", "coin", "notional_at_entry_usd"]].copy()
    t["day"] = pd.to_datetime(t["open_time_ms"], unit="ms", utc=True).dt.floor("D")
    pivot = (t.groupby(["day", "coin"])["notional_at_entry_usd"]
              .sum().unstack(fill_value=0))

    fig, ax = plt.subplots(figsize=(12, 4.6))
    mark_adl_bands(ax, daily)
    bottom = np.zeros(len(pivot))
    if "BTC" in pivot.columns:
        ax.bar(pivot.index, pivot["BTC"].values, bottom=bottom,
               color=COL_BTC, alpha=0.85, width=1.0, label="BTC", zorder=2)
        bottom = bottom + pivot["BTC"].values
    if "ETH" in pivot.columns:
        ax.bar(pivot.index, pivot["ETH"].values, bottom=bottom,
               color=COL_ETH, alpha=0.85, width=1.0, label="ETH", zorder=2)
    handles, _ = ax.get_legend_handles_labels()
    adl_h = adl_legend_handle(daily)
    if adl_h:
        handles.append(adl_h)
    ax.legend(handles=handles, loc="best")
    ax.set_title("Daily volume — notional opened per day, stacked by coin\n"
                 "(HL notional, before Paper $10M cap)")
    ax.set_ylabel("USD opened")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(fmt_dollars))
    style_time_axis(ax, pivot.index)
    return fig_save(fig, png_path)


def chart_daily_oi(trades, daily, png_path=None):
    if len(trades) == 0:
        return None
    times  = np.concatenate([trades["open_time_ms"].values,
                              trades["close_time_ms"].values])
    nots   = (trades["paper_notional_usd"].values
              if "paper_notional_usd" in trades.columns
              else trades["notional_at_entry_usd"].values)
    deltas = np.concatenate([nots, -nots])
    coins  = np.concatenate([trades["coin"].values, trades["coin"].values])

    ev = pd.DataFrame({"time_ms": times, "delta": deltas, "coin": coins})
    ev = ev.sort_values("time_ms", kind="mergesort").reset_index(drop=True)
    ev["day"] = pd.to_datetime(ev["time_ms"], unit="ms", utc=True).dt.floor("D")
    is_btc = (ev["coin"].values == "BTC").astype(np.float64)
    is_eth = (ev["coin"].values == "ETH").astype(np.float64)
    d = ev["delta"].values.astype(np.float64)
    ev["oi_total"] = d.cumsum()
    ev["oi_btc"]   = (d * is_btc).cumsum()
    ev["oi_eth"]   = (d * is_eth).cumsum()
    eod = (ev.groupby("day")
             .agg(oi_total=("oi_total", "last"),
                  oi_btc=("oi_btc", "last"),
                  oi_eth=("oi_eth", "last"))
             .reset_index())

    fig, ax = plt.subplots(figsize=(12, 4.6))
    ax.fill_between(eod["day"], 0, eod["oi_btc"],
                    color=COL_BTC, alpha=0.55, label="BTC OI")
    ax.fill_between(eod["day"], eod["oi_btc"], eod["oi_btc"] + eod["oi_eth"],
                    color=COL_ETH, alpha=0.55, label="ETH OI")
    ax.plot(eod["day"], eod["oi_total"], color="black", linewidth=1.4,
            label="Total OI")
    ax.set_title("Open Interest — end-of-day notional in active Paper positions\n"
                 "(Paper-capped notional, stacked by coin)")
    ax.set_ylabel("USD")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(fmt_dollars))
    ax.legend(loc="best")
    style_time_axis(ax, eod["day"])
    return fig_save(fig, png_path)


def chart_lp_contribution_by_coin(trades, daily, png_path=None):
    t = trades.copy()
    t["close_dt"] = pd.to_datetime(t["close_time_ms"], unit="ms", utc=True)
    t["day"] = t["close_dt"].dt.floor("D")
    agg = (t.groupby(["day", "coin"])["lp_balance_delta_usd"].sum().reset_index()
            .pivot(index="day", columns="coin", values="lp_balance_delta_usd")
            .fillna(0).cumsum())
    fig, ax = plt.subplots(figsize=(12, 4.6))
    if "BTC" in agg.columns:
        ax.plot(agg.index, agg["BTC"], color=COL_BTC, linewidth=1.8, label="BTC")
        ax.fill_between(agg.index, 0, agg["BTC"], color=COL_BTC, alpha=0.10)
    if "ETH" in agg.columns:
        ax.plot(agg.index, agg["ETH"], color=COL_ETH, linewidth=1.8, label="ETH")
        ax.fill_between(agg.index, 0, agg["ETH"], color=COL_ETH, alpha=0.10)
    ax.axhline(0, color="black", linewidth=0.6, alpha=0.6)
    ax.set_title("Cumulative net LP contribution by coin")
    ax.set_ylabel("USD")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(fmt_dollars))
    ax.legend()
    style_time_axis(ax, agg.index)
    return fig_save(fig, png_path)


def chart_pnl_distribution(trades, png_path=None):
    x = trades["lp_balance_delta_usd"].values
    x = x[np.isfinite(x)]
    if x.size == 0:
        return None
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.4))
    pos, neg = x[x > 0], -x[x < 0]
    ax = axes[0]
    if pos.size:
        ax.hist(np.log10(pos), bins=80, color=COL_LP, alpha=0.75)
    ax.set_title(f"Per-trade LP GAINS (log10 USD) — n={pos.size:,}")
    ax.set_xlabel("log10(USD)")
    ax.set_ylabel("# trades")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(fmt_count))
    ax = axes[1]
    if neg.size:
        ax.hist(np.log10(neg), bins=80, color="#d62728", alpha=0.75)
    ax.set_title(f"Per-trade LP LOSSES (log10 USD) — n={neg.size:,}")
    ax.set_xlabel("log10(USD)")
    ax.set_ylabel("# trades")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(fmt_count))
    fig.tight_layout()
    return fig_save(fig, png_path)


def chart_notional_distribution(trades, png_path=None):
    x = trades["notional_at_entry_usd"].values
    paper = trades["paper_notional_usd"].values
    fig, ax = plt.subplots(figsize=(12, 4.4))
    ax.hist(np.log10(x[x > 0]), bins=80, alpha=0.55, color=COL_LP,
            label="HL notional at entry")
    ax.hist(np.log10(paper[paper > 0]), bins=80, alpha=0.55, color=COL_PAPER,
            label="Paper notional (after $10M cap)")
    ax.axvline(np.log10(10_000_000), color="black", linestyle="--",
               linewidth=1, alpha=0.6)
    ax.text(np.log10(10_000_000), ax.get_ylim()[1] * 0.95,
            "  $10M cap", va="top", ha="left", fontsize=9)
    ax.set_title("Position notional distribution (log10 USD)")
    ax.set_xlabel("log10(USD)")
    ax.set_ylabel("# trades")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(fmt_count))
    ax.legend()
    return fig_save(fig, png_path)


def chart_lp_phase_diagram(state, cfg, png_path=None):
    threshold = cfg["paper_mint"]["lp_flat_threshold_usd"]
    lp_cap    = cfg["stakers"]["lp_excess_cap_usd"]
    fig, ax = plt.subplots(figsize=(9.5, 5.4))
    sc = ax.scatter(state["lp_balance_usd"], state["paper_total_supply"],
                    c=np.arange(len(state)), cmap="viridis", s=18, alpha=0.85)
    ax.axvline(0, color="black", linewidth=0.6, alpha=0.6)
    ax.axvline(threshold, color="#666", linestyle="--", linewidth=1, alpha=0.6)
    ax.axvline(lp_cap, color="#666", linestyle="--", linewidth=1, alpha=0.6)
    ax.set_title("Protocol trajectory: LP balance vs PAPER supply\n(color = time)")
    ax.set_xlabel("LP balance (USD)")
    ax.set_ylabel("PAPER total supply")
    ax.xaxis.set_major_formatter(mtick.FuncFormatter(fmt_dollars))
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(fmt_count))
    cbar = fig.colorbar(sc, ax=ax)
    cbar.set_label("day index")
    return fig_save(fig, png_path)


def chart_mint_curve(cfg, png_path=None):
    flat_rate = cfg["paper_mint"]["flat_rate"]
    threshold = cfg["paper_mint"]["lp_flat_threshold_usd"]
    S         = cfg["paper_mint"]["tail_decay_scale_usd"]
    H = np.linspace(0, 5 * S, 500)
    rate = flat_rate * (S / (S + H)) ** 2
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.plot(H + threshold, rate, color=COL_PAPER, linewidth=2)
    ax.fill_between(H + threshold, 0, rate, color=COL_PAPER, alpha=0.12)
    ax.axhline(flat_rate, color="black", linestyle="--", linewidth=1, alpha=0.6)
    ax.text(threshold + S * 0.02, flat_rate * 1.02,
            f"flat = {flat_rate} PAPER/$", ha="left", va="bottom", fontsize=9)
    ax.set_title(f"Theoretical PAPER mint curve\n"
                 f"(flat ≤ $2M; tail decay with S = ${S/1e6:.0f}M)")
    ax.set_xlabel("LP balance (= threshold + tail HWM) — USD")
    ax.set_ylabel("PAPER per $1 LP gain")
    ax.xaxis.set_major_formatter(mtick.FuncFormatter(fmt_dollars))
    return fig_save(fig, png_path)


# -----------------------------------------------------------------------------

def build_daily_aggregates(trades, source_trades=None):
    t = trades.copy()
    t["close_dt"]    = pd.to_datetime(t["close_time_ms"], unit="ms", utc=True)
    t["close_day"]   = t["close_dt"].dt.floor("D")
    t["open_day"]    = pd.to_datetime(t["open_time_ms"], unit="ms", utc=True).dt.floor("D")
    t["is_loser"]    = t["user_pnl_usd"] < 0
    t["is_winner"]   = t["user_pnl_usd"] > 0
    t["trader_loss"] = np.where(t["is_loser"], -t["user_pnl_usd"], 0.0)
    t["trader_win"]  = np.where(t["is_winner"], t["user_pnl_usd"], 0.0)

    daily = (t.groupby("close_day").agg(
        n_trades    = ("trade_id", "count"),
        n_paper_liq = ("paper_was_liquidated", "sum"),
        trader_loss = ("trader_loss", "sum"),
        trader_win  = ("trader_win", "sum"),
        lp_delta    = ("lp_balance_delta_usd", "sum"),
    ).reset_index().rename(columns={"close_day": "day"}))

    vol = (t.groupby("open_day").agg(
        volume_usd_hl    = ("notional_at_entry_usd", "sum"),
        volume_usd_paper = ("paper_notional_usd", "sum"),
        n_trades_opened  = ("trade_id", "count"),
    ).reset_index().rename(columns={"open_day": "day"}))

    daily = (daily.merge(vol, on="day", how="outer")
                  .fillna(0).sort_values("day").reset_index(drop=True))
    daily["liq_pct"] = np.where(daily["n_trades"] > 0,
                                100.0 * daily["n_paper_liq"] / daily["n_trades"], 0.0)
    daily["cum_trader_loss"] = daily["trader_loss"].cumsum()
    daily["cum_trader_win"]  = daily["trader_win"].cumsum()
    daily["cum_trader_net"]  = daily["cum_trader_win"] - daily["cum_trader_loss"]
    daily["cum_lp_delta"]    = daily["lp_delta"].cumsum()

    adl_src = None
    if source_trades is not None and "hl_was_adl" in source_trades.columns:
        adl_src = source_trades
    elif "hl_was_adl" in trades.columns:
        adl_src = trades

    daily["n_adl"] = 0
    if adl_src is not None:
        a = adl_src.loc[adl_src["hl_was_adl"] == True, ["close_time_ms"]].copy()
        if not a.empty:
            a["day"] = pd.to_datetime(a["close_time_ms"], unit="ms", utc=True).dt.floor("D")
            adl_daily = a.groupby("day").size().reset_index(name="n_adl_src")
            daily = daily.merge(adl_daily, on="day", how="left")
            daily["n_adl"] = daily["n_adl_src"].fillna(0).astype(int)
            daily = daily.drop(columns=["n_adl_src"])
    return daily


# -----------------------------------------------------------------------------

def render_report(stats, cfg, charts, out_path, staked_fraction):
    def fmt_money(x):
        try:    return f"${x:,.0f}"
        except: return str(x)

    kpis_html = f"""
    <div class="kpis">
      <div class="kpi"><span class="kpi-label">Trades replayed</span>
        <span class="kpi-value">{stats['n_trades_replayed']:,}</span></div>
      <div class="kpi"><span class="kpi-label">Final LP balance</span>
        <span class="kpi-value">{fmt_money(stats['final_lp_balance_usd'])}</span></div>
      <div class="kpi"><span class="kpi-label">Final PAPER supply</span>
        <span class="kpi-value">{stats['final_paper_supply']:,.0f}</span></div>
      <div class="kpi"><span class="kpi-label">Stakers earned</span>
        <span class="kpi-value">{fmt_money(stats['final_stakers_balance_usd'])}</span></div>
      <div class="kpi"><span class="kpi-label">Paper liquidations</span>
        <span class="kpi-value">{stats['n_paper_liquidated']:,}
          <small>({stats['pct_paper_liquidated']:.1f}%)</small></span></div>
      <div class="kpi"><span class="kpi-label">HL liquidations</span>
        <span class="kpi-value">{stats['n_hl_liquidated']:,}
          <small>({stats['pct_hl_liquidated']:.2f}%)</small></span></div>
      <div class="kpi"><span class="kpi-label">LP gained (losers + liqs)</span>
        <span class="kpi-value">{fmt_money(stats['total_lp_gained_from_losers_and_liqs_usd'])}</span></div>
      <div class="kpi"><span class="kpi-label">LP paid out (to winners)</span>
        <span class="kpi-value">{fmt_money(stats['total_lp_lost_to_winners_usd'])}</span></div>
      <div class="kpi"><span class="kpi-label">Assumed staked</span>
        <span class="kpi-value">{staked_fraction*100:.0f}% <small>of PAPER supply</small></span></div>
    </div>"""

    sections = "".join(
        f'<section><h2>{escape(t)}</h2><p class="desc">{d}</p>'
        f'<div class="chart"><img src="data:image/png;base64,{b}" alt="{escape(t)}"/></div></section>'
        for t, d, b in charts
    )

    note = ""
    impact_vals = []
    for coin_p in cfg.get("impact", {}).values():
        if isinstance(coin_p, dict):
            impact_vals.extend(coin_p.values())
    if any("PLACEHOLDER" in str(v) for v in impact_vals):
        note = ('<p class="warn">⚠ Impact formula values are PLACEHOLDERS.</p>')

    cfg_yaml = yaml.safe_dump(cfg, sort_keys=False)
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>Paper LP simulation report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 1280px; margin: 0 auto; padding: 24px;
         color: #1a1a1a; background: #fafafa; line-height: 1.5; }}
  h1 {{ font-size: 28px; margin: 0 0 8px; }}
  h2 {{ font-size: 18px; margin: 32px 0 6px; color: #222;
        border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
  .subtitle {{ color: #666; margin-bottom: 24px; font-size: 14px; }}
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
           gap: 12px; margin: 20px 0 28px; }}
  .kpi {{ background: white; border: 1px solid #e6e6e6; border-radius: 6px;
          padding: 12px 14px; }}
  .kpi-label {{ display: block; font-size: 11px; color: #777;
                text-transform: uppercase; letter-spacing: .03em; }}
  .kpi-value {{ display: block; font-size: 19px; font-weight: 600; margin-top: 4px; }}
  .kpi-value small {{ color: #888; font-weight: 400; font-size: 13px; }}
  section {{ background: white; border: 1px solid #e6e6e6; border-radius: 6px;
             padding: 14px 18px 18px; margin-bottom: 14px; }}
  .desc {{ color: #555; font-size: 13px; margin: 4px 0 12px; }}
  .chart img {{ max-width: 100%; height: auto; display: block; margin: 0 auto; }}
  .warn {{ background: #fff5e6; border: 1px solid #ffd699; border-radius: 4px;
           padding: 10px 14px; margin: 16px 0; font-size: 13px; color: #663300; }}
  pre {{ background: #f6f6f6; border: 1px solid #ddd; border-radius: 4px;
         padding: 12px; overflow: auto; font-size: 12px; }}
  details summary {{ cursor: pointer; font-weight: 600; color: #444; padding: 6px 0; }}
</style></head><body>
<h1>Paper LP simulation report</h1>
<p class="subtitle">Max-leverage HL trades replayed through Paper protocol mechanics at 1000x.
Individual PNGs are also saved in the <code>charts/</code> subdirectory for full-resolution viewing.</p>
{note}
<h2>Summary</h2>{kpis_html}
{sections}
<h2>Config used</h2>
<details><summary>Show paper_config.yaml</summary><pre>{escape(cfg_yaml)}</pre></details>
</body></html>"""
    out_path.write_text(html, encoding="utf-8")


# -----------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sim-dir", type=Path, required=True,
                   help="Directory with paper_sim_*.parquet + paper_sim_stats.json")
    p.add_argument("--config", type=Path, required=True,
                   help="paper_config.yaml used for the run")
    p.add_argument("--source-trades", type=Path, default=None,
                   help="Optional: max_lev_trades.parquet for ADL events")
    p.add_argument("--output", type=Path, default=None,
                   help="Output HTML (default: <sim-dir>/paper_sim_report.html)")
    p.add_argument("--charts-dir", type=Path, default=None,
                   help="Directory for individual PNGs (default: <sim-dir>/charts/)")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")

    trades_path = args.sim_dir / "paper_sim_trades.parquet"
    state_path  = args.sim_dir / "paper_sim_state.parquet"
    stats_path  = args.sim_dir / "paper_sim_stats.json"
    for x in (trades_path, state_path, stats_path):
        if not x.exists():
            sys.exit(f"ERROR: {x} not found")
    out_path = args.output or (args.sim_dir / "paper_sim_report.html")
    charts_dir = args.charts_dir or (args.sim_dir / "charts")
    charts_dir.mkdir(parents=True, exist_ok=True)

    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    staked_fraction = float(cfg.get("staking", {}).get("assumed_staked_fraction", 1.0))
    logging.info("Assumed staked fraction: %.2f", staked_fraction)

    with open(stats_path) as f:
        stats = json.load(f)

    state = pd.read_parquet(state_path).sort_values("day_ms").reset_index(drop=True)
    if "day" not in state.columns:
        state["day"] = pd.to_datetime(state["day_ms"], unit="ms", utc=True)
    state["day"] = pd.to_datetime(state["day"], utc=True)
    logging.info("State: %s daily rows", f"{len(state):,}")

    trades = pd.read_parquet(trades_path)
    logging.info("Sim trades: %s", f"{len(trades):,}")

    source_trades = None
    if args.source_trades and args.source_trades.exists():
        source_trades = pd.read_parquet(args.source_trades,
                                        columns=["close_time_ms", "hl_was_adl"])
        logging.info("Source trades for ADL: %s loaded", f"{len(source_trades):,}")
    elif "hl_was_adl" in trades.columns:
        logging.info("ADL info present in paper_sim_trades.parquet")
    else:
        logging.warning("No ADL info available. Pass --source-trades to enable.")

    logging.info("Building daily aggregates...")
    daily = build_daily_aggregates(trades, source_trades=source_trades)
    n_adl_days = int((daily["n_adl"] > 0).sum())
    if n_adl_days > 0:
        max_n_adl = int(daily["n_adl"].max())
        logging.info("Days with ADL events: %d  (max in a day: %d)",
                     n_adl_days, max_n_adl)
    else:
        logging.info("No ADL events detected.")

    merged = state.merge(
        daily[["day", "cum_trader_loss", "cum_trader_win", "cum_trader_net",
               "liq_pct", "n_trades", "n_adl"]],
        on="day", how="left").ffill().fillna(0)

    # Each entry: (filename_stub, title, desc, callable returning b64)
    chart_specs = [
        ("01_lp_balance",
         "1 — LP balance over time (linear + symlog)",
         "Two panels of the same series. Top: linear scale (final magnitude, $5M cap plateau). Bottom: symlog scale (early oscillation around $0). Dotted verticals mark first crossings of $0, $2M, $5M. Lavender bands = HL ADL days (darker = more ADLs).",
         lambda png: chart_lp_balance(state, cfg, daily, png_path=png)),

        ("02_paper_supply",
         "2 — PAPER total supply over time",
         "Cumulative PAPER minted to losing/liquidated traders.",
         lambda png: chart_paper_supply(state, daily, png_path=png)),

        ("03_stakers_balance",
         "3 — Cumulative fees to stakers (USDC)",
         "USDC accumulated by stakers from the continuous cut and the $5M cap excess sweep.",
         lambda png: chart_stakers_balance(state, daily, png_path=png)),

        ("04_tail_progress",
         "4 — Tail-region HWM (PAPER mint ratchet)",
         "Strictly non-decreasing high-water-mark of cumulative gains in the tail region.",
         lambda png: chart_tail_progress(state, daily, png_path=png)),

        ("05_mint_rate",
         "5 — Marginal PAPER mint rate over time",
         "PAPER per $1 of LP gain at each moment.",
         lambda png: chart_paper_mint_rate(state, cfg, daily, png_path=png)),

        ("06_trader_pnl",
         "6 — Trader P&L (cumulative)",
         "Aggregate trader-side flows. Lavender bands mark HL ADL days (darker = more ADLs). In Paper, ADL closes are handled as normal closes at the HL ADL fill price.",
         lambda png: chart_cumulative_trader_pnl(daily, png_path=png)),

        ("07_cost_and_fees_per_paper",
         "7 — Cost & fees per PAPER",
         f"Left: cumulative trader losses per PAPER minted. Right: cumulative stakers USDC per STAKED PAPER (assuming {staked_fraction*100:.0f}% of supply is staked, configurable under 'staking.assumed_staked_fraction').",
         lambda png: chart_cost_and_fees_per_paper(merged, staked_fraction, png_path=png)),

        ("08_daily_activity",
         "8 — Daily activity",
         "Top: trades closed per day. Middle: Paper liquidation rate. Bottom: HL ADL events.",
         lambda png: chart_daily_activity(daily, png_path=png)),

        ("09_daily_volume",
         "9 — Daily volume (stacked by coin)",
         "Sum of position notional opened each day, BTC vs ETH. HL notional, before Paper's $10M cap.",
         lambda png: chart_daily_volume(trades, daily, png_path=png)),

        ("10_oi",
         "10 — Open Interest over time",
         "End-of-day OI in active Paper positions (Paper-capped notional, stacked by coin).",
         lambda png: chart_daily_oi(trades, daily, png_path=png)),

        ("11_lp_contribution_by_coin",
         "11 — LP contribution by coin",
         "Net cumulative LP delta from BTC vs ETH trades.",
         lambda png: chart_lp_contribution_by_coin(trades, daily, png_path=png)),

        ("12_pnl_distribution",
         "12 — Per-trade LP delta distribution",
         "Histograms of per-trade LP gains and losses, log10 USD.",
         lambda png: chart_pnl_distribution(trades, png_path=png)),

        ("13_notional_distribution",
         "13 — Position notional distribution",
         "HL notional at entry vs Paper notional (after $10M cap), log10 USD.",
         lambda png: chart_notional_distribution(trades, png_path=png)),

        ("14_phase_diagram",
         "14 — Phase diagram: LP × PAPER supply",
         "Each point = one day. Color = time.",
         lambda png: chart_lp_phase_diagram(state, cfg, png_path=png)),

        ("15_mint_curve",
         "15 — Theoretical PAPER mint curve (reference)",
         "Protocol's structural emission schedule.",
         lambda png: chart_mint_curve(cfg, png_path=png)),
    ]

    charts = []
    logging.info("Generating %d charts → %s", len(chart_specs), charts_dir)
    for stub, title, desc, fn in chart_specs:
        png_path = charts_dir / f"{stub}.png"
        try:
            b64 = fn(png_path)
            if b64 is None:
                logging.warning("Chart %s returned None, skipping", stub)
                continue
            charts.append((title, desc, b64))
            logging.info("  %s.png  (%d KB)", stub, png_path.stat().st_size // 1024)
        except Exception as e:
            logging.error("Chart %s failed: %s", stub, e)

    render_report(stats, cfg, charts, out_path, staked_fraction)
    size_mb = out_path.stat().st_size / (1024 * 1024)
    logging.info("Wrote %s (%.1f MB)", out_path, size_mb)
    print(f"\n✓ HTML report: {out_path}")
    print(f"✓ Individual PNGs: {charts_dir}/")
    print(f"  {len(charts)} charts, HTML {size_mb:.1f} MB")


if __name__ == "__main__":
    sys.exit(main())