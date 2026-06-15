# Paper LP Simulation

Simulation pipeline for the **Paper** synthetic perpetual protocol on Hyperliquid. Replays 3.6 million real max-leverage trades through the Paper LP/staker/minting model across 27,360 parameter scenarios, producing publication-quality charts and tables for tokenomics analysis.

## What this does

Paper is a 1000x leverage exchange built on Hyperliquid. Every trader loss funds the LP pool; every trader win drains it. PAPER tokens are minted to losing traders, and stakers of those tokens earn fees from LP overflow.

This pipeline:

1. **Simulates** the full Paper LP lifecycle: LP balance, staker fees, PAPER minting (flat + decaying tail), queue/debt mechanics, and ADL scenarios
2. **Sweeps** 27,360 scenarios across 45 parameter combos, 4 flow levels, 38 start days, 2 ADL modes, and 2 emission models
3. **Generates** 60+ charts and summary tables for the tokenomics report

## Dataset

The simulation replays 3.6 million real max-leverage trades (BTC at 40x, ETH at 25x) from Hyperliquid, extracted from on-chain fills cross-referenced with HyperTracker position data.

**Download:** [max_lev_trades_v3.parquet (~325 MB)](https://1024terabox.com/s/1QhhqHDRDPiiPiFC2Wz-BcA)

Place it anywhere on disk and pass the path via `--trades`.

## Architecture

```
max_lev_trades_v3.parquet          3.6M real Hyperliquid trades
      |
      v
local_server.py                    Core simulation engine (load_trades, simulate)
      |
      +--> simulate_paper_lp.py    Single-run simulation (per-trade granularity)
      |
      +--> batch_simulate.py       Batch: 27,360 scenarios -> batch_results.csv
                |                              + batch_daily_*.csv (daily series)
                v
         Plotting scripts
         ├── plot_batch.py         Parameter sweep charts (01-08)
         ├── plot_yield.py         Yield & PAPER supply charts (09-14)
         ├── plot_extra.py         Volume, OI, distributions (15-19)
         ├── plot_emission.py      Emission model comparison (E01-E08)
         └── plot_figures.py       Publication figures (F04-F15 + tables)
```

## Key files

| File | Description |
|------|-------------|
| `paper_config.yaml` | All simulation parameters (leverage, mint curve, staker %, impact function) |
| `local_server.py` | Core simulation engine. Exports `load_trades()`, `simulate()`, `DEFAULTS` |
| `batch_simulate.py` | Runs all 27,360 scenarios in parallel, outputs batch CSVs |
| `simulate_paper_lp.py` | Single-run simulation with per-trade output (used for Lorenz/concentration charts) |
| `plot_figures.py` | Publication-quality figures for the tokenomics report |
| `run_all.py` | Orchestrator: runs batch simulation + all chart scripts in sequence |

## How to use

### Prerequisites

```bash
pip install numpy pandas matplotlib pyarrow pyyaml
```

### Quick start: generate charts from existing batch results

If you already have `batch_results.csv` and `batch_daily_*.csv` files (from a previous batch run):

```bash
# Publication figures (F04-F15 + summary tables)
python3 plot_figures.py

# Full chart suite
python3 run_all.py --trades /path/to/max_lev_trades_v3.parquet --skip-sim
```

Charts are saved to `charts/`.

### Full pipeline: batch simulation + charts

```bash
# Run everything (simulation + all charts)
python3 run_all.py --trades /path/to/max_lev_trades_v3.parquet --workers 8

# Or step by step:
python3 batch_simulate.py --trades /path/to/max_lev_trades_v3.parquet --workers 8
python3 plot_figures.py
```

The batch simulation takes ~30-60 minutes with 8 workers and produces:
- `batch_results.csv` (27,360 rows, 54 columns) — final metrics per scenario
- `batch_daily_*.csv` (27,360 rows, 290 day columns each) — daily time series for LP, PAPER supply, staker fees, tail progress, debt, queue, trader losses/wins

### Single-run simulation

For per-trade granularity (used by concentration/Lorenz charts):

```bash
python3 simulate_paper_lp.py \
  --trades /path/to/max_lev_trades_v3.parquet \
  --config paper_config.yaml \
  --output-dir sim_flow_1.00 \
  --sample-fraction 1.00
```

Outputs `paper_sim_trades.parquet` (3.6M rows with per-trade minting) and `paper_sim_state.parquet` (289 daily rows).

## Simulation model

### Core mechanics

- **Leverage**: All trades replayed at 1000x in Paper (vs 40x BTC / 25x ETH on Hyperliquid)
- **LP pool**: Starts at $0, grows from trader losses, capped at $5M
- **Staker fees**: 2% slice of non-liquidation losses while LP < $5M; 100% of overflow after LP hits cap
- **PAPER minting**: Flat 100 PAPER/$ while LP < $2M; decaying tail `r(H) = 100 * (120M / (120M + H))^2` after
- **Queue**: Trader wins exceeding LP balance are queued (FIFO) and paid when LP recovers
- **ADL**: Optional worst-case auto-deleveraging scenario

### Batch scenarios (27,360 total)

- **45 parameter combos**: 3 base rates x 3 BTC reference notionals x 5 ETH reference notionals
- **4 flow levels**: 25%, 50%, 75%, 100% of Hyperliquid's actual volume
- **38 start days**: Launch date sensitivity (day 0 through day 37)
- **2 ADL modes**: Off (base case) vs On (pessimistic)
- **2 emission models**: Base vs emission-based (volume-dependent)

### Key results (100% flow, default params)

| Metric | Value |
|--------|-------|
| Final PAPER supply | 8.616B |
| Cumulative staker fees | $265.1M |
| Annualized fee run-rate | $339M/yr |
| Tail progress | $281M |
| Canonical liq rates | BTC 80.0%, ETH 91.5% |
| LP time to $5M cap | 5 days |
| Day-0 cohort yield (20% staked) | $0.286 per token |
| Payback multiple (20% staked) | 28.6x of $0.01 mint cost |

## Generated charts

### Publication figures (`plot_figures.py`)

| Chart | Description |
|-------|-------------|
| F04 | PAPER inflation rate over time, by flow |
| F05 | Cumulative staker fees: base model vs emission-based |
| F05b | Cumulative PAPER supply: base model vs emission-based |
| F06 | Staker yield split: pre-cap vs post-cap overflow |
| F07 | Early window: daily emission peak vs cumulative staker fees (all flows) |
| F09 | Inflation-adjusted real yield per staked token (4 flows x 6 staked fractions) |
| F10 | Payback multiples vs $0.01 mint cost (4 flows x 6 staked fractions) |
| F11 | Lifetime staker yield by entry-day cohort (4 flows x 6 staked fractions) |
| F12 | Fee concentration Lorenz curve (all flows) |
| F13 | Equilibrium implied price at target annual yields (4 flows x 3 staked fractions) |
| F14 | NPV per staked token across discount rates (4 flows x 3 staked fractions) |
| F15 | Yield sensitivity to flow, ADL, and launch window |
| T09-T14 | Summary tables for all chart metrics |

### Batch charts (`plot_batch.py`, `plot_yield.py`, `plot_extra.py`)

40+ additional charts covering parameter sweeps, LP paths, debt analysis, daily volume/OI, P&L distributions, and more.
