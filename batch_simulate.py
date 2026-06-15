#!/usr/bin/env python3
"""
batch_simulate.py — Full factorial sweep of Paper LP simulation.

Parameter grid (fully crossed):
  - baseRate: 5 values [2,3,5,7,10 bps]
  - btcRefNotional: 3 values [$75K,$100K,$125K]
  - ethRefNotional: 3 values [$50K,$75K,$100K]
  = 45 parameter combinations

  rateMult fixed at 1000 (proven insensitive, <3% across 100-5000)
  posMult fixed at $10M (redundant with refNotional)

Outer axes:
  - 4 flow fractions × 38 start days × 2 ADL × 2 emission = 608
  Total: 45 × 608 = 27,360 scenarios (~75 min)

Outputs (all reusable for future analysis):
  batch_results.csv       — summary metrics per scenario (~30 columns)
  batch_daily_lp.csv      — daily LP balance
  batch_daily_debt.csv    — daily queue debt
  batch_daily_queue.csv   — daily queue length
  batch_daily_paper.csv   — daily PAPER supply
  batch_daily_stakers.csv — daily cumulative staker fees
  batch_daily_tail.csv    — daily tail progress

Usage:
    python3 batch_simulate.py --trades /Volumes/External/HyperliquidData/max_lev_trades.parquet
    python3 batch_simulate.py --trades ... --workers 8
"""

from __future__ import annotations

import argparse
import csv
import itertools
import logging
import multiprocessing as mp
import time
from pathlib import Path

from local_server import load_trades, simulate, DEFAULTS, SIM_DAYS, START_MS, DAY_MS

# ---------------------------------------------------------------------------
# Parameter grid — full factorial
# ---------------------------------------------------------------------------
BASE_RATE_VALUES = [0.02, 0.03, 0.05, 0.07, 0.10]
BTC_REF_VALUES   = [75_000, 100_000, 125_000]
ETH_REF_VALUES   = [50_000, 75_000, 100_000]

# Outer axes
SAMPLE_FRACTIONS = [0.25, 0.50, 0.75, 1.0]
START_DAYS       = list(range(0, 260, 7))   # every 7 days, 38 start dates
ADL_OPTIONS      = [False, True]
EMISSION_OPTIONS = [False, True]


def build_scenarios() -> list[dict]:
    """Full factorial: 45 param combos × 608 outer axes = 27,360 scenarios."""
    scenarios = []

    for (br, btc_rn, eth_rn,
         sample_frac, start_day, adl_worst, emission) in itertools.product(
        BASE_RATE_VALUES, BTC_REF_VALUES, ETH_REF_VALUES,
        SAMPLE_FRACTIONS, START_DAYS, ADL_OPTIONS, EMISSION_OPTIONS,
    ):
        params = {
            **DEFAULTS,
            "btcBaseRate": br,
            "ethBaseRate": br,
            "btcReferenceNotional": float(btc_rn),
            "ethReferenceNotional": float(eth_rn),
            "sampleFraction": sample_frac,
            "startDay": start_day,
            "adlWorstCase": adl_worst,
            "emissionBasedVolume": emission,
        }

        em_tag = "emOn" if emission else "emOff"
        label = (
            f"br={br}_btcRN={btc_rn}_ethRN={eth_rn}"
            f"_flow={sample_frac:.0%}_start=d{start_day}"
            f"_adl={'on' if adl_worst else 'off'}"
            f"_{em_tag}"
        )

        scenarios.append({
            "id": label,
            "params": params,
            "emissionBased": emission,
        })

    return scenarios


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
_TRADES = None


def _init_worker(trades):
    global _TRADES
    _TRADES = trades


