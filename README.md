# Paper LP Simulation

Replays **3.6 million real max-leverage trades** from Hyperliquid through the **Paper** synthetic perpetual model, and shows what happens to the LP pool, the $PAPER token, and the traders.

Change the parameters, re-run, and see how the answers move.

## What Paper is

Paper is a 1000x leverage exchange built on Hyperliquid. Every trader loss funds the LP pool; every trader win drains it. $PAPER tokens are minted to losing traders, and stakers of those tokens earn fees from the LP's overflow. The interesting question is whether the LP stays solvent — and what the token is worth if it does.

This simulator answers both against real trade data rather than assumptions.

## Quick start

**1. Install dependencies**

```bash
pip3 install pandas numpy matplotlib pyyaml pyarrow
```

**2. Get the trade data**

The simulation replays 3.6M real max-leverage trades (BTC at 40x, ETH at 25x), extracted from on-chain fills cross-referenced with HyperTracker position data.

**Download:** [max_lev_trades_v3.parquet (~325 MB)](https://1024terabox.com/s/1QhhqHDRDPiiPiFC2Wz-BcA)

Place it at `data/max_lev_trades_v3.parquet`, or keep it anywhere and pass `--trades /path/to/file.parquet`.

**3. Run it**

```bash
python3 run.py
```

That simulates at the parameters in `paper_config.yaml` and writes charts to `charts/`. Takes a few minutes.

## Changing parameters

Everything you'd want to tune lives in **`paper_config.yaml`**: leverage and bust buffer, the $PAPER mint curve (flat rate, threshold, tail decay), the staker/frontend fee split and LP cap, and the asymmetric impact curve (base rate, rate multiplier, position multiplier, reference notional, deadband).

Edit it, re-run `python3 run.py`, and compare the charts.

## Commands

```bash
python3 run.py                  # simulate at the configured parameters, build charts
python3 run.py --sweep          # also sweep scenarios (flow x launch day x ADL x
                                # emission = 608 runs) and build every chart. ~15 min.
python3 run.py --charts-only    # rebuild charts from existing results, no simulation
```

| Option | Meaning |
|---|---|
| `--trades PATH` | Trade dataset (default `data/max_lev_trades_v3.parquet`) |
| `--config PATH` | Parameter file (default `paper_config.yaml`) |
| `--workers N` | Parallel workers for the sweep (default: all cores) |
| `--full-sweep` | Also sweep the impact parameters — 27,360 scenarios instead of 608. Only useful if you want to explore impact-curve settings rather than use the published ones. |

Outputs land in `charts/`, plus `charts_emission/` and `charts_comparison/` when you sweep. A sweep also writes `batch_results.csv` (one row per scenario).

## What gets simulated

- **Leverage** — all trades replayed at 1000x in Paper (vs 40x BTC / 25x ETH on Hyperliquid)
- **LP pool** — starts at $0, grows from trader losses, capped at $5M
- **Fee split** — stakers 1% and the frontend 1% of every LP credit while the pool fills; once it caps, the 98% that would have grown the LP sweeps to stakers instead (stakers 99%, frontend 1%)
- **$PAPER minting** — flat 100 PAPER/$ while the LP is below $2M, then a decaying tail `r(H) = 100 · (120M / (120M + H))²`
- **Queue** — trader wins that exceed the LP balance are queued FIFO and paid as the LP recovers
- **ADL** — optional worst-case auto-deleveraging scenario
- **Asymmetric impact** — winning closes are haircut by
  `scale = (1 − base_rate) / (1 + 1/(move·rate_mult) + ref_notional/(move·pos_mult))`,
  applied to the move net of a **deadband** (half the CLOB spread, 0.2bps — so sub-spread jitter retains nothing).

  The shipped values are Rollbit's published parameters: `base_rate 0.1`, `rate_multiplier 15000`, `rate_exponent 1`, `position_multiplier 1,384,615,385` (BTC) / `923,076,923` (ETH) — Rollbit quotes those as 1384.615 / 923.077 in $-millions. `reference_notional` is fixed at `100000`: Rollbit takes position size as an input, but fixing it resists sybil splitting (punishing below $100k, favorable above).

### Sweep axes (`--sweep`)

4 flow levels (25/50/75/100% of Hyperliquid's actual volume) × 38 launch days × 2 ADL modes × 2 emission models = **608 scenarios**.

## Some results at the shipped parameters

At 100% flow, launched day 0:

| Metric | Value |
|---|---|
| Scenarios ending solvent | 100% of 608 |
| Scenarios never taking on debt | 81.2% |
| Largest debt at any moment | $61,974 (resolved same day) |
| LP time to the $5M cap | 5 days |
| Final $PAPER supply | 8.63B |
| Cumulative staker fees | $248.1M |
| Liquidation rate | BTC 80.05%, ETH 91.49% |
| What a winner keeps on a 1% move | BTC 88.6%, ETH 88.3% |

The figures built from these runs are in `results/article_figures/`.

## Repository layout

```
run.py                  the only entry point
paper_config.yaml       every parameter you can change
data/                   put the trade dataset here
pipeline/               simulation engine and chart generators
results/
  article_figures/      figures built from these runs
  chapter1_numbers.md   the full result set, with methodology notes
charts/                 output (regenerated on each run)
```

`pipeline/` holds the engine (`local_server.py`, `simulate_paper_lp.py`, `batch_simulate.py`) and seven chart generators covering LP and debt paths, per-coin BTC/ETH breakdowns, $PAPER supply and staker yield, emission-model comparisons, and the publication figures. `run.py` drives all of them; you shouldn't need to call them directly.

## Caveats

- Replaying historical trades assumes traders behave the same way under Paper's rules as they did under Hyperliquid's. They wouldn't, exactly — a 1000x venue with an impact haircut attracts different behaviour.
- Flow levels below 100% are modelled by uniform random sampling of trades, which preserves the size distribution but not any correlation between trader identity and volume.
- The ADL mode is a worst-case bound, not a forecast.
