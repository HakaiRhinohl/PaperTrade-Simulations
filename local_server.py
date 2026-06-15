#!/usr/bin/env python3
"""
local_server.py — Paper LP simulation engine.

Core simulation logic for the Paper protocol: loads max-leverage trades,
runs them through the LP/staker/queue/minting model, and returns daily
time series + final statistics.

Exported for use by batch_simulate.py and other scripts:
    from local_server import load_trades, simulate, DEFAULTS, SIM_DAYS, START_MS, DAY_MS
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants (must match app.js)
# ---------------------------------------------------------------------------
DAY_MS = 86_400_000
START_MS = 1754006400000   # Date.UTC(2025, 7, 1) = Aug 1, 2025
SIM_DAYS = 290

REAL_ADL = {70:857,71:10,72:6,73:7,74:6,75:1,76:7,77:3,80:1,81:3,83:1,86:1,88:1,89:1,90:2,93:2,94:2,95:1,96:1,103:2,104:1,105:1,106:1,108:1,109:1,112:2,122:3,123:2,125:1,126:1,132:2,137:1,140:1,143:1,166:1,170:1,183:1,188:1,189:2,191:1,192:1,194:1,207:1,212:1,216:1,227:1,231:1,238:1,240:1,246:1,259:1,261:1,269:1,271:1,272:1,273:1,278:1,280:1,283:1,286:1,287:3,288:2}
ADL_HEADROOM = {70:0.026006,71:0.030117,72:0.002278,73:0.056038,74:0.018076,75:0.043984,76:0.011549,77:0.028544,80:0.013425,81:0.052463,83:0.014501,86:0.016638,88:0.02287,89:0.030971,90:0.051154,93:0.010538,94:0.026174,95:0.048435,96:0.009528,103:0.00971,104:0.049564,105:0.034622,106:0.005507,108:0.029418,109:0.034278,112:0.039256,122:0.0337,123:0.039793,125:0.025214,126:0.035094,132:0.034973,137:0.010118,140:0.005363,143:0.023355,166:0.003438,170:0.00189,183:0.135681,188:0.033616,189:0.158105,191:0.030463,192:0.008718,194:0.050442,207:0.009369,212:0.030291,216:0.033707,227:0.031492,231:0.01402,238:0.02169,240:0.011397,246:0.017428,259:0.01994,261:0.035637,269:0.009658,271:0.013472,272:0.004878,273:0.023172,278:0.011229,280:0.009869,283:0.002516,286:0.009236,287:0.003622,288:0.005757}

DEFAULTS = dict(
    leverage=1000.0, bufferBps=5.0, maxOpenUsd=10_000_000.0, initialLpUsd=0.0,
    flatRate=100.0, thresholdUsd=2_000_000.0, tailScaleUsd=120_000_000.0,
    stakerPct=0.02, lpCapUsd=5_000_000.0, stakedFraction=1.0,
    sampleFraction=1.0, volatility=1.0, volumeScale=1.0,
    btcBaseRate=0.05, btcRateMultiplier=1000.0,
    btcPositionMultiplier=10_000_000.0, btcReferenceNotional=100_000.0,
    ethBaseRate=0.05, ethRateMultiplier=1000.0,
    ethPositionMultiplier=10_000_000.0, ethReferenceNotional=50_000.0,
    adlWorstCase=False,
    startDay=0,
    emissionBasedVolume=False,
)

# ---------------------------------------------------------------------------
# Trade loading
# ---------------------------------------------------------------------------
def load_trades(path: Path) -> dict:
    """Load and pre-process real trades into numpy arrays bucketed by day."""
    logging.info("Loading trades from %s ...", path)
    t0 = time.time()
    df = pd.read_parquet(path, columns=[
        "coin", "direction", "open_time_ms", "close_time_ms",
        "open_px", "close_px", "notional_at_entry_usd", "worst_adverse_pct",
    ])
    logging.info("Loaded %s trades in %.1fs", f"{len(df):,}", time.time() - t0)

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
    df["is_btc"] = (df["coin"] == "BTC").astype(np.int8)

    # Drop rows with NaN
    mask = df[["closeMovePct", "adversePct", "notional"]].notna().all(axis=1) & (df["open_px"] > 0)
    df = df[mask].sort_values("closeDay", kind="mergesort").reset_index(drop=True)
    logging.info("Valid trades: %s", f"{len(df):,}")

    # Deterministic sample key (uniform hash of index)
    rng = np.random.default_rng(42)
    df["sampleKey"] = rng.random(len(df))

    # Bucket by closeDay (vectorized groupby instead of iterrows)
    by_day = [[] for _ in range(SIM_DAYS)]
    close_days = df["closeDay"].values
    for idx in range(len(close_days)):
        by_day[int(close_days[idx])].append(idx)

    return {
        "is_btc": df["is_btc"].values,
        "openDay": df["openDay"].values,
        "closeDay": df["closeDay"].values,
        "closeMovePct": df["closeMovePct"].values,
        "adversePct": df["adversePct"].values,
        "notional": df["notional"].values,
        "sampleKey": df["sampleKey"].values,
        "by_day": by_day,
        "n_total": len(df),
    }


# ---------------------------------------------------------------------------
# Simulation (mirrors app.js simulate())
# ---------------------------------------------------------------------------
def impact_scale(is_btc: bool, move_pct: float, p: dict) -> float:
    if move_pct <= 0:
        return 0.0
    prefix = "btc" if is_btc else "eth"
    base = p[f"{prefix}BaseRate"]
    rm = p[f"{prefix}RateMultiplier"]
    pm = p[f"{prefix}PositionMultiplier"]
    rn = p[f"{prefix}ReferenceNotional"]
    t1 = 1.0 / (move_pct * rm)
    t2 = rn / (move_pct * pm)
    return max(0.0, min(1.0, (1.0 - base) / (1.0 + t1 + t2)))


def simulate(trades: dict, params: dict) -> dict:
    p = {**DEFAULTS, **params}
    t0 = time.time()

    # Arrays
    is_btc_arr = trades["is_btc"]
    openDay_arr = trades["openDay"]
    closeMovePct_arr = trades["closeMovePct"]
    adversePct_arr = trades["adversePct"]
    notional_arr = trades["notional"]
    sampleKey_arr = trades["sampleKey"]
    by_day = trades["by_day"]

    leverage = p["leverage"]
    buffer_bps = p["bufferBps"]
    max_open = p["maxOpenUsd"]
    vol = p["volatility"]
    vol_scale = p["volumeScale"]
    sample_frac = p["sampleFraction"]
    staker_pct = p["stakerPct"]
    lp_cap = p["lpCapUsd"]
    flat_rate = p["flatRate"]
    threshold = p["thresholdUsd"]
    tail_scale = p["tailScaleUsd"]
    tail_scale_sq = tail_scale * tail_scale
    tolerance = max(0.0, 1.0 / leverage - buffer_bps / 10_000)
    adl_worst = p["adlWorstCase"]
    staked_frac = p["stakedFraction"]
    start_day = int(p.get("startDay", 0))
    emission_vol = bool(p.get("emissionBasedVolume", False))

    lp_balance = float(p["initialLpUsd"])
    paper_total = 0.0
    stakers_total = 0.0
    tail_progress = 0.0
    lp_gained = 0.0
    lp_lost = 0.0
    trader_loss = 0.0
    trader_win  = 0.0
    n_trades    = 0
    n_liquidated = 0
    btc_lp = 0.0
    eth_lp = 0.0
    # Per-coin accounting (no overhead — already computing ibtc per trade)
    btc_n_trades = 0; eth_n_trades = 0
    btc_n_liq    = 0; eth_n_liq    = 0
    btc_loss = 0.0;   eth_loss = 0.0
    btc_win  = 0.0;   eth_win  = 0.0
    oi_btc = 0.0
    oi_eth = 0.0

    # Queue: when LP can't pay a winning trader, the payout is deferred
    from collections import deque
    queue = deque()          # entries: (amount_owed, day_entered)
    debt_total = 0.0         # sum of all amounts in queue
    total_queued = 0         # lifetime count of trades that entered queue
    total_queue_paid = 0     # lifetime count of trades paid from queue
    total_queue_wait = 0     # sum of wait-days for all paid queue trades
    max_debt = 0.0
    max_queue_len = 0

    # OI tracking
    oi_btc_delta = np.zeros(SIM_DAYS + 1)
    oi_eth_delta = np.zeros(SIM_DAYS + 1)

    # Pre-compute base volume per openDay (before emission scaling)
    daily_volume = np.zeros(SIM_DAYS)
    daily_volume_btc = np.zeros(SIM_DAYS)
    daily_volume_eth = np.zeros(SIM_DAYS)

    # Filter by sampleKey
    included = sampleKey_arr <= sample_frac

    for idx in range(len(notional_arr)):
        if not included[idx]:
            continue
        cd = min(SIM_DAYS - 1, int(trades["closeDay"][idx]))
        if cd < start_day:
            continue
        notional_entry = notional_arr[idx] * vol_scale
        paper_notional = min(notional_entry, max_open)
        od = max(start_day, int(openDay_arr[idx]))
        daily_volume[od] += notional_entry
        if is_btc_arr[idx]:
            daily_volume_btc[od] += notional_entry
            oi_btc_delta[od] += paper_notional
            oi_btc_delta[min(SIM_DAYS, cd + 1)] -= paper_notional
        else:
            daily_volume_eth[od] += notional_entry
            oi_eth_delta[od] += paper_notional
            oi_eth_delta[min(SIM_DAYS, cd + 1)] -= paper_notional

    # Runtime volume accumulators (reflect emission scaling)
    rt_volume = np.zeros(SIM_DAYS)
    rt_volume_btc = np.zeros(SIM_DAYS)
    rt_volume_eth = np.zeros(SIM_DAYS)
    daily_em_mult = np.ones(SIM_DAYS)  # emission multiplier per day

    # Daily arrays for output
    daily_out = []
    state_out = []

    for day in range(SIM_DAYS):
        if day < start_day:
            daily_out.append({"day": day, "nTrades": 0, "nLiquidated": 0,
                "liqPct": 0, "volume": 0, "volumeBtc": 0, "volumeEth": 0,
                "traderLoss": 0, "traderWin": 0, "traderNet": 0,
                "nAdl": REAL_ADL.get(day, 0), "adlVolume": 0,
                "oiBtc": 0, "oiEth": 0, "oiTotal": 0,
                "debtTotal": 0, "queueSize": 0,
                "queueEntered": 0, "queuePaid": 0})
            state_out.append({"day": day, "lpBalance": lp_balance,
                "paperSupply": 0, "stakers": 0, "tailProgress": 0,
                "btcLp": 0, "ethLp": 0})
            continue
        day_n_trades = 0
        day_n_liq = 0
        day_trader_loss = 0.0
        day_trader_win = 0.0
        day_adl_volume = 0.0
        day_queue_entered = 0
        day_queue_paid = 0
        day_peak_debt = debt_total    # track intra-day peak
        day_peak_queue = len(queue)

        adl_remaining = REAL_ADL.get(day, 0) if adl_worst else 0
        headroom = ADL_HEADROOM.get(day, 0.0)

        # Emission-based volume: scale notional by current mint rate / flat rate
        if emission_vol:
            if lp_balance < threshold:
                em_mult = 1.0           # flat region — full incentive
            else:
                em_mult = (tail_scale / (tail_scale + tail_progress)) ** 2
        else:
            em_mult = 1.0
        daily_em_mult[day] = em_mult

        for idx in by_day[day]:
            if not included[idx]:
                continue

            n_trades += 1
            day_n_trades += 1

            notional_entry = notional_arr[idx] * vol_scale * em_mult
            paper_notional = min(notional_entry, max_open)
            margin = paper_notional / leverage
            close_move = closeMovePct_arr[idx] * vol
            adverse = abs(adversePct_arr[idx] * vol)
            ibtc = bool(is_btc_arr[idx])

            # Track runtime volume (reflects emission scaling)
            rt_volume[day] += notional_entry
            if ibtc:
                rt_volume_btc[day] += notional_entry
            else:
                rt_volume_eth[day] += notional_entry

            # ADL worst case
            if adl_remaining > 0 and close_move > 0:
                close_move += headroom
                adl_remaining -= 1
                day_adl_volume += paper_notional

            paper_liq = adverse >= tolerance
            raw_pnl = close_move * paper_notional
            lp_event = 0.0
            user_outcome = 0.0
            is_liquidation = False
            impact_revenue = 0.0

            if paper_liq:
                lp_event = margin
                user_outcome = -margin
                n_liquidated += 1
                day_n_liq += 1
                is_liquidation = True
            elif raw_pnl >= 0:
                scale = impact_scale(ibtc, abs(close_move), p)
                adjusted = raw_pnl * scale
                impact_revenue = raw_pnl - adjusted
                lp_event = -adjusted
                user_outcome = adjusted
            else:
                lp_event = -raw_pnl
                user_outcome = raw_pnl

            # Per-coin counters (ibtc already computed above)
            if ibtc: btc_n_trades += 1
            else:    eth_n_trades += 1
            if is_liquidation:
                if ibtc: btc_n_liq += 1
                else:    eth_n_liq += 1

            if user_outcome < 0:
                trader_loss += -user_outcome
                day_trader_loss += -user_outcome
                if ibtc: btc_loss += -user_outcome
                else:    eth_loss += -user_outcome
            else:
                trader_win += user_outcome
                day_trader_win += user_outcome
                if ibtc: btc_win += user_outcome
                else:    eth_win += user_outcome

            lp_delta = lp_event
            stakers_event = 0.0
            queue_was_empty = len(queue) == 0

            if lp_event > 0:
                # --- LP GAINS (trader liquidated or lost) ---
                stakers_cut = lp_event * staker_pct
                lp_gain = lp_event - stakers_cut

                # FIX 1+2: mint_basis BEFORE queue drain / cap handling
                # Liquidations: mint on full margin (docs: regardless of solvency)
                # Losses: mint on LP gain after staker fee (docs: rawLoss − fee)
                if is_liquidation:
                    mint_basis = lp_event          # full margin
                else:
                    mint_basis = lp_gain           # after 2 % fee

                # 1) Drain queue FIFO before growing LP
                while queue and lp_gain > 0:
                    owed, entry_day = queue[0]
                    if lp_gain >= owed:
                        lp_gain -= owed
                        debt_total -= owed
                        total_queue_wait += (day - entry_day)
                        total_queue_paid += 1
                        day_queue_paid += 1
                        queue.popleft()
                    else:
                        queue[0] = (owed - lp_gain, entry_day)
                        debt_total -= lp_gain
                        lp_gain = 0.0

                # 2) Remaining lp_gain grows LP (cap handling)
                excess = 0.0
                if lp_balance >= lp_cap:
                    excess = lp_gain
                    lp_gain = 0.0
                elif lp_balance + lp_gain > lp_cap:
                    excess = lp_balance + lp_gain - lp_cap
                    lp_gain -= excess

                stakers_event = stakers_cut + excess
                lp_pre = lp_balance
                lp_balance += lp_gain
                lp_delta = lp_gain

                # FIX 1+4: PAPER minting on mint_basis (not post-cap lp_gain)
                # Gated: non-liquidation losses skip when queue was non-empty
                should_mint = is_liquidation or queue_was_empty

                if should_mint and mint_basis > 0:
                    if lp_pre < threshold:
                        if (lp_pre + mint_basis) <= threshold:
                            flat_part = mint_basis
                            tail_part = 0.0
                        else:
                            flat_part = threshold - lp_pre
                            tail_part = mint_basis - flat_part
                    else:
                        flat_part = 0.0
                        tail_part = mint_basis

                    paper_total += flat_part * flat_rate
                    if tail_part > 0:
                        new_tail = tail_progress + tail_part
                        paper_total += flat_rate * tail_scale_sq * (
                            1.0 / (tail_scale + tail_progress) - 1.0 / (tail_scale + new_tail)
                        )
                        tail_progress = new_tail

                stakers_total += stakers_event
                lp_gained += max(0, lp_delta)
            else:
                # --- LP PAYS (trader won) ---
                payout = -lp_event  # positive amount
                lp_lost += payout

                # FIX 3: impact-revenue staker fee (suppressed when queue non-empty)
                staker_impact = 0.0
                if impact_revenue > 0 and queue_was_empty:
                    staker_impact = impact_revenue * staker_pct

                if lp_balance >= payout:
                    lp_balance -= payout
                    # Staker cut from impact revenue (from LP's retained amount)
                    if staker_impact > 0:
                        actual_impact = min(staker_impact, lp_balance)
                        lp_balance -= actual_impact
                        stakers_total += actual_impact
                else:
                    # LP can't fully pay — queue the shortfall
                    shortfall = payout - lp_balance
                    lp_balance = 0.0
                    queue.append((shortfall, day))
                    debt_total += shortfall
                    total_queued += 1
                    day_queue_entered += 1

                lp_delta = -payout  # how much LP changed (negative)

            # Track queue peaks (global + intra-day)
            if debt_total > max_debt:
                max_debt = debt_total
            if debt_total > day_peak_debt:
                day_peak_debt = debt_total
            if len(queue) > max_queue_len:
                max_queue_len = len(queue)
            if len(queue) > day_peak_queue:
                day_peak_queue = len(queue)

            if ibtc:
                btc_lp += lp_delta
            else:
                eth_lp += lp_delta

        liq_pct = (100.0 * day_n_liq / day_n_trades) if day_n_trades else 0.0
        oi_btc += oi_btc_delta[day]
        oi_eth += oi_eth_delta[day]

        daily_out.append({
            "day": day,
            "nTrades": day_n_trades,
            "nLiquidated": day_n_liq,
            "liqPct": liq_pct,
            "volume": float(rt_volume[day]) if emission_vol else float(daily_volume[day]),
            "volumeBtc": float(rt_volume_btc[day]) if emission_vol else float(daily_volume_btc[day]),
            "volumeEth": float(rt_volume_eth[day]) if emission_vol else float(daily_volume_eth[day]),
            "emissionMult": float(daily_em_mult[day]),
            "traderLoss": day_trader_loss,
            "traderWin": day_trader_win,
            "traderNet": trader_win - trader_loss,
            "nAdl": REAL_ADL.get(day, 0),
            "adlVolume": day_adl_volume,
            "oiBtc": oi_btc,
            "oiEth": oi_eth,
            "oiTotal": oi_btc + oi_eth,
            "debtTotal": debt_total,
            "queueSize": len(queue),
            "queueEntered": day_queue_entered,
            "queuePaid": day_queue_paid,
            "peakDebt": day_peak_debt,
            "peakQueueLen": day_peak_queue,
        })

        state_out.append({
            "day": day,
            "lpBalance": lp_balance,
            "paperSupply": paper_total,
            "stakers": stakers_total,
            "tailProgress": tail_progress,
            "btcLp": btc_lp,
            "ethLp": eth_lp,
            "emissionMult": float(daily_em_mult[day]),
            "cumTraderLoss": trader_loss,
            "cumTraderWin":  trader_win,
        })

    final_lp = lp_balance
    lp_values = [s["lpBalance"] for s in state_out]
    marginal_mint = (
        flat_rate if final_lp < threshold
        else flat_rate * (tail_scale / (tail_scale + tail_progress)) ** 2
    )
    fees_per = stakers_total / max(1e-9, paper_total * staked_frac)
    total_vol = sum(d["volume"] for d in daily_out)
    max_oi = max((d["oiTotal"] for d in daily_out), default=0)

    elapsed = time.time() - t0
    logging.info("Simulation: %s trades in %.2fs", f"{n_trades:,}", elapsed)

    return {
        "daily": daily_out,
        "state": state_out,
        "stats": {
            "nTrades": n_trades,
            "nLiquidated": n_liquidated,
            "liqPct": (100.0 * n_liquidated / n_trades) if n_trades else 0,
            "finalLp": final_lp,
            "finalPaper": paper_total,
            "finalStakers": stakers_total,
            "tailProgress": tail_progress,
            "tolerance": tolerance,
            "marginalMintRate": marginal_mint,
            "feesPerStakedPaper": fees_per,
            "costPerPaper": trader_loss / max(1e-9, paper_total),
            "traderLoss": trader_loss,
            "traderWin": trader_win,
            "traderNet": trader_win - trader_loss,
            "lpGained": lp_gained,
            "lpLost": lp_lost,
            "totalVolume": total_vol,
            "maxOi": max_oi,
            "finalBtcLp": btc_lp,
            "finalEthLp": eth_lp,
            "btcNTrades":  btc_n_trades,
            "ethNTrades":  eth_n_trades,
            "btcNLiq":     btc_n_liq,
            "ethNLiq":     eth_n_liq,
            "btcLiqPct":   (100.0 * btc_n_liq / btc_n_trades) if btc_n_trades else 0,
            "ethLiqPct":   (100.0 * eth_n_liq / eth_n_trades) if eth_n_trades else 0,
            "btcTraderLoss": btc_loss,
            "ethTraderLoss": eth_loss,
            "btcTraderWin":  btc_win,
            "ethTraderWin":  eth_win,
            "nLpGainTrades": 0,
            "nLpLossTrades": 0,
            "lpMin": min(lp_values[start_day:]) if lp_values[start_day:] else 0,
            "lpMax": max(lp_values[start_day:]) if lp_values[start_day:] else 0,
            "maxDebt": max_debt,
            "maxQueueLen": max_queue_len,
            "totalQueued": total_queued,
            "totalQueuePaid": total_queue_paid,
            "queueRemaining": len(queue),
            "debtRemaining": debt_total,
            "avgQueueWait": (total_queue_wait / total_queue_paid) if total_queue_paid else 0,
        },
        "params": p,
        "meta": {
            "totalTradesLoaded": trades["n_total"],
            "elapsed": round(elapsed, 3),
        },
    }


