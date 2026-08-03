#!/usr/bin/env python3
"""
run.py — the single entry point for the Paper simulation.

Edit `paper_config.yaml`, then run one of:

    python3 run.py                  # simulate at the configured parameters,
                                    # then build the single-run charts
    python3 run.py --sweep          # also run the scenario sweep
                                    # (flow x launch day x ADL x emission)
                                    # and build every chart. Slow: ~15 min on 8 cores.
    python3 run.py --charts-only    # rebuild charts from existing results, no simulation

Common options:
    --trades PATH     trade dataset (default: data/max_lev_trades_v3.parquet)
    --config PATH     parameter file (default: paper_config.yaml)
    --workers N       parallel workers for the sweep (default: all cores)
    --full-sweep      sweep the impact parameters too (27,360 scenarios instead of 608).
                      Only useful if you want to explore impact-curve settings.

Outputs:
    charts/              charts from the run
    charts_emission/     base vs emission-based model comparison   (--sweep)
    charts_comparison/   side-by-side comparisons                  (--sweep)
    batch_results.csv    one row per scenario                      (--sweep)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
PIPE = BASE / "pipeline"

# Flow fractions simulated in isolation (share of Hyperliquid's actual volume).
FLOW_FRACTIONS = [0.25, 0.50, 0.75, 1.00]


def run_step(name: str, cmd: list[str]) -> None:
    print(f"\n{'=' * 60}\n  {name}\n{'=' * 60}")
    t0 = time.time()
    result = subprocess.run(cmd, cwd=str(BASE))
    elapsed = time.time() - t0
    if result.returncode != 0:
        print(f"  FAILED ({elapsed:.1f}s, exit code {result.returncode})")
        sys.exit(result.returncode)
    print(f"  OK ({elapsed:.1f}s)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trades", type=Path,
                        default=BASE / "data" / "max_lev_trades_v3.parquet")
    parser.add_argument("--config", type=Path, default=BASE / "paper_config.yaml")
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--sweep", action="store_true",
                        help="also run the scenario sweep and its charts")
    parser.add_argument("--full-sweep", action="store_true",
                        help="sweep impact parameters too (27,360 scenarios)")
    parser.add_argument("--charts-only", action="store_true",
                        help="rebuild charts from existing results, no simulation")
    args = parser.parse_args()

    if not args.charts_only and not args.trades.exists():
        print(f"Trade dataset not found: {args.trades}\n"
              f"Download it (see README) and place it at data/max_lev_trades_v3.parquet,\n"
              f"or pass --trades /path/to/max_lev_trades_v3.parquet")
        sys.exit(1)

    py = sys.executable
    sweep = args.sweep or args.full_sweep
    t_start = time.time()

    # ── Simulation ────────────────────────────────────────────────────────
    if not args.charts_only:
        if sweep:
            cmd = [py, str(PIPE / "batch_simulate.py"),
                   "--trades", str(args.trades), "--out", str(BASE)]
            if not args.full_sweep:
                # Impact parameters are fixed in the config, so there is nothing
                # to sweep on that axis: 608 scenarios instead of 27,360.
                cmd.append("--fixed-impact")
            if args.workers:
                cmd += ["--workers", str(args.workers)]
            run_step("Scenario sweep", cmd)

        for frac in FLOW_FRACTIONS:
            sim_dir = BASE / f"sim_flow_{frac:.2f}"
            sim_dir.mkdir(parents=True, exist_ok=True)
            run_step(f"Simulating at {frac:.0%} of Hyperliquid volume",
                     [py, str(PIPE / "simulate_paper_lp.py"),
                      "--trades", str(args.trades),
                      "--config", str(args.config),
                      "--output-dir", str(sim_dir),
                      "--sample-fraction", str(frac)])

        # The sweep charts read the full-flow run from the repo root.
        for name in ("paper_sim_trades.parquet", "paper_sim_state.parquet"):
            src = BASE / "sim_flow_1.00" / name
            if src.exists():
                shutil.copyfile(src, BASE / name)

    # ── Charts from the single run ────────────────────────────────────────
    run_step("Charts: LP, minting, trader P&L",
             [py, str(PIPE / "make_charts.py"),
              "--sim-dir", str(BASE / "sim_flow_1.00"),
              "--config", str(args.config),
              "--source-trades", str(args.trades),
              "--charts-dir", str(BASE / "charts")])

    run_step("Charts: per-coin breakdown (BTC vs ETH)",
             [py, str(PIPE / "plot_coins.py"),
              "--sim-dir", str(BASE / "sim_flow_1.00"),
              "--config", str(args.config),
              "--charts-dir", str(BASE / "charts")])

    run_step("Charts: volume, open interest, distributions",
             [py, str(PIPE / "plot_extra.py"),
              "--trades", str(args.trades),
              "--charts-dir", str(BASE / "charts")])

    # ── Charts that need the sweep ────────────────────────────────────────
    if sweep or args.charts_only:
        run_step("Charts: solvency and debt across scenarios",
                 [py, str(PIPE / "plot_batch.py"), "--dir", str(BASE)])
        run_step("Charts: PAPER supply and staker yield",
                 [py, str(PIPE / "plot_yield.py"), "--dir", str(BASE)])
        run_step("Charts: emission model comparison",
                 [py, str(PIPE / "plot_emission.py"), "--dir", str(BASE)])
        run_step("Charts: publication figures and tables",
                 [py, str(PIPE / "plot_figures.py")])

    total = time.time() - t_start
    print(f"\n{'=' * 60}")
    print(f"  Done in {total:.0f}s ({total / 60:.1f} min)")
    print(f"  charts/")
    if sweep or args.charts_only:
        print(f"  charts_emission/")
        print(f"  charts_comparison/")
    if not args.charts_only and sweep:
        print(f"  batch_results.csv")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
