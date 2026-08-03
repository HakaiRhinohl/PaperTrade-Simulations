#!/usr/bin/env python3
"""
simulate_paper_lp.py — Replay max-lev HL trades through Paper protocol mechanics.

For each HL position episode, opens a 1000x Paper position with the same entry,
checks if it would have been liquidated under Paper's tighter bust price (≤5bps
adverse move), computes PnL with asymmetric impact, and evolves the LP / PAPER
/ stakers state through time.

Reads:
  - max_lev_trades.parquet (output of build_trades.py)
  - paper_config.yaml (Paper protocol parameters; placeholders editable)

Writes (to --output-dir):
  - paper_sim_trades.parquet  (per-trade outcomes under Paper)
  - paper_sim_state.parquet   (daily timeseries of LP / PAPER / stakers)
  - paper_sim_stats.json      (summary stats)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--trades", type=Path,
                        default=Path(__file__).resolve().parent / "data" / "max_lev_trades_v3.parquet",
                        help="Path to max_lev_trades parquet (default: data/max_lev_trades_v3.parquet)")
    parser.add_argument("--config", type=Path, required=True,
                        help="Path to paper_config.yaml")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Directory for output files")
    parser.add_argument("--sample-fraction", type=float, default=None,
                        help="Override simulation.sample_fraction from config "
                             "(1.0 = all trades; 0.1 = random 10%% sample)")
    parser.add_argument("--sample-seed", type=int, default=None,
                        help="Override simulation.sample_seed from config")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = load_config(args.config)
    leverage = cfg["paper_leverage"]
    buffer_bps = cfg["bust_buffer_bps"]
    max_open_usd = cfg["max_position_open_usd"]

    flat_rate = cfg["paper_mint"]["flat_rate"]
    threshold = cfg["paper_mint"]["lp_flat_threshold_usd"]
    S = cfg["paper_mint"]["tail_decay_scale_usd"]

    stakers_pct = cfg["stakers"]["continuous_pct_of_lp_gain"]
    frontend_pct = cfg["stakers"].get("frontend_pct", 0.0)
    lp_cap = cfg["stakers"]["lp_excess_cap_usd"]

    # Adverse-tolerance for Paper at this leverage/buffer
    # 1/leverage = max margin-erasing move; buffer is cushion subtracted from that
    buffer_frac = buffer_bps / 10000.0
    tolerance = 1.0 / leverage - buffer_frac          # 0.0005 for 1000x/5bps

    logging.info("Paper bust tolerance: %.5f (%.2f bps)", tolerance, tolerance * 10000)
    logging.info("Loading trades from %s", args.trades)
    df = pd.read_parquet(args.trades)
    n_input = len(df)
    logging.info("Loaded %s trades", f"{n_input:,}")

    # -------- subsampling --------
    sim_cfg = cfg.get("simulation", {})
    sample_fraction = float(args.sample_fraction
                             if args.sample_fraction is not None
                             else sim_cfg.get("sample_fraction", 1.0))
    sample_seed = int(args.sample_seed
                       if args.sample_seed is not None
                       else sim_cfg.get("sample_seed", 42))
    if sample_fraction <= 0 or sample_fraction > 1:
        sys.exit(f"sample_fraction must be in (0, 1], got {sample_fraction}")
    if sample_fraction < 1.0:
        rng = np.random.default_rng(sample_seed)
        keep = rng.random(n_input) < sample_fraction
        df = df[keep].reset_index(drop=True)
        logging.info(
            "Subsampled: kept %s of %s trades (%.4f, seed=%d) — preserves size distribution",
            f"{len(df):,}", f"{n_input:,}", sample_fraction, sample_seed,
        )
    else:
        logging.info("No subsampling (sample_fraction = 1.0)")

    df = df.sort_values("close_time_ms", kind="mergesort").reset_index(drop=True)
    n = len(df)

    # -------- numpy arrays for the tight loop --------
    coin            = df["coin"].values
    direction       = df["direction"].values
    is_long         = (direction == "long")
    sign            = np.where(is_long, 1.0, -1.0)

    open_px         = df["open_px"].values.astype(np.float64)
    close_px        = df["close_px"].values.astype(np.float64)
    worst_adv_px    = df["worst_adverse_px"].values.astype(np.float64)
    size_units      = df["size_units"].values.astype(np.float64)
    notional_entry  = df["notional_at_entry_usd"].values.astype(np.float64)
    close_time_ms   = df["close_time_ms"].values

    # Cap notional at $10M (the trade still uses the HL prices for outcome)
    paper_notional  = np.minimum(notional_entry, max_open_usd)
    paper_size      = paper_notional / open_px            # units after cap
    paper_margin    = paper_notional / leverage

    # Liquidation in Paper: the worst adverse move (magnitude) reaches the bust
    # tolerance. Use the precomputed worst_adverse_pct column with abs(), which is
    # exactly what local_server (the batch engine) does — so both engines report an
    # identical liq rate (BTC 80.05% / ETH 91.49%). Deriving it from prices instead
    # disagreed by ~0.02pp on edge trades.
    adverse_pct = np.abs(df["worst_adverse_pct"].values.astype(np.float64))
    paper_liq = (adverse_pct >= tolerance) & ~np.isnan(adverse_pct)

    # Trades the sim CAN process: need finite open_px, close_px, notional, size.
    # A NaN here (e.g., position never closed within data window) makes the
    # PnL math undefined and would propagate NaN into lp_balance forever.
    valid_trade = (
        ~np.isnan(open_px) & ~np.isnan(close_px)
        & ~np.isnan(notional_entry) & (open_px > 0)
    )
    n_invalid = int((~valid_trade).sum())
    if n_invalid > 0:
        logging.warning(
            "Skipping %s trades (%.2f%%) with NaN open_px/close_px/notional "
            "— positions that never closed in the HL data window",
            f"{n_invalid:,}", 100.0 * n_invalid / n,
        )

    # Raw PnL at close (for trades that survived to close)
    # long  → (close-open)*size ; short → (open-close)*size
    raw_pnl  = sign * (close_px - open_px) * paper_size
    move_pct = np.abs(close_px - open_px) / open_px

    # Impact params per coin, cached
    btc_p = cfg["impact"]["BTC"]
    eth_p = cfg["impact"]["ETH"]
    btc_base, btc_rm, btc_pm, btc_rn = (
        btc_p["base_rate"], btc_p["rate_multiplier"],
        btc_p["position_multiplier"], btc_p["reference_notional_usd"],
    )
    eth_base, eth_rm, eth_pm, eth_rn = (
        eth_p["base_rate"], eth_p["rate_multiplier"],
        eth_p["position_multiplier"], eth_p["reference_notional_usd"],
    )
    deadband = cfg.get("deadband_bps", 0.0) / 10_000.0   # half-spread, move fraction
    is_btc = (coin == "BTC")

    # -------- output arrays --------
    out_was_liq        = np.zeros(n, dtype=bool)
    out_lp_delta       = np.zeros(n)   # signed change to LP balance
    out_paper_minted   = np.zeros(n)
    out_stakers_taken  = np.zeros(n)
    out_frontend_taken = np.zeros(n)
    out_user_outcome   = np.zeros(n)
    out_lp_balance     = np.zeros(n)   # post-trade LP balance

    # -------- state --------
    from collections import deque
    lp_balance     = float(cfg["initial_lp_usd"])
    tail_progress  = 0.0
    paper_total    = 0.0
    stakers_total  = 0.0
    frontend_total = 0.0

    # FIFO queue / debt — identical mechanics to local_server.simulate()
    queue            = deque()   # entries: (owed_usd, entry_day)
    debt_total       = 0.0
    max_debt         = 0.0
    max_queue_len    = 0
    total_queued     = 0
    total_queue_paid = 0
    total_queue_wait = 0

    snapshot_rows  = []
    last_day_ms    = None

    logging.info("Starting simulation (%s trades)...", f"{n:,}")
    t0 = time.time()
    log_every = max(1, n // 25)

    # Pre-compute S² (used in tail-region mint integral)
    S_sq = S * S

    for i in range(n):
        # ---------- daily snapshot (BEFORE processing this trade, so it
        # reflects the state at END of the previous day) ----------
        day_ms = (close_time_ms[i] // 86_400_000) * 86_400_000
        if last_day_ms is not None and last_day_ms != day_ms:
            snapshot_rows.append({
                "day_ms":              last_day_ms,
                "lp_balance_usd":      lp_balance,
                "tail_progress_usd":   tail_progress,
                "paper_total_supply":  paper_total,
                "stakers_balance_usd": stakers_total,
                "frontend_balance_usd": frontend_total,
                "debt_total_usd":      debt_total,
                "queue_size":          len(queue),
            })
        last_day_ms = day_ms

        # ---------- skip trades the sim can't process ----------
        if not valid_trade[i]:
            out_lp_balance[i] = lp_balance
            # leave out_was_liq, out_lp_delta, etc. at their zero defaults
            continue

        # ---------- determine LP change from this trade ----------
        impact_revenue = 0.0                     # win haircut retained by the LP
        if paper_liq[i]:
            lp_event_gain = paper_margin[i]
            user_outcome  = -paper_margin[i]
        else:
            rpnl = raw_pnl[i]
            if rpnl >= 0.0:
                # winning close → apply asymmetric impact
                if is_btc[i]:
                    br, rm, pm, rn = btc_base, btc_rm, btc_pm, btc_rn
                else:
                    br, rm, pm, rn = eth_base, eth_rm, eth_pm, eth_rn

                m = move_pct[i]
                # deadband: remove half the CLOB spread from the winning move,
                # then apply the impact scale on the net move
                net_m = m - deadband
                if net_m <= 0.0 or not np.isfinite(m):
                    adjusted = 0.0
                else:
                    term1 = 1.0 / (net_m * rm)
                    term2 = rn / (net_m * pm)
                    scale = (1.0 - br) / (1.0 + term1 + term2)
                    if scale < 0.0:   scale = 0.0
                    elif scale > 1.0: scale = 1.0
                    adjusted = rpnl * (net_m / m) * scale
                impact_revenue = rpnl - adjusted
                lp_event_gain  = -adjusted       # LP pays the user
                user_outcome   = adjusted
            else:
                # losing close → full loss to LP
                lp_event_gain = -rpnl            # negate negative
                user_outcome  = rpnl

        # ---------- apply to LP / PAPER / stakers (identical to local_server) ----------
        paper_event     = 0.0
        stakers_event   = 0.0
        frontend_event  = 0.0
        queue_was_empty = (len(queue) == 0)
        day_idx         = int(close_time_ms[i] // 86_400_000)

        if lp_event_gain > 0.0:
            # --- LP GAINS (trader liquidated or lost) ---
            # staker + frontend each take their pct up front; the rest grows the LP
            stakers_cut     = lp_event_gain * stakers_pct
            frontend_event  = lp_event_gain * frontend_pct
            frontend_total += frontend_event
            lp_gain         = lp_event_gain - stakers_cut - frontend_event

            # mint basis = GROSS gain, BEFORE queue drain / cap: liquidations mint
            # on the full margin, losses on the loss after fees. Minting happens
            # regardless of cap (protocol docs).
            mint_basis = lp_event_gain if paper_liq[i] else lp_gain

            # 1) drain the FIFO queue before growing the LP
            while queue and lp_gain > 0.0:
                owed, entry_day = queue[0]
                if lp_gain >= owed:
                    lp_gain          -= owed
                    debt_total       -= owed
                    total_queue_wait += (day_idx - entry_day)
                    total_queue_paid += 1
                    queue.popleft()
                else:
                    queue[0]    = (owed - lp_gain, entry_day)
                    debt_total -= lp_gain
                    lp_gain     = 0.0

            # 2) remaining lp_gain grows the LP (cap handling)
            excess = 0.0
            if lp_balance >= lp_cap:
                excess  = lp_gain
                lp_gain = 0.0
            elif lp_balance + lp_gain > lp_cap:
                excess   = (lp_balance + lp_gain) - lp_cap
                lp_gain -= excess

            stakers_event = stakers_cut + excess
            lp_pre        = lp_balance
            lp_balance   += lp_gain

            # 3) mint PAPER on mint_basis (gross); non-liquidation losses skip
            #    minting when the queue was non-empty
            should_mint = paper_liq[i] or queue_was_empty
            if should_mint and mint_basis > 0.0:
                if lp_pre < threshold:
                    if lp_pre + mint_basis <= threshold:
                        flat_part = mint_basis
                        tail_part = 0.0
                    else:
                        flat_part = threshold - lp_pre
                        tail_part = mint_basis - flat_part
                else:
                    flat_part = 0.0
                    tail_part = mint_basis

                paper_event += flat_part * flat_rate
                if tail_part > 0.0:
                    new_tail = tail_progress + tail_part
                    paper_event += (
                        flat_rate * S_sq
                        * (1.0 / (S + tail_progress) - 1.0 / (S + new_tail))
                    )
                    tail_progress = new_tail   # strict HWM

            paper_total    += paper_event
            stakers_total  += stakers_event
            out_lp_delta[i] = lp_gain
        else:
            # --- LP PAYS (trader won, no liquidation) ---
            payout = -lp_event_gain

            # impact-revenue fee, suppressed when queue non-empty; split staker/frontend
            if impact_revenue > 0.0 and queue_was_empty:
                staker_impact   = impact_revenue * stakers_pct
                frontend_impact = impact_revenue * frontend_pct
            else:
                staker_impact = frontend_impact = 0.0

            if lp_balance >= payout:
                lp_balance -= payout
                total_impact = staker_impact + frontend_impact
                if total_impact > 0.0:
                    actual_impact   = min(total_impact, lp_balance)
                    lp_balance     -= actual_impact
                    stakers_event   = actual_impact * (staker_impact / total_impact)
                    frontend_event  = actual_impact * (frontend_impact / total_impact)
                    stakers_total  += stakers_event
                    frontend_total += frontend_event
            else:
                # LP can't fully pay — queue the shortfall (FIFO)
                shortfall     = payout - lp_balance
                lp_balance    = 0.0
                queue.append((shortfall, day_idx))
                debt_total   += shortfall
                total_queued += 1

            out_lp_delta[i] = lp_event_gain   # = -payout, matches local_server

        # queue / debt peaks
        if debt_total > max_debt:
            max_debt = debt_total
        if len(queue) > max_queue_len:
            max_queue_len = len(queue)

        # record per-trade outputs
        out_was_liq[i]        = paper_liq[i]
        out_paper_minted[i]   = paper_event
        out_stakers_taken[i]  = stakers_event
        out_frontend_taken[i] = frontend_event
        out_user_outcome[i]   = user_outcome
        out_lp_balance[i]     = lp_balance

        if i and i % log_every == 0:
            pct = 100.0 * i / n
            el  = time.time() - t0
            eta = el / i * (n - i)
            logging.info(
                "  %4.0f%%  LP=$%s  PAPER=%s  stakers=$%s  ETA %.0fs",
                pct,
                f"{lp_balance:>14,.0f}",
                f"{paper_total:>16,.0f}",
                f"{stakers_total:>12,.0f}",
                eta,
            )

    if last_day_ms is not None:
        snapshot_rows.append({
            "day_ms":              last_day_ms,
            "lp_balance_usd":      lp_balance,
            "tail_progress_usd":   tail_progress,
            "paper_total_supply":  paper_total,
            "stakers_balance_usd": stakers_total,
        })

    elapsed = time.time() - t0
    logging.info("Simulation done in %.1fs", elapsed)

    # -------- write outputs --------
    args.output_dir.mkdir(parents=True, exist_ok=True)

    trades_out = df[[
        "trade_id", "coin", "direction",
        "open_time_ms", "close_time_ms",
        "open_px", "close_px", "worst_adverse_px",
        "size_units", "notional_at_entry_usd",
        "hl_was_liquidated", "hl_was_adl", "hl_realized_pnl_usd",
    ]].copy()
    trades_out["paper_notional_usd"]   = paper_notional
    trades_out["paper_margin_usd"]     = paper_margin
    trades_out["paper_was_liquidated"] = out_was_liq
    trades_out["lp_balance_delta_usd"] = out_lp_delta
    trades_out["lp_balance_post_usd"]  = out_lp_balance
    trades_out["paper_minted_to_user"] = out_paper_minted
    trades_out["stakers_taken_usd"]    = out_stakers_taken
    trades_out["frontend_taken_usd"]   = out_frontend_taken
    trades_out["user_pnl_usd"]         = out_user_outcome

    trades_path = args.output_dir / "paper_sim_trades.parquet"
    trades_out.to_parquet(trades_path, compression="zstd", index=False)
    logging.info("Wrote %s (%s rows)", trades_path, f"{len(trades_out):,}")

    state_df = pd.DataFrame(snapshot_rows)
    if not state_df.empty:
        state_df["day"] = pd.to_datetime(state_df["day_ms"], unit="ms", utc=True)
    state_path = args.output_dir / "paper_sim_state.parquet"
    state_df.to_parquet(state_path, compression="zstd", index=False)
    logging.info("Wrote %s (%s daily snapshots)", state_path, f"{len(state_df):,}")

    # -------- stats --------
    lp_gain_pos  = out_lp_delta[out_lp_delta > 0]
    lp_gain_neg  = out_lp_delta[out_lp_delta < 0]

    stats = {
        "simulation_runtime_seconds": float(elapsed),
        "config": cfg,
        "sample_fraction": float(sample_fraction),
        "sample_seed": int(sample_seed),
        "n_trades_input": int(n_input),
        "n_trades_replayed": int(n),
        "n_paper_liquidated": int(out_was_liq.sum()),
        "pct_paper_liquidated": float(100 * out_was_liq.sum() / n),
        "n_hl_liquidated": int(df["hl_was_liquidated"].sum()),
        "pct_hl_liquidated": float(100 * df["hl_was_liquidated"].sum() / n),
        "final_lp_balance_usd": float(lp_balance),
        "final_paper_supply": float(paper_total),
        "final_stakers_balance_usd": float(stakers_total),
        "final_frontend_balance_usd": float(frontend_total),
        "final_tail_progress_usd": float(tail_progress),
        "total_lp_gained_from_losers_and_liqs_usd": float(lp_gain_pos.sum()),
        "total_lp_lost_to_winners_usd": float(-lp_gain_neg.sum()),
        "final_debt_usd": float(debt_total),
        "max_debt_usd": float(max_debt),
        "max_queue_len": int(max_queue_len),
        "total_queued": int(total_queued),
        "total_queue_paid": int(total_queue_paid),
        "by_coin": {},
    }
    for c in ("BTC", "ETH"):
        mask = coin == c
        if not mask.any():
            continue
        m_pos = mask & (out_lp_delta > 0)
        m_neg = mask & (out_lp_delta < 0)
        stats["by_coin"][c] = {
            "n_trades":              int(mask.sum()),
            "n_paper_liquidated":    int(out_was_liq[mask].sum()),
            "pct_paper_liquidated":  float(100 * out_was_liq[mask].sum() / mask.sum()),
            "lp_gained_usd":         float(out_lp_delta[m_pos].sum()),
            "lp_lost_usd":           float(-out_lp_delta[m_neg].sum()),
        }

    stats_path = args.output_dir / "paper_sim_stats.json"
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2, default=str)
    logging.info("Wrote %s", stats_path)

    # -------- pretty summary --------
    print("\n=== Simulation summary ===")
    print(f"  Trades replayed:        {n:>14,}")
    print(f"  Paper liquidations:     {stats['n_paper_liquidated']:>14,}  "
          f"({stats['pct_paper_liquidated']:.2f}%)")
    print(f"  HL liquidations:        {stats['n_hl_liquidated']:>14,}  "
          f"({stats['pct_hl_liquidated']:.2f}%)")
    print()
    print(f"  Final LP balance:       ${lp_balance:>14,.0f}")
    print(f"  Final PAPER supply:     {paper_total:>15,.0f}")
    print(f"  Final stakers balance:  ${stakers_total:>14,.0f}")
    print(f"  Final tail progress:    ${tail_progress:>14,.0f}")
    print()
    print(f"  Total LP gained:        ${stats['total_lp_gained_from_losers_and_liqs_usd']:>14,.0f}")
    print(f"  Total LP lost:          ${stats['total_lp_lost_to_winners_usd']:>14,.0f}")
    print()
    for c, s in stats["by_coin"].items():
        print(f"  {c}: {s['n_trades']:>10,} trades, "
              f"{s['pct_paper_liquidated']:5.1f}% liq in Paper, "
              f"LP +${s['lp_gained_usd']:>14,.0f}, "
              f"-${s['lp_lost_usd']:>14,.0f}")


if __name__ == "__main__":
    sys.exit(main())