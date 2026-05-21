#!/usr/bin/env python3
"""
build_trades.py — Extract the max-leverage trades table from fills_leveraged.

One row per HL position episode (open → close/liq cycle) that was at max-lev
certain. This is the input to the Paper LP simulation: each row will be
"replayed" in Paper at 1000x leverage under Paper mechanics.

Output schema (max_lev_trades.parquet):

  trade_id              str   composite key (coin:address:episode_id)
  coin                  str   BTC or ETH
  address               str   wallet (info, not used by sim)
  direction             str   "long" or "short"
  open_time_ms          int64 millisecond UTC of first fill of the episode
  close_time_ms         int64 millisecond UTC of last fill
  open_px               float weighted-avg entry price (over opening fills)
  close_px              float weighted-avg exit price (over closing fills)
  size_units            float max |position| reached during the episode
                              (= the trade's size for the sim)
  notional_at_entry_usd float open_px × size_units
  hl_leverage           int   the snap leverage observed (40 or 25)
  worst_adverse_px      float lowest (for long) or highest (for short)
                              price seen during the episode
  worst_adverse_pct     float |open_px - worst_adverse_px| / open_px
  hl_was_liquidated     bool  True if HL liquidated this position
  hl_was_adl            bool  True if ADL'd
  hl_liq_px             float HL's liquidation price (if liquidated)
  hl_realized_pnl_usd   float sum of realized_pnl from closing fills
  holding_seconds       float (close_time_ms - open_time_ms) / 1000

Filters applied:
  - is_max_lev_certain = TRUE (we know for sure leverage was at max ±5%)
  - size_units > 0
  - open_px is computable (had opening fills)
  - close_time_ms > open_time_ms (must have closed)
  - direction is non-null
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import duckdb


def list_valid_parquet(root: Path) -> list[str]:
    return sorted(
        str(p) for p in root.rglob("*.parquet")
        if not p.name.startswith("._")
    )


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--leveraged-dir", type=Path, required=True,
                   help="Path to fills_leveraged dir produced by join_leverage.py")
    p.add_argument("--output", type=Path, required=True,
                   help="Output path for max_lev_trades.parquet")
    p.add_argument("--memory-limit", default="20GB")
    p.add_argument("--include-possible", action="store_true",
                   help="Also include is_max_lev_possible (less certain) trades")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")

    files = list_valid_parquet(args.leveraged_dir)
    if not files:
        sys.exit(f"ERROR: no parquet in {args.leveraged_dir}")
    logging.info("Reading %d parquet files", len(files))

    con = duckdb.connect()
    con.execute(f"SET memory_limit = '{args.memory_limit}'")
    con.execute("SET preserve_insertion_order = FALSE")

    filter_clause = "is_max_lev_certain = TRUE"
    if args.include_possible:
        filter_clause = "(is_max_lev_certain = TRUE OR (is_max_lev_possible = TRUE AND NOT is_max_lev_excluded))"
        logging.info("Including is_max_lev_possible trades (less certain leverage)")
    else:
        logging.info("Only is_max_lev_certain trades (strict)")

    t0 = time.time()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    con.execute(f"""
        COPY (
            WITH src AS (
                SELECT * FROM read_parquet({json.dumps(files)})
                WHERE {filter_clause}
            ),
            agg AS (
                SELECT
                    base_symbol AS coin,
                    address,
                    episode_id,
                    MIN(time_ms) AS open_time_ms,
                    MAX(time_ms) AS close_time_ms,

                    -- Weighted entry: fills that increased |position|
                    SUM(CASE WHEN abs(pos_after) > abs(COALESCE(pos_before, 0))
                             THEN price * abs(pos_after - COALESCE(pos_before, 0))
                             ELSE 0 END)
                      / NULLIF(SUM(CASE WHEN abs(pos_after) > abs(COALESCE(pos_before, 0))
                                         THEN abs(pos_after - COALESCE(pos_before, 0))
                                         ELSE 0 END), 0) AS open_px,

                    -- Weighted exit: fills that decreased |position|
                    SUM(CASE WHEN abs(pos_after) < abs(COALESCE(pos_before, 0))
                             THEN price * abs(COALESCE(pos_before, 0) - pos_after)
                             ELSE 0 END)
                      / NULLIF(SUM(CASE WHEN abs(pos_after) < abs(COALESCE(pos_before, 0))
                                         THEN abs(COALESCE(pos_before, 0) - pos_after)
                                         ELSE 0 END), 0) AS close_px,

                    MAX(abs(pos_after)) AS size_units,
                    ANY_VALUE(CASE WHEN pos_after > 0 THEN 'long'
                                   WHEN pos_after < 0 THEN 'short' END)
                        FILTER (WHERE pos_after != 0) AS direction,

                    ANY_VALUE(snap_leverage) FILTER (WHERE snap_leverage IS NOT NULL)
                        AS hl_leverage,
                    ANY_VALUE(episode_worst_adverse_px) AS worst_adverse_px,

                    BOOL_OR(is_liquidation = TRUE) AS hl_was_liquidated,
                    BOOL_OR(direction = 'Auto-Deleveraging') AS hl_was_adl,
                    ANY_VALUE(episode_liq_px) AS hl_liq_px,

                    SUM(COALESCE(realized_pnl, 0)) AS hl_realized_pnl_usd
                FROM src
                GROUP BY 1, 2, 3
                HAVING open_time_ms < close_time_ms
                    AND open_px IS NOT NULL
                    AND close_px IS NOT NULL
                    AND size_units > 0
                    AND direction IS NOT NULL
            )
            SELECT
                coin || ':' || address || ':' || CAST(episode_id AS VARCHAR) AS trade_id,
                coin,
                address,
                direction,
                open_time_ms,
                close_time_ms,
                open_px,
                close_px,
                size_units,
                size_units * open_px AS notional_at_entry_usd,
                CAST(hl_leverage AS INTEGER) AS hl_leverage,
                worst_adverse_px,
                CASE WHEN worst_adverse_px IS NOT NULL AND open_px > 0
                     THEN abs(open_px - worst_adverse_px) / open_px
                     ELSE NULL END AS worst_adverse_pct,
                hl_was_liquidated,
                hl_was_adl,
                hl_liq_px,
                hl_realized_pnl_usd,
                (close_time_ms - open_time_ms) / 1000.0 AS holding_seconds
            FROM agg
        )
        TO '{args.output}' (FORMAT 'parquet', COMPRESSION 'zstd')
    """)

    elapsed = time.time() - t0
    n = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{args.output}')"
    ).fetchone()[0]
    size_mb = args.output.stat().st_size / (1024 * 1024)

    logging.info("Done in %.1fs.  %s trades  →  %s (%.1f MB)",
                 elapsed, f"{n:,}", args.output, size_mb)

    print("\n=== Sample summary ===")
    print(con.sql(f"""
        SELECT
            coin,
            COUNT(*) AS n_trades,
            SUM(CAST(hl_was_liquidated AS INT)) AS n_hl_liquidated,
            ROUND(100.0 * SUM(CAST(hl_was_liquidated AS INT))/COUNT(*), 2) AS pct_hl_liq,
            SUM(CASE WHEN direction='long' THEN 1 ELSE 0 END) AS n_long,
            SUM(CASE WHEN direction='short' THEN 1 ELSE 0 END) AS n_short,
            ROUND(approx_quantile(worst_adverse_pct, 0.5) * 10000, 1)
                AS median_adverse_bps,
            ROUND(approx_quantile(worst_adverse_pct, 0.9) * 10000, 1)
                AS p90_adverse_bps,
            ROUND(approx_quantile(notional_at_entry_usd, 0.5), 0)
                AS median_notional_usd,
            ROUND(approx_quantile(notional_at_entry_usd, 0.99), 0)
                AS p99_notional_usd
        FROM read_parquet('{args.output}')
        GROUP BY coin
        ORDER BY coin
    """).df().to_string(index=False))

    print()
    print(f"Critical preview: at Paper 1000x with 5bps buffer, liquidation triggers")
    print(f"at adverse_pct ≥ 0.0005 (5 bps). Median adverse moves above are well")
    print(f"above that — expect HIGH liquidation rate in Paper.")


if __name__ == "__main__":
    sys.exit(main())