#!/usr/bin/env python3
"""
run_all.py — Run batch simulation + generate all charts in one go.

Steps:
  1. batch_simulate.py  — run all scenarios (base + emission-based)
  2. plot_batch.py       — parameter sweep charts (01-08)        → charts/
  3. plot_yield.py       — yield & PAPER charts (09-12)          → charts/
  4. plot_extra.py       — volume, OI, distribution (15-19)      → charts/
  5. plot_emission.py    — emission model comparison (E01-E08)   → charts_emission/

Usage:
    python3 run_all.py --trades /Volumes/External/HyperliquidData/max_lev_trades.parquet
    python3 run_all.py --trades ... --workers 8 --skip-sim
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


def run_step(name: str, cmd: list[str]):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    t0 = time.time()
    result = subprocess.run(cmd, cwd=str(Path(__file__).parent))
    elapsed = time.time() - t0
    if result.returncode != 0:
        print(f"  FAILED ({elapsed:.1f}s, exit code {result.returncode})")
        sys.exit(result.returncode)
    print(f"  OK ({elapsed:.1f}s)")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trades", type=Path,
                        default=Path("/Volumes/External/HyperliquidData/max_lev_trades.parquet"))
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--out", type=Path, default=Path("."),
                        help="Output directory for CSVs")
    parser.add_argument("--skip-sim", action="store_true",
                        help="Skip simulation, only regenerate charts from existing CSVs")
    args = parser.parse_args()

    py = sys.executable
    base_dir = Path(__file__).parent

    t_start = time.time()

    # Step 1: Batch simulation
    if not args.skip_sim:
        cmd = [py, str(base_dir / "batch_simulate.py"),
               "--trades", str(args.trades),
               "--out", str(args.out)]
        if args.workers:
            cmd += ["--workers", str(args.workers)]
        run_step("Step 1/5: Batch simulation", cmd)
    else:
        print("\n  Skipping simulation (--skip-sim)")

    # Step 2: Parameter sweep charts (base model only)
    run_step("Step 2/5: Parameter sweep charts (01-08)",
             [py, str(base_dir / "plot_batch.py"), "--dir", str(args.out)])

    # Step 3: Yield & PAPER charts
    run_step("Step 3/5: Yield & PAPER charts (09-12)",
             [py, str(base_dir / "plot_yield.py"), "--dir", str(args.out)])

    # Step 4: Extra charts (volume, OI, distributions)
    run_step("Step 4/5: Extra charts (15-19)",
             [py, str(base_dir / "plot_extra.py")])

    # Step 5: Emission model comparison charts
    run_step("Step 5/5: Emission model charts (E01-E08)",
             [py, str(base_dir / "plot_emission.py"), "--dir", str(args.out)])

    total = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"  ALL DONE in {total:.0f}s ({total/60:.1f} min)")
    print(f"  Charts:    {args.out}/charts/")
    print(f"  Emission:  {args.out}/charts_emission/")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
