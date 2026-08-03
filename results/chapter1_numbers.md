# Results

Every number below comes from the simulation at the parameters shipped in `paper_config.yaml`:

`base_rate 0.10 · rate_multiplier 15000 · rate_exponent 1 · position_multiplier BTC 1,384,615,385 / ETH 923,076,923 ($-notional; Rollbit publishes 1384.615 / 923.077 in $-millions) · reference_notional 100,000 · deadband 0.2bps (half CLOB spread) · stakerPct 0.01 · frontendPct 0.01 · lpCapUsd 5,000,000 · bufferBps 5 · maxOpenUsd 10,000,000`

Scenario grid: 4 flow levels × 38 launch days × 2 ADL modes × 2 emission models = **608 scenarios**, in `batch_results_official.csv`. Reproduce with `python3 run.py --sweep`.

---

## 1. The impact curve

Share of a raw gain the trader keeps (from the formula, no simulation needed):

| Move | BTC | ETH |
|---|---|---|
| 0.05% | 67.0% | 63.3% |
| 0.5% | 87.2% | 86.6% |
| 1% | 88.6% | 88.3% |
| 2% | 89.3% | 89.1% |
| 5% | 89.7% | 89.7% |
| 10% | 89.9% | 89.8% |
| 20% | 89.9% | 89.9% |

- Move at which the trader keeps **25%**: BTC 0.0095%, ETH 0.0110%. To keep **50%**: BTC 0.0235%, ETH 0.0281%.
- `referenceNotional / positionMultiplier`: BTC 7.222e-5, ETH 1.083e-4 → **ETH:BTC = 1.500**
- The **deadband applies to both coins** — `net_move = move − deadband` is coin-agnostic, so any winning move below **0.2bps** retains **0.00%** for ETH exactly as for BTC. ETH at 0.05% keeps 66.67% without the deadband vs **63.32%** with it.
- Over 1%–20% moves the trader keeps **88.6–89.9% (BTC)** and **88.3–89.9% (ETH)** — a haircut of roughly **10–11%**.

## 2. Solvency and debt (608 scenarios)

- Share ending solvent (`debtRemaining == 0`): **100.0%** · max `debtRemaining` **$0.00**
- Scenarios that never take on debt at all: **494/608 = 81.2%**
  - ADL off / base 81.6% (124/152) · ADL off / emission 81.6% (124/152) · ADL on / base 80.9% (123/152) · ADL on / emission 80.9% (123/152)
- Largest debt at any moment: **$61,974.43** — 25% flow, launch d91, ADL off, base model
- Longest queue: **70 trades**, same scenario
- Debt events by flow: 25% → 46, 50% → 24, 75% → 16, 100% → 28
- All debt resolves **within the same simulation day** (max `avgQueueWait` = 0.000 days)
- Scenarios never reaching the $5M cap: 25% flow → **4**, all other flows → 0.
  Those four are all **launch date d259** — one date, repeated across emission {off,on} × ADL {off,on} at 25% flow, with `lpMax` $4.20–4.24M.

## 3. Fill speed (base model, ADL off)

| Flow | d0 → $2M | d0 → $5M | worst → $2M | worst → $5M |
|---|---|---|---|---|
| 25% | 7d | 14d | 17d | 36d |
| 50% | 4d | 12d | 9d | 20d |
| 75% | 3d | 11d | 7d | 15d |
| 100% | 2d | 5d | 4d | 11d |

## 4. The trader side

| Flow | Base net (min/max) | Emission net (min/max) |
|---|---|---|
| 25% | −$64.2M / −$4.3M | −$46.8M / −$4.3M |
| 50% | −$127.6M / −$8.5M | −$76.2M / −$8.2M |
| 75% | −$192.1M / −$13.1M | −$99.2M / −$12.3M |
| 100% | −$256.0M / −$17.6M | −$118.2M / −$16.1M |

- At full flow launched d0: total volume **$350.0B**, implied posted margin **$350M**, **73.1¢ lost per $ of margin**
- Nothing leaks: finalLp $5.0M + stakers $248.1M + frontend $2.87M = **$256.0M** = −traderNet ✓

## 5. Liquidation rates

| Coin | n | Paper liq | HL liq | median adverse | payoff |
|---|---|---|---|---|---|
| BTC | 2,617,543 | **80.05%** | 7.82% | 0.222% | **11.2%** |
| ETH | 983,114 | **91.49%** | 6.09% | 0.410% | 6.7% |

Liquidation and payoff don't sum to 100% — here is the rest:

| Coin | liquidated | winners (payoff) | residual | residual breakdown |
|---|---|---|---|---|
| BTC | 80.05% | 11.22% | **8.73%** | 8.03% non-liq losers + 0.70% break-even |
| ETH | 91.49% | 6.66% | **1.85%** | 1.65% non-liq losers + 0.20% break-even |

The residual is trades that **closed at a loss but were never liquidated**, plus exact break-evens: the trader was underwater, but the worst adverse move never reached the 5bps bust line, so they exited with a partial loss instead of a wipeout. ETH's residual is smaller precisely because ETH liquidates more, leaving fewer partial-loss survivors. Every trade is exactly one of {liquidated, winner, non-liq loser, break-even}, so the three columns sum to 100.00%.

Note that the payoff rate is measured **after** the deadband: winning moves below ~0.2bps net to exactly $0, so they no longer count as a payoff.

## 6. $PAPER supply and fees