def _run_one(scenario: dict) -> dict:
    """Run a single scenario, return summary + all daily paths."""
    result = simulate(_TRADES, scenario["params"])
    s = result["stats"]
    p = result["params"]

    summary = {
        "scenario_id": scenario["id"],
        "emissionBased": scenario.get("emissionBased", False),
        "sampleFraction": p["sampleFraction"],
        "startDay": int(p.get("startDay", 0)),
        "adlWorstCase": p["adlWorstCase"],
        "btcBaseRate": p["btcBaseRate"],
        "btcRateMultiplier": p["btcRateMultiplier"],
        "btcPositionMultiplier": p["btcPositionMultiplier"],
        "btcReferenceNotional": p["btcReferenceNotional"],
        "ethBaseRate": p["ethBaseRate"],
        "ethRateMultiplier": p["ethRateMultiplier"],
        "ethPositionMultiplier": p["ethPositionMultiplier"],
        "ethReferenceNotional": p["ethReferenceNotional"],
        "stakerPct": p["stakerPct"],
        "nTrades": s["nTrades"],
        "nLiquidated": s["nLiquidated"],
        "liqPct": round(s["liqPct"], 2),
        "finalLp": round(s["finalLp"], 2),
        "finalPaper": round(s["finalPaper"], 2),
        "finalStakers": round(s["finalStakers"], 2),
        "traderLoss": round(s["traderLoss"], 2),
        "traderWin": round(s["traderWin"], 2),
        "traderNet": round(s["traderNet"], 2),
        "lpGained": round(s["lpGained"], 2),
        "lpLost": round(s["lpLost"], 2),
        "lpMin": round(s["lpMin"], 2),
        "lpMax": round(s["lpMax"], 2),
        "totalVolume": round(s["totalVolume"], 2),
        "maxOi": round(s["maxOi"], 2),
        "marginalMintRate": round(s["marginalMintRate"], 4),
        "feesPerStakedPaper": round(s["feesPerStakedPaper"], 6),
        "costPerPaper": round(s["costPerPaper"], 6),
        "tailProgress": round(s["tailProgress"], 2),
        "maxDebt": round(s["maxDebt"], 2),
        "maxQueueLen": s["maxQueueLen"],
        "totalQueued": s["totalQueued"],
        "totalQueuePaid": s["totalQueuePaid"],
        "queueRemaining": s["queueRemaining"],
        "debtRemaining": round(s["debtRemaining"], 2),
        "avgQueueWait": round(s["avgQueueWait"], 2),
        # Per-coin stats (added in update pass — zero overhead, already tracked in sim)
        "finalBtcLp":    round(s.get("finalBtcLp", 0), 2),
        "finalEthLp":    round(s.get("finalEthLp", 0), 2),
        "btcNTrades":    s.get("btcNTrades", 0),
        "ethNTrades":    s.get("ethNTrades", 0),
        "btcNLiq":       s.get("btcNLiq", 0),
        "ethNLiq":       s.get("ethNLiq", 0),
        "btcLiqPct":     round(s.get("btcLiqPct", 0), 3),
        "ethLiqPct":     round(s.get("ethLiqPct", 0), 3),
        "btcTraderLoss": round(s.get("btcTraderLoss", 0), 2),
        "ethTraderLoss": round(s.get("ethTraderLoss", 0), 2),
        "btcTraderWin":  round(s.get("btcTraderWin", 0), 2),
        "ethTraderWin":  round(s.get("ethTraderWin", 0), 2),
    }

    state = result["state"]
    daily = result["daily"]

    daily_lp           = [round(row["lpBalance"], 2)                 for row in state]
    daily_paper        = [round(row["paperSupply"], 2)               for row in state]
    daily_stakers      = [round(row["stakers"], 2)                   for row in state]
    daily_tail         = [round(row["tailProgress"], 2)              for row in state]
    daily_traderloss   = [round(row.get("cumTraderLoss", 0), 2)      for row in state]
    daily_traderwin    = [round(row.get("cumTraderWin", 0), 2)       for row in state]
    daily_debt         = [round(row.get("peakDebt", row.get("debtTotal", 0)), 2) for row in daily]
    daily_queue        = [row.get("peakQueueLen", row.get("queueSize", 0))       for row in daily]

    return {
        "summary":          summary,
        "daily_lp":         daily_lp,
        "daily_paper":      daily_paper,
        "daily_stakers":    daily_stakers,
        "daily_tail":       daily_tail,
        "daily_traderloss": daily_traderloss,
        "daily_traderwin":  daily_traderwin,
        "daily_debt":       daily_debt,
        "daily_queue":      daily_queue,
    }