| Flow | PAPER base | PAPER emission | stakers base | stakers emission | cost per PAPER |
|---|---|---|---|---|---|
| 25% | 4.59B | 3.72B | $58.5M | $41.3M | $0.0154 |
| 50% | 6.67B | 5.08B | $121.2M | $70.3M | $0.0212 |
| 75% | 7.86B | 5.87B | $184.9M | $93.1M | $0.0270 |
| 100% | 8.63B | 6.40B | $248.1M | $111.9M | $0.0328 |

**Emission schedule (100% flow, base, d0)**

- Share of lifetime supply minted in the first **90 days: 72.6%** · $2M threshold crossed **d2** · $5M cap hit **d5**
- Biggest single minting day: **d13, 259M PAPER**

**Front-loading (100% flow, base)**

- Marginal mint cost **doubles** ($0.01 → $0.02) when the tail high-water mark `H` reaches **$49.7M** = `S·(√2−1)` with `S = $120M`. This is deterministic and flow-independent.
- The tail HWM crosses $49.7M on **day 30**, by which point **43.6%** of lifetime supply is already minted.
- Final tail HWM at 100% flow: **$280.6M**.

**Marginal mint cost at the end of the window** (cost = 1/rate at the final tail HWM)

| Flow | final tail HWM | marginal cost |
|---|---|---|
| 25% | $68.6M | **$0.0247 (2.5¢)** |
| 50% | $139.1M | **$0.0466 (4.7¢)** |
| 75% | $209.7M | **$0.0755 (7.6¢)** |
| 100% | $280.6M | **$0.1114 (11.1¢)** |

**Share of lifetime staker fees earned before the LP caps**

| Flow | cap hit | pre-cap fees | share |
|---|---|---|---|
| 25% | d14 | $0.32M / $58.5M | **0.54%** |
| 50% | d12 | $2.92M / $121.2M | **2.41%** |
| 75% | d11 | $5.40M / $184.9M | **2.92%** |
| 100% | d5 | $0.96M / $248.1M | **0.39%** |

100% flow has the lowest pre-cap share because it caps fastest (d5), so the fewest fees accrue before the switch.

**Annualised inflation** (daily mint ÷ supply × 365, 7-day smoothed)

| Flow | 25% | 50% | 75% | 100% |
|---|---|---|---|---|
| Final annualised inflation | **54.0%** | **37.9%** | **29.6%** | **23.4%** |

## 7. Staker economics

Real-yield, payback and cohort charts use staked shares **{10%, 20%, 50%, 80%}**; equilibrium and NPV use **{20%, 30%, 50%}**.

- **Cumulative fees per token, day-0 staker** (100% flow): 10% staked → $0.531, 20% → $0.266, 50% → $0.106, 80% → $0.066
- **Payback**, as a multiple of the 1¢ mint cost: least favourable **3.3×** (25% flow / 80% staked), central **26.6×** (100% / 20%), most favourable **53.1×** (100% / 10%)
- **Yield by entry-day cohort** (100% flow / 20% staked): d0 **$0.266**, d30 **$0.157**, d90 **$0.095**, d180 **$0.046**, d270 **$0.006** — a **42.1×** advantage for day 0 over day 270 (5.8× over day 180)
- **Fee concentration** (100% flow): the first 5% of losers to arrive generate **39.0%** of all staker fees, the first 10% → **62.7%**, the first 25% → **85.4%**
- **Annual fee run-rate and implied price** (post-cap fees × 365, at 20% staked):

  | Flow | annual fee | implied price @20% yield | implied price @50% yield |
  |---|---|---|---|
  | 25% | $77.2M | $0.420 | $0.168 |
  | 50% | $155.8M | $0.584 | $0.234 |
  | 75% | $235.7M | $0.750 | $0.300 |
  | 100% | $317.6M | $0.921 | $0.368 |

  Price scales linearly with the yield target, so the @50% column is 0.4× the @20% column.

- **Fee run-rate per staked token** (post-cap, annualised)

  | Flow | 20% staked | 50% staked |
  |---|---|---|
  | 25% | $0.084/yr | $0.034/yr |
  | 100% | $0.184/yr | $0.074/yr |

- **NPV per token** (@20% discount): from $0.921 (100% flow / 20% staked) down to $0.168 (25% / 50%) — the floor stays above the 1¢ mint cost.

---

## Methodology note: "cumulative fees per token for a day-0 staker"

The per-token yield chart plots two lines, and the distinction matters:

- **Naïve** (dashed) = total staker fees ÷ **final** staked supply.
- **Day-0 staker** (solid, the number reported above) = `Σ_t [ daily_fee_t / (share × supply_t) ]` — each day's fee divided by **that day's** supply, then summed.

The solid line is deliberately **not** described as inflation-adjusted or "real". The simulation has no price series, so there is no deflator anywhere in it. The only thing separating the two lines is a constant **+84.6% gap** (identical at every staked share) that comes from valuing early fees against the smaller early supply — a supply-dilution/time-weighting effect, not an inflation adjustment.

Nor does the staked-share axis carry any adjustment: `yield × staked_share = 0.0531` is constant across 10/20/50/80% staked, so per-token yield is exactly proportional to `1/staked_share`. That is pure fee-splitting — more stakers dividing the same pool.

What the solid line genuinely measures is the per-token cash accrued by someone who stakes on day 0 and holds, which is why it equals the d0 cohort value exactly ($0.266 at 100% flow / 20% staked).