def _write_daily_csv(path: Path, results: list[dict], key: str, n_days: int):
    """Write one daily timeseries CSV."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        header = ["scenario_id"] + [f"day_{d}" for d in range(n_days)]
        writer.writerow(header)
        for r in sorted(results, key=lambda x: x["summary"]["scenario_id"]):
            writer.writerow([r["summary"]["scenario_id"]] + r[key])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trades", type=Path,
                        default=Path("/Volumes/External/HyperliquidData/max_lev_trades.parquet"))
    parser.add_argument("--workers", type=int, default=None,
                        help="Number of parallel workers (default: CPU count)")
    parser.add_argument("--out", type=Path, default=Path("."),
                        help="Output directory")
    parser.add_argument("--update-stats-only", action="store_true",
                        help=(
                            "UPDATE MODE: re-runs all scenarios but ONLY appends new per-coin "
                            "columns (finalBtcLp, ethLp, btcLiqPct, ethLiqPct, btcTraderLoss, etc.) "
                            "to the existing batch_results.csv. Skips all daily CSV writes "
                            "(they already exist). ~40-50%% faster than a full rerun."
                        ))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    if args.update_stats_only:
        existing_path = args.out / "batch_results.csv"
        if not existing_path.exists():
            logging.error("--update-stats-only requires existing batch_results.csv at %s", existing_path)
            return
        import pandas as _pd
        existing = _pd.read_csv(existing_path, index_col="scenario_id")
        new_cols = ["finalBtcLp","finalEthLp","btcNTrades","ethNTrades",
                    "btcNLiq","ethNLiq","btcLiqPct","ethLiqPct",
                    "btcTraderLoss","ethTraderLoss","btcTraderWin","ethTraderWin"]
        already_done = all(c in existing.columns for c in new_cols)
        if already_done:
            logging.warning("All per-coin columns already present in batch_results.csv. Nothing to do.")
            return
        logging.info("UPDATE MODE: will add %d new columns; skipping all daily CSV writes.", len(new_cols))

    trades = load_trades(args.trades)
    scenarios = build_scenarios()
    n = len(scenarios)
    logging.info("Running %d scenarios with %d trades...", n, trades["n_total"])

    workers = args.workers or mp.cpu_count()
    logging.info("Using %d workers", workers)

    t0 = time.time()

    try:
        ctx = mp.get_context("fork")
    except ValueError:
        ctx = mp.get_context()

    with ctx.Pool(processes=workers, initializer=_init_worker, initargs=(trades,)) as pool:
        results = []
        for i, result in enumerate(pool.imap_unordered(_run_one, scenarios), 1):
            results.append(result)
            if i % 50 == 0 or i == n:
                elapsed = time.time() - t0
                rate = i / elapsed
                eta = (n - i) / rate if rate > 0 else 0
                logging.info("  %d / %d done (%.1f/s, ETA %.0fs)", i, n, rate, eta)

    elapsed = time.time() - t0
    logging.info("All %d scenarios completed in %.1fs (%.1f/s)", n, elapsed, n / elapsed)

    args.out.mkdir(parents=True, exist_ok=True)

    if args.update_stats_only:
        # ── UPDATE MODE: only append new per-coin columns ──
        import pandas as _pd
        new_cols = ["finalBtcLp","finalEthLp","btcNTrades","ethNTrades",
                    "btcNLiq","ethNLiq","btcLiqPct","ethLiqPct",
                    "btcTraderLoss","ethTraderLoss","btcTraderWin","ethTraderWin"]
        updates = {r["summary"]["scenario_id"]: {k: r["summary"][k] for k in new_cols}
                   for r in results}
        existing = _pd.read_csv(args.out / "batch_results.csv")
        # Remove old per-coin columns if present (idempotent)
        existing.drop(columns=[c for c in new_cols if c in existing.columns],
                      inplace=True, errors="ignore")
        patch = _pd.DataFrame.from_dict(updates, orient="index")
        patch.index.name = "scenario_id"
        patch.reset_index(inplace=True)
        merged = existing.merge(patch, on="scenario_id", how="left")
        summary_path = args.out / "batch_results.csv"
        merged.to_csv(summary_path, index=False)
        logging.info("UPDATE DONE: added %d per-coin columns → %s (%d rows)",
                     len(new_cols), summary_path, len(merged))
        logging.info("Daily CSVs NOT rewritten (already exist, unchanged).")
        return

    # --- Full run: write everything ---
    summary_path = args.out / "batch_results.csv"
    summaries = [r["summary"] for r in results]
    summaries.sort(key=lambda x: x["scenario_id"])
    fields = list(summaries[0].keys())
    with open(summary_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summaries)
    logging.info("Summary → %s (%d rows)", summary_path, len(summaries))

    # Daily timeseries CSVs
    daily_files = [
        ("batch_daily_lp.csv",          "daily_lp"),
        ("batch_daily_paper.csv",        "daily_paper"),
        ("batch_daily_stakers.csv",      "daily_stakers"),
        ("batch_daily_tail.csv",         "daily_tail"),
        ("batch_daily_traderloss.csv",   "daily_traderloss"),
        ("batch_daily_traderwin.csv",    "daily_traderwin"),
        ("batch_daily_debt.csv",         "daily_debt"),
        ("batch_daily_queue.csv",        "daily_queue"),
    ]
    for filename, key in daily_files:
        path = args.out / filename
        _write_daily_csv(path, results, key, SIM_DAYS)
        logging.info("  %s → %d scenarios × %d days", filename, len(results), SIM_DAYS)


if __name__ == "__main__":
    main()
