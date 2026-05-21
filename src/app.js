const DAY_MS = 86_400_000;
const SIM_DAYS = 290;
const BASE_TRADE_COUNT = 12_000;
const START_DATE = Date.UTC(2025, 7, 1);
const REAL_ADL = {70:857,71:10,72:6,73:7,74:6,75:1,76:7,77:3,80:1,81:3,83:1,86:1,88:1,89:1,90:2,93:2,94:2,95:1,96:1,103:2,104:1,105:1,106:1,108:1,109:1,112:2,122:3,123:2,125:1,126:1,132:2,137:1,140:1,143:1,166:1,170:1,183:1,188:1,189:2,191:1,192:1,194:1,207:1,212:1,216:1,227:1,231:1,238:1,240:1,246:1,259:1,261:1,269:1,271:1,272:1,273:1,278:1,280:1,283:1,286:1,287:3,288:2};

const COLORS = {
  lp: "#1769e0",
  paper: "#d64550",
  stakers: "#18936a",
  bars: "#54708c",
  liq: "#c43138",
  win: "#12a6a3",
  loss: "#e05f2b",
  net: "#6a4bb8",
  btc: "#f7931a",
  eth: "#627eea",
  tail: "#9467bd",
  cost: "#8c6239",
  total: "#15181d",
  phase: "#4c2882",
  grid: "#dfe5ec",
  axis: "#8994a1",
  text: "#303946",
  muted: "#677280",
  threshold: "#59636f",
  cap: "#9a6b16",
};

const chartZoom = new Map();
const chartMeta = new Map();
let chartTooltip = null;
let panState = null;

const DEFAULTS = {
  leverage: 1000,
  bufferBps: 5,
  maxOpenUsd: 10_000_000,
  initialLpUsd: 0,
  flatRate: 100,
  thresholdUsd: 2_000_000,
  tailScaleUsd: 120_000_000,
  stakerPct: 0.1,
  lpCapUsd: 5_000_000,
  stakedFraction: 1,
  sampleFraction: 1,
  seed: 42,
  volatility: 1,
  volumeScale: 1,
  btcBaseRate: 0.05,
  btcRateMultiplier: 1000,
  btcPositionMultiplier: 10_000_000,
  btcReferenceNotional: 100_000,
  ethBaseRate: 0.05,
  ethRateMultiplier: 1000,
  ethPositionMultiplier: 10_000_000,
  ethReferenceNotional: 50_000,
};

const CONTROL_GROUPS = [
  {
    title: "Trade side",
    controls: [
      {
        id: "bufferBps",
        label: "Bust buffer",
        min: 0,
        max: 9.5,
        step: 0.1,
        suffix: " bps",
        help: "Cushion subtracted from the theoretical margin before liquidation. More buffer means earlier liquidations; less buffer lets traders survive more adverse movement.",
      },
    ],
  },
  {
    title: "Mint + stakers",
    controls: [
      {
        id: "tailScaleUsd",
        label: "Tail decay scale",
        min: 5_000_000,
        max: 300_000_000,
        step: 5_000_000,
        format: formatUsdShort,
        help: "Scale S in the post-threshold mint curve. Higher values make PAPER issuance decay more slowly; lower values make PAPER scarce sooner.",
      },
      {
        id: "stakerPct",
        label: "Staker cut",
        min: 0,
        max: 50,
        step: 1,
        factor: 100,
        format: formatPct,
        help: "Percentage of each LP-positive event routed to stakers. Higher values mean more staker fees and slower LP growth.",
      },
      {
        id: "stakedFraction",
        label: "Assumed staked",
        min: 5,
        max: 100,
        step: 5,
        factor: 100,
        format: formatPct,
        help: "Assumed share of PAPER supply that is staked. It does not change the simulation; it only changes fees per staked PAPER.",
      },
    ],
  },
  {
    title: "Flow",
    controls: [
      {
        id: "sampleFraction",
        label: "Flow sampled",
        min: 5,
        max: 100,
        step: 5,
        factor: 100,
        format: formatPct,
        help: "Percentage of generated trade flow included in the run. Lower flow means fewer trades and is useful for modeling partial adoption.",
      },
      {
        id: "seed",
        label: "Seed",
        min: 1,
        max: 9999,
        step: 1,
        integer: true,
        help: "Changes the synthetic trade flow reproducibly. The same seed produces the same base scenario.",
      },
    ],
  },
  {
    title: "Impact BTC",
    controls: [
      {
        id: "btcBaseRate",
        label: "Base rate",
        min: 0,
        max: 30,
        step: 1,
        factor: 100,
        format: formatPct,
        help: "Base haircut for winning BTC closes. Higher values mean winning traders receive less and the LP pays less.",
      },
      {
        id: "btcRateMultiplier",
        label: "Rate multiplier",
        min: 50,
        max: 5000,
        step: 50,
        help: "Controls how much payout improves when the price move is large. Higher values mean less haircut for real directional moves.",
      },
      {
        id: "btcPositionMultiplier",
        label: "Position multiplier",
        min: 1_000_000,
        max: 50_000_000,
        step: 500_000,
        format: formatUsdShort,
        help: "Controls the size penalty for BTC positions. Higher values mean large positions receive less haircut.",
      },
      {
        id: "btcReferenceNotional",
        label: "Reference notional",
        min: 10_000,
        max: 1_000_000,
        step: 10_000,
        format: formatUsdShort,
        help: "BTC reference scale in the impact formula. Higher values create more haircut for the same move and size.",
      },
    ],
  },
  {
    title: "Impact ETH",
    controls: [
      {
        id: "ethBaseRate",
        label: "Base rate",
        min: 0,
        max: 30,
        step: 1,
        factor: 100,
        format: formatPct,
        help: "Base haircut for winning ETH closes. Higher values mean winning traders receive less and the LP pays less.",
      },
      {
        id: "ethRateMultiplier",
        label: "Rate multiplier",
        min: 50,
        max: 5000,
        step: 50,
        help: "Controls how much payout improves when the price move is large. Higher values mean less haircut for real directional moves.",
      },
      {
        id: "ethPositionMultiplier",
        label: "Position multiplier",
        min: 1_000_000,
        max: 50_000_000,
        step: 500_000,
        format: formatUsdShort,
        help: "Controls the size penalty for ETH positions. Higher values mean large positions receive less haircut.",
      },
      {
        id: "ethReferenceNotional",
        label: "Reference notional",
        min: 10_000,
        max: 1_000_000,
        step: 10_000,
        format: formatUsdShort,
        help: "ETH reference scale in the impact formula. Higher values create more haircut for the same move and size.",
      },
    ],
  },
];

const FIXED_PARAMS = [
  {
    id: "leverage",
    label: "Paper leverage",
    value: () => `${DEFAULTS.leverage}x`,
    detail: "All positions are replayed at fixed leverage.",
  },
  {
    id: "maxOpenUsd",
    label: "Max open notional",
    value: () => formatUsdShort(DEFAULTS.maxOpenUsd),
    detail: "Opening notional cap per position.",
  },
  {
    id: "initialLpUsd",
    label: "Initial LP",
    value: () => formatUsdShort(DEFAULTS.initialLpUsd),
    detail: "LP balance before the first trade.",
  },
  {
    id: "flatRate",
    label: "Flat mint rate",
    value: () => `${DEFAULTS.flatRate} PAPER/$`,
    detail: "Fixed PAPER issuance before the threshold.",
  },
  {
    id: "thresholdUsd",
    label: "Flat threshold",
    value: () => formatUsdShort(DEFAULTS.thresholdUsd),
    detail: "Flat issuance applies up to this level.",
  },
  {
    id: "lpCapUsd",
    label: "LP excess cap",
    value: () => formatUsdShort(DEFAULTS.lpCapUsd),
    detail: "Above this cap, excess goes to stakers.",
  },
  {
    id: "volatility",
    label: "Volatility",
    value: () => `${DEFAULTS.volatility}x`,
    detail: "Fixed price-move multiplier.",
  },
];

const EDITABLE_IDS = CONTROL_GROUPS.flatMap((group) =>
  group.controls.map((control) => control.id),
);

const controlsEl = document.querySelector("#controls");
const fixedParamsEl = document.querySelector("#fixedParams");
const kpisEl = document.querySelector("#kpis");
const statusText = document.querySelector("#statusText");
const pageTitle = document.querySelector("#pageTitle");
const dashboardPage = document.querySelector("#dashboardPage");
const methodologyPage = document.querySelector("#methodologyPage");
const dashboardLink = document.querySelector("#dashboardLink");
const methodologyLink = document.querySelector("#methodologyLink");
const resetBtn = document.querySelector("#resetBtn");
const seedBtn = document.querySelector("#seedBtn");
const shareBtn = document.querySelector("#shareBtn");

let params = clampParams({ ...DEFAULTS, ...readParamsFromUrl() });
let baseTrades = generateBaseTrades(params.seed);
let latestResult = null;
let updateFrame = null;
let lastSeed = params.seed;
const inputRefs = new Map();

buildControls();
buildFixedParams();
wireActions();
routePage();
scheduleUpdate();

window.addEventListener("resize", debounce(() => {
  if (latestResult) render(latestResult);
}, 120));
window.addEventListener("hashchange", routePage);

function buildControls() {
  const fragment = document.createDocumentFragment();
  for (const group of CONTROL_GROUPS) {
    const section = document.createElement("section");
    section.className = "control-section";

    const heading = document.createElement("h3");
    heading.textContent = group.title;
    section.appendChild(heading);

    for (const control of group.controls) {
      const row = document.createElement("div");
      row.className = "control-row";

      const label = document.createElement("label");
      label.className = "control-label";
      label.setAttribute("for", `${control.id}-range`);

      const name = document.createElement("span");
      name.className = "label-main";
      name.textContent = control.label;

      const info = document.createElement("button");
      info.type = "button";
      info.className = "info-button";
      info.setAttribute("aria-label", `${control.label}: ${control.help}`);
      info.innerHTML = `<span aria-hidden="true">i</span><span class="tooltip" role="tooltip">${control.help}</span>`;
      name.appendChild(info);

      const output = document.createElement("output");
      output.className = "control-value";

      label.append(name, output);

      const inputWrap = document.createElement("div");
      inputWrap.className = "control-inputs";

      const range = document.createElement("input");
      range.type = "range";
      range.id = `${control.id}-range`;
      range.min = String(control.min);
      range.max = String(control.max);
      range.step = String(control.step ?? 1);

      const number = document.createElement("input");
      number.type = "number";
      number.id = `${control.id}-number`;
      number.min = String(control.min);
      number.max = String(control.max);
      number.step = String(control.step ?? 1);
      number.inputMode = "decimal";

      inputWrap.append(range, number);
      row.append(label, inputWrap);
      section.appendChild(row);

      inputRefs.set(control.id, { control, range, number, output });

      const syncFromView = (viewValue) => {
        const next = viewToInternal(control, viewValue);
        params[control.id] = next;
        syncControl(control.id);
        scheduleUpdate();
      };

      range.addEventListener("input", () => syncFromView(Number(range.value)));
      number.addEventListener("input", () => syncFromView(Number(number.value)));
    }

    fragment.appendChild(section);
  }
  controlsEl.appendChild(fragment);
  syncAllControls();
}

function buildFixedParams() {
  fixedParamsEl.innerHTML = FIXED_PARAMS.map((item) => `
    <div class="fixed-item">
      <div>
        <span class="fixed-label">${item.label}</span>
        <span class="fixed-detail">${item.detail}</span>
      </div>
      <strong>${item.value()}</strong>
    </div>
  `).join("");
}

function wireActions() {
  resetBtn.addEventListener("click", () => {
    params = { ...DEFAULTS };
    chartZoom.clear();
    syncAllControls();
    scheduleUpdate();
  });

  seedBtn.addEventListener("click", () => {
    params.seed = Math.floor(1000 + Math.random() * 8999);
    chartZoom.clear();
    syncControl("seed");
    scheduleUpdate();
  });

  shareBtn.addEventListener("click", async () => {
    replaceUrlFromState();
    try {
      await navigator.clipboard.writeText(window.location.href);
      flashStatus("Link copied");
      shareBtn.textContent = "Copied";
      window.setTimeout(() => {
        shareBtn.textContent = "Copy link";
      }, 1300);
    } catch {
      flashStatus("Link updated");
    }
  });
}

function routePage() {
  const showMethodology = window.location.hash === "#methodology";
  dashboardPage.hidden = showMethodology;
  methodologyPage.hidden = !showMethodology;
  pageTitle.textContent = showMethodology ? "Methodology" : "Parameter Dashboard";
  dashboardLink.classList.toggle("is-active", !showMethodology);
  methodologyLink.classList.toggle("is-active", showMethodology);
}

function syncAllControls() {
  for (const id of inputRefs.keys()) syncControl(id);
}

function syncControl(id) {
  const ref = inputRefs.get(id);
  if (!ref) return;
  const { control, range, number, output } = ref;
  const viewValue = internalToView(control, params[id]);
  const decimals = decimalsFor(control.step ?? 1);
  const valueText = control.integer ? String(Math.round(viewValue)) : trimNumber(viewValue, decimals);
  range.value = valueText;
  number.value = valueText;
  output.value = formatControlValue(control, params[id]);
}

function scheduleUpdate() {
  if (updateFrame) cancelAnimationFrame(updateFrame);
  updateFrame = requestAnimationFrame(() => {
    updateFrame = null;
    params = clampParams(params);
    if (Math.round(params.seed) !== Math.round(lastSeed)) {
      baseTrades = generateBaseTrades(Math.round(params.seed));
      lastSeed = Math.round(params.seed);
    }
    const result = simulate(params, baseTrades);
    latestResult = result;
    render(result);
    replaceUrlFromState();
  });
}

function render(result) {
  renderKpis(result);
  renderSubtitles(result);
  drawLpChart(document.querySelector("#lpChart"), result);
  drawLpSymlogChart(document.querySelector("#lpSymlogChart"), result);
  drawLineChart(document.querySelector("#paperChart"), {
    series: [{ name: "PAPER", color: COLORS.paper, values: result.state.map((d) => d.paperSupply), fill: true }],
    dates: result.state.map((d) => d.date),
    yFormatter: formatCompact,
    zero: true,
  });
  drawLineChart(document.querySelector("#stakerChart"), {
    series: [{ name: "Stakers", color: COLORS.stakers, values: result.state.map((d) => d.stakers), fill: true }],
    dates: result.state.map((d) => d.date),
    yFormatter: formatUsdShort,
    zero: true,
  });
  drawActivityChart(document.querySelector("#activityChart"), result);
  drawAdlEventsChart(document.querySelector("#adlChart"), result);
  drawPnlChart(document.querySelector("#pnlChart"), result);
  drawImpactChart(document.querySelector("#impactChart"), result);
  drawTailChart(document.querySelector("#tailChart"), result);
  drawMintRateChart(document.querySelector("#mintRateChart"), result);
  drawCostChart(document.querySelector("#costChart"), result);
  drawFeesChart(document.querySelector("#feesChart"), result);
  drawVolumeChart(document.querySelector("#volumeChart"), result);
  drawOpenInterestChart(document.querySelector("#oiChart"), result);
  drawCoinContributionChart(document.querySelector("#coinContributionChart"), result);
  drawPhaseChart(document.querySelector("#phaseChart"), result);
  drawLpDistributionCharts(result);
  drawNotionalDistributionChart(document.querySelector("#notionalDistChart"), result);
  drawMintCurveChart(document.querySelector("#mintCurveChart"), result);
  flashStatus("Updated");
}

function renderKpis(result) {
  const items = [
    { label: "Trades", value: formatCompact(result.stats.nTrades), note: `${formatPct(result.params.sampleFraction)} flow sampled` },
    { label: "Paper liq", value: formatPct(result.stats.liqPct / 100), note: `${formatCompact(result.stats.nLiquidated)} positions` },
    { label: "Final LP", value: formatUsdShort(result.stats.finalLp), note: `cap ${formatUsdShort(result.params.lpCapUsd)}` },
    { label: "PAPER supply", value: formatCompact(result.stats.finalPaper), note: `${formatNumber(result.stats.marginalMintRate)} PAPER/$ marginal` },
    { label: "Stakers", value: formatUsdShort(result.stats.finalStakers), note: `${formatUsdSmall(result.stats.feesPerStakedPaper)} / staked PAPER` },
    { label: "Trader net", value: formatUsdShort(result.stats.traderNet), note: result.stats.traderNet >= 0 ? "net winner" : "net loser" },
    { label: "LP gained", value: formatUsdShort(result.stats.lpGained), note: "losers + liqs" },
    { label: "LP paid", value: formatUsdShort(result.stats.lpLost), note: "winning closes" },
  ];

  kpisEl.innerHTML = items.map((item) => `
    <article class="kpi">
      <span class="kpi-label">${item.label}</span>
      <span class="kpi-value">${item.value}</span>
      <span class="kpi-note">${item.note}</span>
    </article>
  `).join("");
}

function renderSubtitles(result) {
  const toleranceBps = result.stats.tolerance * 10_000;
  document.querySelector("#lpSubtitle").textContent =
    `${formatUsdShort(result.stats.lpMin)} min / ${formatUsdShort(result.stats.lpMax)} max`;
  document.querySelector("#lpSymlogSubtitle").textContent =
    "same LP path with small early moves expanded";
  document.querySelector("#paperSubtitle").textContent =
    `${formatCompact(result.stats.finalPaper)} final supply`;
  document.querySelector("#stakerSubtitle").textContent =
    `${formatUsdSmall(result.stats.feesPerStakedPaper)} fees per staked PAPER`;
  document.querySelector("#activitySubtitle").textContent =
    `${formatNumber(toleranceBps)} bps bust tolerance`;
  document.querySelector("#adlSubtitle").textContent =
    `${formatCompact(Math.max(...result.daily.map((d) => d.nAdl), 0))} max daily events`;
  document.querySelector("#pnlSubtitle").textContent =
    `${formatUsdShort(result.stats.traderLoss)} lost / ${formatUsdShort(result.stats.traderWin)} won`;
  document.querySelector("#impactSubtitle").textContent =
    `${formatPct(result.params.btcBaseRate)} BTC base / ${formatPct(result.params.ethBaseRate)} ETH base`;
  document.querySelector("#tailSubtitle").textContent =
    `${formatUsdShort(result.stats.tailProgress)} tail progress`;
  document.querySelector("#mintRateSubtitle").textContent =
    `${formatNumber(result.stats.marginalMintRate)} PAPER/$ marginal`;
  document.querySelector("#costSubtitle").textContent =
    `${formatUsdSmall(result.stats.costPerPaper)} cumulative trader loss per PAPER`;
  document.querySelector("#feesSubtitle").textContent =
    `${formatUsdSmall(result.stats.feesPerStakedPaper)} per staked PAPER`;
  document.querySelector("#volumeSubtitle").textContent =
    `${formatUsdShort(result.stats.totalVolume)} opened notional`;
  document.querySelector("#oiSubtitle").textContent =
    `${formatUsdShort(result.stats.maxOi)} max end-of-day OI`;
  document.querySelector("#coinContributionSubtitle").textContent =
    `BTC ${formatUsdShort(result.stats.finalBtcLp)} / ETH ${formatUsdShort(result.stats.finalEthLp)}`;
  document.querySelector("#phaseSubtitle").textContent =
    `${result.state.length} daily protocol states`;
  document.querySelector("#lpGainDistSubtitle").textContent =
    `${formatCompact(result.stats.nLpGainTrades)} LP-positive trades`;
  document.querySelector("#lpLossDistSubtitle").textContent =
    `${formatCompact(result.stats.nLpLossTrades)} LP-negative trades`;
  document.querySelector("#notionalDistSubtitle").textContent =
    `${formatUsdShort(result.params.maxOpenUsd)} Paper opening cap`;
  document.querySelector("#mintCurveSubtitle").textContent =
    `flat ${result.params.flatRate} PAPER/$, S ${formatUsdShort(result.params.tailScaleUsd)}`;
}

function simulate(rawParams, trades) {
  const p = clampParams(rawParams);
  const byDay = Array.from({ length: SIM_DAYS }, () => []);
  const preparedTrades = [];
  const oiBtcDelta = Array(SIM_DAYS + 1).fill(0);
  const oiEthDelta = Array(SIM_DAYS + 1).fill(0);
  const daily = Array.from({ length: SIM_DAYS }, (_, day) => ({
    day,
    date: new Date(START_DATE + day * DAY_MS),
    nTrades: 0,
    nLiquidated: 0,
    liqPct: 0,
    volume: 0,
    volumeBtc: 0,
    volumeEth: 0,
    paperVolume: 0,
    traderLoss: 0,
    traderWin: 0,
    traderNet: 0,
    btcLp: 0,
    ethLp: 0,
    oiBtc: 0,
    oiEth: 0,
    oiTotal: 0,
    nAdl: 0,
  }));

  for (const trade of trades) {
    if (trade.sampleKey > p.sampleFraction) continue;
    const notionalAtEntry = trade.notional * p.volumeScale;
    const paperNotional = Math.min(notionalAtEntry, p.maxOpenUsd);
    const prepared = { ...trade, notionalAtEntry, paperNotional };
    preparedTrades.push(prepared);
    byDay[trade.closeDay].push(prepared);

    const openRow = daily[trade.openDay];
    openRow.volume += notionalAtEntry;
    openRow.paperVolume += paperNotional;
    if (trade.coin === "BTC") {
      openRow.volumeBtc += notionalAtEntry;
      oiBtcDelta[trade.openDay] += paperNotional;
      oiBtcDelta[Math.min(SIM_DAYS, trade.closeDay + 1)] -= paperNotional;
    } else {
      openRow.volumeEth += notionalAtEntry;
      oiEthDelta[trade.openDay] += paperNotional;
      oiEthDelta[Math.min(SIM_DAYS, trade.closeDay + 1)] -= paperNotional;
    }
  }

  let lpBalance = p.initialLpUsd;
  let paperTotal = 0;
  let stakersTotal = 0;
  let tailProgress = 0;
  let lpGained = 0;
  let lpLost = 0;
  let traderLoss = 0;
  let traderWin = 0;
  let nTrades = 0;
  let nLiquidated = 0;
  let btcLp = 0;
  let ethLp = 0;
  let oiBtc = 0;
  let oiEth = 0;

  const state = [];
  const tolerance = Math.max(0, 1 / p.leverage - p.bufferBps / 10_000);
  const tailScaleSq = p.tailScaleUsd * p.tailScaleUsd;

  for (let day = 0; day < SIM_DAYS; day += 1) {
    const row = daily[day];

    for (const trade of byDay[day]) {
      nTrades += 1;
      row.nTrades += 1;

      const { notionalAtEntry, paperNotional } = trade;
      const margin = paperNotional / p.leverage;
      const closeMovePct = trade.closeMovePct * p.volatility;
      const adversePct = Math.abs(trade.adversePct * p.volatility);
      const paperLiquidated = adversePct >= tolerance;
      const rawPnl = closeMovePct * paperNotional;
      let lpEventGain = 0;
      let userOutcome = 0;

      if (paperLiquidated) {
        lpEventGain = margin;
        userOutcome = -margin;
        nLiquidated += 1;
        row.nLiquidated += 1;
      } else if (rawPnl >= 0) {
        const scale = impactScale(trade.coin, Math.abs(closeMovePct), p);
        const adjusted = rawPnl * scale;
        lpEventGain = -adjusted;
        userOutcome = adjusted;
      } else {
        lpEventGain = -rawPnl;
        userOutcome = rawPnl;
      }

      let lpDelta = lpEventGain;
      let stakersEvent = 0;

      if (lpEventGain > 0) {
        const stakersCut = lpEventGain * p.stakerPct;
        let lpGainAfterCut = lpEventGain - stakersCut;
        let excess = 0;

        if (lpBalance >= p.lpCapUsd) {
          excess = lpGainAfterCut;
          lpGainAfterCut = 0;
        } else if (lpBalance + lpGainAfterCut > p.lpCapUsd) {
          excess = lpBalance + lpGainAfterCut - p.lpCapUsd;
          lpGainAfterCut -= excess;
        }

        stakersEvent = stakersCut + excess;
        const lpPre = lpBalance;
        lpBalance += lpGainAfterCut;
        lpDelta = lpGainAfterCut;

        if (lpGainAfterCut > 0) {
          let flatPart = 0;
          let tailPart = 0;
          if (lpPre < p.thresholdUsd) {
            if (lpBalance <= p.thresholdUsd) {
              flatPart = lpGainAfterCut;
            } else {
              flatPart = p.thresholdUsd - lpPre;
              tailPart = lpBalance - p.thresholdUsd;
            }
          } else {
            tailPart = lpGainAfterCut;
          }

          paperTotal += flatPart * p.flatRate;
          if (tailPart > 0) {
            const newTail = tailProgress + tailPart;
            paperTotal += p.flatRate * tailScaleSq * (
              1 / (p.tailScaleUsd + tailProgress) - 1 / (p.tailScaleUsd + newTail)
            );
            tailProgress = newTail;
          }
        }
        stakersTotal += stakersEvent;
        lpGained += Math.max(0, lpDelta);
      } else {
        lpBalance += lpEventGain;
        lpLost += -lpEventGain;
      }

      if (trade.coin === "BTC") btcLp += lpDelta;
      else ethLp += lpDelta;

      trade.lpDelta = lpDelta;
      trade.userOutcome = userOutcome;
      trade.paperLiquidated = paperLiquidated;
      trade.paperMargin = margin;

      if (userOutcome < 0) {
        traderLoss += -userOutcome;
        row.traderLoss += -userOutcome;
      } else {
        traderWin += userOutcome;
        row.traderWin += userOutcome;
      }
    }

    row.liqPct = row.nTrades ? (100 * row.nLiquidated) / row.nTrades : 0;
    row.traderNet = traderWin - traderLoss;
    row.btcLp = btcLp;
    row.ethLp = ethLp;
    row.nAdl = REAL_ADL[day] ?? 0;
    oiBtc += oiBtcDelta[day];
    oiEth += oiEthDelta[day];
    row.oiBtc = oiBtc;
    row.oiEth = oiEth;
    row.oiTotal = oiBtc + oiEth;

    state.push({
      day,
      date: row.date,
      lpBalance,
      paperSupply: paperTotal,
      stakers: stakersTotal,
      tailProgress,
      btcLp,
      ethLp,
    });
  }

  const finalLp = lpBalance;
  const lpValues = state.map((d) => d.lpBalance);
  const marginalMintRate =
    finalLp < p.thresholdUsd
      ? p.flatRate
      : p.flatRate * (p.tailScaleUsd / (p.tailScaleUsd + tailProgress)) ** 2;
  const feesPerStakedPaper = stakersTotal / Math.max(1e-9, paperTotal * p.stakedFraction);
  const totalVolume = daily.reduce((sum, row) => sum + row.volume, 0);
  const maxOi = Math.max(...daily.map((row) => row.oiTotal), 0);
  const nLpGainTrades = preparedTrades.filter((trade) => trade.lpDelta > 0).length;
  const nLpLossTrades = preparedTrades.filter((trade) => trade.lpDelta < 0).length;
  const costPerPaper = traderLoss / Math.max(1e-9, paperTotal);

  return {
    params: p,
    state,
    daily,
    trades: preparedTrades,
    stats: {
      nTrades,
      nLiquidated,
      liqPct: nTrades ? (100 * nLiquidated) / nTrades : 0,
      finalLp,
      finalPaper: paperTotal,
      finalStakers: stakersTotal,
      tailProgress,
      tolerance,
      marginalMintRate,
      feesPerStakedPaper,
      costPerPaper,
      traderLoss,
      traderWin,
      traderNet: traderWin - traderLoss,
      lpGained,
      lpLost,
      totalVolume,
      maxOi,
      finalBtcLp: btcLp,
      finalEthLp: ethLp,
      nLpGainTrades,
      nLpLossTrades,
      lpMin: Math.min(...lpValues),
      lpMax: Math.max(...lpValues),
    },
  };
}

function impactScale(coin, movePct, p) {
  if (!Number.isFinite(movePct) || movePct <= 0) return 0;
  const prefix = coin === "BTC" ? "btc" : "eth";
  const baseRate = p[`${prefix}BaseRate`];
  const rateMultiplier = p[`${prefix}RateMultiplier`];
  const positionMultiplier = p[`${prefix}PositionMultiplier`];
  const referenceNotional = p[`${prefix}ReferenceNotional`];
  const term1 = 1 / (movePct * rateMultiplier);
  const term2 = referenceNotional / (movePct * positionMultiplier);
  return clamp((1 - baseRate) / (1 + term1 + term2), 0, 1);
}

function generateBaseTrades(seedValue) {
  const rand = mulberry32(Math.round(seedValue) || DEFAULTS.seed);
  const trades = [];
  for (let i = 0; i < BASE_TRADE_COUNT; i += 1) {
    const coin = rand() < 0.58 ? "BTC" : "ETH";
    const closeDay = clampInt(Math.floor(rand() * SIM_DAYS), 0, SIM_DAYS - 1);
    const holdingDays = Math.max(1, Math.min(35, Math.ceil(logNormal(rand, 5, 0.9))));
    const openDay = clampInt(closeDay - holdingDays, 0, SIM_DAYS - 1);
    const cycle = Math.sin((closeDay / SIM_DAYS) * Math.PI * 4);
    const trend = 0.0004 * cycle + (coin === "BTC" ? 0.00005 : -0.00002);
    const closeMovePct = randNormal(rand) * 0.004 + trend;
    const intratradeAdverse = logNormal(rand, 0.0012, 0.9);
    const closeAdverse = closeMovePct < 0
      ? Math.abs(closeMovePct) * (0.72 + rand() * 0.56)
      : Math.abs(closeMovePct) * rand() * 0.45;
    const adversePct = clamp(Math.max(intratradeAdverse, closeAdverse), 0.00002, 0.18);
    const medianNotional = coin === "BTC" ? 280_000 : 140_000;
    const notional = clamp(logNormal(rand, medianNotional, 1.35), 4_000, 90_000_000);

    trades.push({
      coin,
      openDay,
      closeDay,
      holdingDays,
      notional,
      closeMovePct,
      adversePct,
      sampleKey: rand(),
    });
  }
  return trades.sort((a, b) => a.closeDay - b.closeDay);
}

function drawLpChart(canvas, result) {
  drawLineChart(canvas, {
    series: [{ name: "LP", color: COLORS.lp, values: result.state.map((d) => d.lpBalance), fill: true }],
    dates: result.state.map((d) => d.date),
    yFormatter: formatUsdShort,
    zero: true,
    guides: [
      { value: result.params.thresholdUsd, color: COLORS.threshold, label: "flat threshold" },
      { value: result.params.lpCapUsd, color: COLORS.cap, label: "LP cap" },
    ],
  });
}

function drawLpSymlogChart(canvas, result) {
  drawSymlogLineChart(canvas, {
    series: [{ name: "LP", color: COLORS.lp, values: result.state.map((d) => d.lpBalance), fill: true }],
    dates: result.state.map((d) => d.date),
    yFormatter: formatUsdShort,
    guides: [
      { value: result.params.thresholdUsd, color: COLORS.threshold, label: "flat threshold" },
      { value: result.params.lpCapUsd, color: COLORS.cap, label: "LP cap" },
    ],
  });
}

function drawPnlChart(canvas, result) {
  drawLineChart(canvas, {
    series: [
      { name: "Loss", color: COLORS.loss, values: running(result.daily.map((d) => d.traderLoss)) },
      { name: "Win", color: COLORS.win, values: running(result.daily.map((d) => d.traderWin)) },
      { name: "Net", color: COLORS.net, values: result.daily.map((d) => d.traderNet) },
    ],
    dates: result.daily.map((d) => d.date),
    yFormatter: formatUsdShort,
    zero: true,
  });
}

function drawActivityChart(canvas, result) {
  const { ctx, width, height } = setupCanvas(canvas);
  const m = { left: 58, right: 54, top: 14, bottom: 34 };
  const plot = getPlot(width, height, m);
  const length = result.daily.length;
  const range = getVisibleRange(canvas, length);
  const visibleDaily = result.daily.slice(range.start, range.end + 1);
  const trades = visibleDaily.map((d) => d.nTrades);
  const liq = visibleDaily.map((d) => d.liqPct);
  const maxTrades = niceMax(Math.max(1, ...trades));
  const maxPct = Math.max(100, niceMax(Math.max(1, ...liq)));

  clearCanvas(ctx, width, height);
  drawGrid(ctx, plot, 0, maxTrades, formatCompact);

  drawAdlBands(ctx, plot, visibleDaily);

  const barW = Math.max(1, plot.w / trades.length - 1);
  trades.forEach((value, i) => {
    const x = plot.x + (i / trades.length) * plot.w;
    const y = mapY(value, 0, maxTrades, plot);
    ctx.fillStyle = "rgba(84, 112, 140, 0.68)";
    ctx.fillRect(x, y, barW, plot.y + plot.h - y);
  });

  drawSeriesPath(ctx, liq, {
    color: COLORS.liq,
    width: 2,
    plot,
    yMin: 0,
    yMax: maxPct,
  });

  drawAxes(ctx, plot);
  drawXTicks(ctx, plot, { dates: visibleDaily.map((d) => d.date) });

  ctx.fillStyle = COLORS.muted;
  ctx.font = "12px Inter, system-ui, sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= 4; i += 1) {
    const value = (maxPct / 4) * i;
    const y = mapY(value, 0, maxPct, plot);
    ctx.fillText(`${Math.round(value)}%`, width - 8, y);
  }
  registerInteractiveChart(canvas, {
    length,
    plot,
    visibleStart: range.start,
    visibleEnd: range.end,
    getTooltip: (index) => {
      const row = result.daily[index];
      return {
        title: formatDateFull(row.date),
        rows: [
          { color: COLORS.bars, label: "trades", value: formatCompact(row.nTrades) },
          { color: COLORS.liq, label: "liquidation rate", value: formatPct(row.liqPct / 100) },
          { color: COLORS.tail, label: "ADL events", value: formatCompact(row.nAdl) },
        ],
      };
    },
  });
}

function drawAdlEventsChart(canvas, result) {
  drawStackedBarChart(canvas, {
    dates: result.daily.map((d) => d.date),
    series: [
      { name: "ADL events", color: COLORS.tail, values: result.daily.map((d) => d.nAdl) },
    ],
    yFormatter: formatCompact,
  });
}

function drawImpactChart(canvas, result) {
  const movesBps = [1, 2, 5, 10, 25, 50, 100, 250, 500, 1000];
  const btc = movesBps.map((bps) => impactScale("BTC", bps / 10_000, result.params) * 100);
  const eth = movesBps.map((bps) => impactScale("ETH", bps / 10_000, result.params) * 100);
  drawIndexedChart(canvas, {
    labels: movesBps.map((x) => `${x}`),
    yMin: 0,
    yMax: 100,
    yFormatter: (v) => `${Math.round(v)}%`,
    xLabelEvery: 2,
    series: [
      { name: "BTC", color: COLORS.btc, values: btc },
      { name: "ETH", color: COLORS.eth, values: eth },
    ],
  });
}

function drawTailChart(canvas, result) {
  drawLineChart(canvas, {
    series: [{ name: "Tail HWM", color: COLORS.tail, values: result.state.map((d) => d.tailProgress), fill: true }],
    dates: result.state.map((d) => d.date),
    yFormatter: formatUsdShort,
    zero: true,
  });
}

function drawMintRateChart(canvas, result) {
  const p = result.params;
  const values = result.state.map((d) => (
    d.lpBalance < p.thresholdUsd
      ? p.flatRate
      : p.flatRate * (p.tailScaleUsd / (p.tailScaleUsd + d.tailProgress)) ** 2
  ));
  drawLineChart(canvas, {
    series: [{ name: "mint rate", color: COLORS.paper, values, fill: true }],
    dates: result.state.map((d) => d.date),
    yFormatter: (v) => `${formatNumber(v)} PAPER/$`,
    zero: true,
    guides: [{ value: p.flatRate, color: COLORS.threshold, label: "flat" }],
  });
}

function drawCostChart(canvas, result) {
  const loss = running(result.daily.map((d) => d.traderLoss));
  const values = result.state.map((d, i) => loss[i] / Math.max(1e-9, d.paperSupply));
  drawLineChart(canvas, {
    series: [{ name: "cost", color: COLORS.cost, values, fill: true }],
    dates: result.state.map((d) => d.date),
    yFormatter: formatUsdSmall,
    zero: true,
  });
}

function drawFeesChart(canvas, result) {
  const values = result.state.map((d) => (
    d.stakers / Math.max(1e-9, d.paperSupply * result.params.stakedFraction)
  ));
  drawLineChart(canvas, {
    series: [{ name: "fees", color: COLORS.stakers, values, fill: true }],
    dates: result.state.map((d) => d.date),
    yFormatter: formatUsdSmall,
    zero: true,
  });
}

function drawVolumeChart(canvas, result) {
  drawStackedBarChart(canvas, {
    dates: result.daily.map((d) => d.date),
    adl: result.daily.map((d) => d.nAdl),
    series: [
      { name: "BTC", color: COLORS.btc, values: result.daily.map((d) => d.volumeBtc) },
      { name: "ETH", color: COLORS.eth, values: result.daily.map((d) => d.volumeEth) },
    ],
    yFormatter: formatUsdShort,
  });
}

function drawOpenInterestChart(canvas, result) {
  drawStackedAreaChart(canvas, {
    dates: result.daily.map((d) => d.date),
    series: [
      { name: "BTC OI", color: COLORS.btc, values: result.daily.map((d) => d.oiBtc) },
      { name: "ETH OI", color: COLORS.eth, values: result.daily.map((d) => d.oiEth) },
    ],
    total: { name: "Total OI", color: COLORS.total, values: result.daily.map((d) => d.oiTotal) },
    yFormatter: formatUsdShort,
  });
}

function drawCoinContributionChart(canvas, result) {
  drawLineChart(canvas, {
    series: [
      { name: "BTC", color: COLORS.btc, values: result.state.map((d) => d.btcLp), fill: true },
      { name: "ETH", color: COLORS.eth, values: result.state.map((d) => d.ethLp), fill: true },
    ],
    dates: result.state.map((d) => d.date),
    yFormatter: formatUsdShort,
    zero: true,
  });
}

function drawPhaseChart(canvas, result) {
  drawScatterChart(canvas, {
    points: result.state.map((d, i) => ({
      x: d.lpBalance,
      y: d.paperSupply,
      color: lerpColor("#482475", "#fde725", i / Math.max(1, result.state.length - 1)),
      label: formatDateFull(d.date),
      rows: [
        { color: COLORS.lp, label: "LP", value: formatUsdShort(d.lpBalance) },
        { color: COLORS.paper, label: "PAPER", value: formatCompact(d.paperSupply) },
      ],
    })),
    xFormatter: formatUsdShort,
    yFormatter: formatCompact,
  });
}

function drawLpDistributionCharts(result) {
  const gains = result.trades.filter((trade) => trade.lpDelta > 0).map((trade) => Math.log10(Math.max(1e-12, trade.lpDelta)));
  const losses = result.trades.filter((trade) => trade.lpDelta < 0).map((trade) => Math.log10(Math.max(1e-12, -trade.lpDelta)));
  drawHistogramChart(document.querySelector("#lpGainDistChart"), {
    datasets: [{ name: "LP gains", color: COLORS.bars, values: gains }],
    bins: 56,
    xFormatter: (v) => formatNumber(v),
    yFormatter: formatCompact,
  });
  drawHistogramChart(document.querySelector("#lpLossDistChart"), {
    datasets: [{ name: "LP losses", color: COLORS.liq, values: losses }],
    bins: 56,
    xFormatter: (v) => formatNumber(v),
    yFormatter: formatCompact,
  });
}

function drawNotionalDistributionChart(canvas, result) {
  drawHistogramChart(canvas, {
    datasets: [
      { name: "entry notional", color: COLORS.bars, values: result.trades.map((trade) => Math.log10(Math.max(1, trade.notionalAtEntry))) },
      { name: "after Paper cap", color: COLORS.paper, values: result.trades.map((trade) => Math.log10(Math.max(1, trade.paperNotional))) },
    ],
    bins: 64,
    xFormatter: (v) => formatNumber(v),
    yFormatter: formatCompact,
  });
}

function drawMintCurveChart(canvas, result) {
  const p = result.params;
  const xValues = Array.from({ length: 260 }, (_, i) => p.thresholdUsd + (5 * p.tailScaleUsd * i) / 259);
  const values = xValues.map((x) => {
    const h = Math.max(0, x - p.thresholdUsd);
    return p.flatRate * (p.tailScaleUsd / (p.tailScaleUsd + h)) ** 2;
  });
  drawLineChart(canvas, {
    series: [{ name: "rate", color: COLORS.paper, values, fill: true }],
    labels: xValues,
    xFormatter: formatUsdShort,
    yFormatter: (v) => `${formatNumber(v)} PAPER/$`,
    zero: true,
    guides: [{ value: p.flatRate, color: COLORS.threshold, label: "flat" }],
  });
}

function drawLineChart(canvas, options) {
  const { ctx, width, height } = setupCanvas(canvas);
  const m = { left: 82, right: 28, top: 14, bottom: 34 };
  const plot = getPlot(width, height, m);
  const length = Math.max(0, ...options.series.map((series) => series.values.length));
  const range = getVisibleRange(canvas, length);
  const visibleLength = Math.max(1, range.end - range.start + 1);
  const visibleSeries = options.series.map((series) => ({
    ...series,
    values: series.values.slice(range.start, range.end + 1),
  }));
  const visibleDates = options.dates?.slice(range.start, range.end + 1);
  const visibleLabels = options.labels?.slice(range.start, range.end + 1);
  const allValues = visibleSeries.flatMap((s) => s.values).filter(Number.isFinite);
  if (options.guides) allValues.push(...options.guides.map((g) => g.value));
  if (options.zero) allValues.push(0);
  let yMin = Math.min(...allValues);
  let yMax = Math.max(...allValues);
  if (!Number.isFinite(yMin) || !Number.isFinite(yMax) || yMin === yMax) {
    yMin = 0;
    yMax = 1;
  }
  const pad = (yMax - yMin) * 0.08;
  yMin -= pad;
  yMax += pad;
  if (options.zero && yMin > 0) yMin = 0;
  if (options.zero && yMax < 0) yMax = 0;

  clearCanvas(ctx, width, height);
  drawGrid(ctx, plot, yMin, yMax, options.yFormatter ?? formatCompact);

  if (options.guides) {
    for (const guide of options.guides) {
      if (guide.value < yMin || guide.value > yMax) continue;
      const y = mapY(guide.value, yMin, yMax, plot);
      ctx.save();
      ctx.setLineDash([5, 5]);
      ctx.strokeStyle = guide.color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(plot.x, y);
      ctx.lineTo(plot.x + plot.w, y);
      ctx.stroke();
      ctx.restore();
    }
  }

  for (const series of visibleSeries) {
    if (series.fill) {
      fillSeriesArea(ctx, series.values, {
        color: series.color,
        plot,
        yMin,
        yMax,
      });
    }
    drawSeriesPath(ctx, series.values, {
      color: series.color,
      width: series.name === "Net" ? 2.5 : 2,
      plot,
      yMin,
      yMax,
    });
  }

  drawAxes(ctx, plot);
  drawXTicks(ctx, plot, {
    dates: visibleDates,
    labels: visibleLabels,
    formatter: options.xFormatter,
  });
  registerInteractiveChart(canvas, {
    length,
    plot,
    visibleStart: range.start,
    visibleEnd: range.end,
    getTooltip: (index) => {
      const label = options.dates
        ? formatDateFull(options.dates[index])
        : (options.labels ? (options.xFormatter ? options.xFormatter(options.labels[index]) : options.labels[index]) : `#${index + 1}`);
      const rows = options.series.map((series) => ({
        color: series.color,
        label: series.name || "value",
        value: options.yFormatter ? options.yFormatter(series.values[index]) : formatCompact(series.values[index]),
      }));
      return { title: label, rows };
    },
  });
}

function drawSymlogLineChart(canvas, options) {
  const { ctx, width, height } = setupCanvas(canvas);
  const m = { left: 82, right: 28, top: 14, bottom: 34 };
  const plot = getPlot(width, height, m);
  const length = Math.max(0, ...options.series.map((series) => series.values.length));
  const range = getVisibleRange(canvas, length);
  const visibleSeries = options.series.map((series) => ({
    ...series,
    values: series.values.slice(range.start, range.end + 1),
  }));
  const visibleDates = options.dates?.slice(range.start, range.end + 1);
  const allValues = visibleSeries.flatMap((s) => s.values).filter(Number.isFinite);
  if (options.guides) allValues.push(...options.guides.map((g) => g.value));
  allValues.push(0);
  let yMin = Math.min(...allValues);
  let yMax = Math.max(...allValues);
  if (!Number.isFinite(yMin) || !Number.isFinite(yMax) || yMin === yMax) {
    yMin = 0;
    yMax = 1;
  }
  const pad = (yMax - yMin) * 0.08;
  yMin -= pad;
  yMax += pad;

  const constant = options.constant ?? 1_000;
  const tMin = symlog(yMin, constant);
  const tMax = symlog(yMax, constant);

  clearCanvas(ctx, width, height);
  drawSymlogGrid(ctx, plot, yMin, yMax, constant, options.yFormatter ?? formatCompact);

  if (options.guides) {
    for (const guide of options.guides) {
      if (guide.value < yMin || guide.value > yMax) continue;
      const y = mapY(symlog(guide.value, constant), tMin, tMax, plot);
      ctx.save();
      ctx.setLineDash([5, 5]);
      ctx.strokeStyle = guide.color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(plot.x, y);
      ctx.lineTo(plot.x + plot.w, y);
      ctx.stroke();
      ctx.restore();
    }
  }

  for (const series of visibleSeries) {
    if (series.fill) {
      fillSymlogSeriesArea(ctx, series.values, { color: series.color, plot, tMin, tMax, constant });
    }
    drawSymlogSeriesPath(ctx, series.values, { color: series.color, width: 2, plot, tMin, tMax, constant });
  }

  drawAxes(ctx, plot);
  drawXTicks(ctx, plot, { dates: visibleDates });
  registerInteractiveChart(canvas, {
    length,
    plot,
    visibleStart: range.start,
    visibleEnd: range.end,
    getTooltip: (index) => ({
      title: options.dates ? formatDateFull(options.dates[index]) : `#${index + 1}`,
      rows: options.series.map((series) => ({
        color: series.color,
        label: series.name || "value",
        value: options.yFormatter ? options.yFormatter(series.values[index]) : formatCompact(series.values[index]),
      })),
    }),
  });
}

function drawIndexedChart(canvas, options) {
  const { ctx, width, height } = setupCanvas(canvas);
  const m = { left: 50, right: 14, top: 14, bottom: 34 };
  const plot = getPlot(width, height, m);
  const length = options.labels.length;
  const range = getVisibleRange(canvas, length);
  const visibleLabels = options.labels.slice(range.start, range.end + 1);
  const visibleSeries = options.series.map((series) => ({
    ...series,
    values: series.values.slice(range.start, range.end + 1),
  }));
  const visibleValues = visibleSeries.flatMap((series) => series.values).filter(Number.isFinite);
  const yMin = options.yMin ?? Math.min(0, ...visibleValues);
  const yMax = options.yMax ?? niceMax(Math.max(1, ...visibleValues));
  clearCanvas(ctx, width, height);
  drawGrid(ctx, plot, yMin, yMax, options.yFormatter);
  for (const series of visibleSeries) {
    drawSeriesPath(ctx, series.values, {
      color: series.color,
      width: 2.4,
      plot,
      yMin,
      yMax,
    });
  }
  drawAxes(ctx, plot);
  ctx.fillStyle = COLORS.muted;
  ctx.font = "12px Inter, system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  visibleLabels.forEach((label, i) => {
    if (i % options.xLabelEvery !== 0 && i !== visibleLabels.length - 1) return;
    const x = mapX(i, visibleLabels.length, plot);
    ctx.fillText(label, x, plot.y + plot.h + 10);
  });
  ctx.textAlign = "right";
  ctx.fillText("bps", plot.x + plot.w, plot.y + plot.h + 24);
  registerInteractiveChart(canvas, {
    length,
    plot,
    visibleStart: range.start,
    visibleEnd: range.end,
    getTooltip: (index) => ({
      title: `${options.labels[index]} bps`,
      rows: options.series.map((series, seriesIndex) => ({
        color: series.color,
        label: series.name || (seriesIndex === 0 ? "BTC" : "ETH"),
        value: options.yFormatter(series.values[index]),
      })),
    }),
  });
}

function drawStackedBarChart(canvas, options) {
  const { ctx, width, height } = setupCanvas(canvas);
  const m = { left: 74, right: 28, top: 14, bottom: 34 };
  const plot = getPlot(width, height, m);
  const length = options.dates.length;
  const range = getVisibleRange(canvas, length);
  const visibleSeries = options.series.map((series) => ({
    ...series,
    values: series.values.slice(range.start, range.end + 1),
  }));
  const visibleDates = options.dates.slice(range.start, range.end + 1);
  const totals = visibleDates.map((_, i) => visibleSeries.reduce((sum, series) => sum + series.values[i], 0));
  const yMax = niceMax(Math.max(1, ...totals));

  clearCanvas(ctx, width, height);
  drawGrid(ctx, plot, 0, yMax, options.yFormatter);
  drawAdlBands(ctx, plot, visibleDates.map((date, i) => ({ date, nAdl: options.adl?.[range.start + i] ?? 0 })));

  const barW = Math.max(1, plot.w / Math.max(1, visibleDates.length) - 1);
  visibleDates.forEach((_, i) => {
    let bottom = 0;
    for (const series of visibleSeries) {
      const value = series.values[i];
      const yTop = mapY(bottom + value, 0, yMax, plot);
      const yBottom = mapY(bottom, 0, yMax, plot);
      ctx.fillStyle = hexToRgba(series.color, 0.72);
      ctx.fillRect(plot.x + (i / visibleDates.length) * plot.w, yTop, barW, Math.max(0, yBottom - yTop));
      bottom += value;
    }
  });

  drawAxes(ctx, plot);
  drawXTicks(ctx, plot, { dates: visibleDates });
  registerInteractiveChart(canvas, {
    length,
    plot,
    visibleStart: range.start,
    visibleEnd: range.end,
    getTooltip: (index) => ({
      title: formatDateFull(options.dates[index]),
      rows: options.series.map((series) => ({
        color: series.color,
        label: series.name,
        value: options.yFormatter(series.values[index]),
      })),
    }),
  });
}

function drawStackedAreaChart(canvas, options) {
  const { ctx, width, height } = setupCanvas(canvas);
  const m = { left: 74, right: 28, top: 14, bottom: 34 };
  const plot = getPlot(width, height, m);
  const length = options.dates.length;
  const range = getVisibleRange(canvas, length);
  const visibleDates = options.dates.slice(range.start, range.end + 1);
  const visibleSeries = options.series.map((series) => ({
    ...series,
    values: series.values.slice(range.start, range.end + 1),
  }));
  const visibleTotal = options.total.values.slice(range.start, range.end + 1);
  const yMax = niceMax(Math.max(1, ...visibleTotal));

  clearCanvas(ctx, width, height);
  drawGrid(ctx, plot, 0, yMax, options.yFormatter);

  const first = visibleSeries[0]?.values ?? [];
  const second = visibleSeries[1]?.values ?? [];
  fillBand(ctx, first.map(() => 0), first, { color: visibleSeries[0].color, plot, yMin: 0, yMax });
  fillBand(ctx, first, first.map((v, i) => v + (second[i] ?? 0)), { color: visibleSeries[1].color, plot, yMin: 0, yMax });
  drawSeriesPath(ctx, visibleTotal, { color: options.total.color, width: 2.2, plot, yMin: 0, yMax });

  drawAxes(ctx, plot);
  drawXTicks(ctx, plot, { dates: visibleDates });
  registerInteractiveChart(canvas, {
    length,
    plot,
    visibleStart: range.start,
    visibleEnd: range.end,
    getTooltip: (index) => ({
      title: formatDateFull(options.dates[index]),
      rows: [
        ...options.series.map((series) => ({
          color: series.color,
          label: series.name,
          value: options.yFormatter(series.values[index]),
        })),
        { color: options.total.color, label: options.total.name, value: options.yFormatter(options.total.values[index]) },
      ],
    }),
  });
}

function drawHistogramChart(canvas, options) {
  const { ctx, width, height } = setupCanvas(canvas);
  const m = { left: 56, right: 14, top: 14, bottom: 34 };
  const plot = getPlot(width, height, m);
  const allValues = options.datasets.flatMap((dataset) => dataset.values).filter(Number.isFinite);
  const min = Math.min(...allValues, 0);
  const max = Math.max(...allValues, 1);
  const binCount = options.bins ?? 50;
  const binWidth = (max - min || 1) / binCount;
  const bins = Array.from({ length: binCount }, (_, i) => ({
    min: min + i * binWidth,
    max: min + (i + 1) * binWidth,
  }));
  const histograms = options.datasets.map((dataset) => {
    const counts = Array(binCount).fill(0);
    for (const value of dataset.values) {
      if (!Number.isFinite(value)) continue;
      const index = clampInt(Math.floor((value - min) / binWidth), 0, binCount - 1);
      counts[index] += 1;
    }
    return { ...dataset, counts };
  });
  const range = getVisibleRange(canvas, binCount);
  const visibleBins = bins.slice(range.start, range.end + 1);
  const visibleHistograms = histograms.map((hist) => ({
    ...hist,
    counts: hist.counts.slice(range.start, range.end + 1),
  }));
  const yMax = niceMax(Math.max(1, ...visibleHistograms.flatMap((hist) => hist.counts)));

  clearCanvas(ctx, width, height);
  drawGrid(ctx, plot, 0, yMax, options.yFormatter);
  const barW = Math.max(1, plot.w / Math.max(1, visibleBins.length));
  visibleHistograms.forEach((hist, histIndex) => {
    hist.counts.forEach((count, i) => {
      const y = mapY(count, 0, yMax, plot);
      ctx.fillStyle = hexToRgba(hist.color, histograms.length > 1 ? 0.55 : 0.78);
      const inset = histograms.length > 1 ? histIndex * (barW / 5) : 0;
      ctx.fillRect(plot.x + i * barW + inset, y, Math.max(1, barW - 1), plot.y + plot.h - y);
    });
  });
  drawAxes(ctx, plot);
  drawNumericTicks(ctx, plot, visibleBins.map((bin) => (bin.min + bin.max) / 2), options.xFormatter);
  registerInteractiveChart(canvas, {
    length: binCount,
    plot,
    visibleStart: range.start,
    visibleEnd: range.end,
    getTooltip: (index) => {
      const bin = bins[index];
      return {
        title: `${options.xFormatter(bin.min)} to ${options.xFormatter(bin.max)}`,
        rows: histograms.map((hist) => ({
          color: hist.color,
          label: hist.name,
          value: options.yFormatter(hist.counts[index]),
        })),
      };
    },
  });
}

function drawScatterChart(canvas, options) {
  const { ctx, width, height } = setupCanvas(canvas);
  const m = { left: 74, right: 28, top: 14, bottom: 34 };
  const plot = getPlot(width, height, m);
  const length = options.points.length;
  const range = getVisibleRange(canvas, length);
  const points = options.points.slice(range.start, range.end + 1);
  const xValues = points.map((point) => point.x);
  const yValues = points.map((point) => point.y);
  const xMin = Math.min(0, ...xValues);
  const xMax = Math.max(1, ...xValues);
  const yMin = Math.min(0, ...yValues);
  const yMax = Math.max(1, ...yValues);
  const xPad = (xMax - xMin) * 0.08;
  const yPad = (yMax - yMin) * 0.08;

  clearCanvas(ctx, width, height);
  drawGrid(ctx, plot, yMin - yPad, yMax + yPad, options.yFormatter);
  points.forEach((point) => {
    const x = plot.x + ((point.x - (xMin - xPad)) / ((xMax + xPad) - (xMin - xPad) || 1)) * plot.w;
    const y = mapY(point.y, yMin - yPad, yMax + yPad, plot);
    ctx.fillStyle = point.color;
    ctx.beginPath();
    ctx.arc(x, y, 3.2, 0, Math.PI * 2);
    ctx.fill();
  });
  drawAxes(ctx, plot);
  drawNumericTicks(ctx, plot, Array.from({ length: 5 }, (_, i) => (xMin - xPad) + (((xMax + xPad) - (xMin - xPad)) * i) / 4), options.xFormatter);
  registerInteractiveChart(canvas, {
    length,
    plot,
    visibleStart: range.start,
    visibleEnd: range.end,
    getTooltip: (index) => {
      const point = options.points[index];
      return { title: point.label, rows: point.rows };
    },
  });
}

function setupCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(280, rect.width);
  const height = Math.max(220, rect.height);
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, width, height };
}

function clearCanvas(ctx, width, height) {
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);
}

function getPlot(width, height, margin) {
  return {
    x: margin.left,
    y: margin.top,
    w: width - margin.left - margin.right,
    h: height - margin.top - margin.bottom,
  };
}

function drawGrid(ctx, plot, yMin, yMax, formatter) {
  ctx.save();
  ctx.strokeStyle = COLORS.grid;
  ctx.lineWidth = 1;
  ctx.fillStyle = COLORS.muted;
  ctx.font = "12px Inter, system-ui, sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= 4; i += 1) {
    const value = yMin + ((yMax - yMin) * i) / 4;
    const y = mapY(value, yMin, yMax, plot);
    ctx.beginPath();
    ctx.moveTo(plot.x, y);
    ctx.lineTo(plot.x + plot.w, y);
    ctx.stroke();
    ctx.fillText(formatter(value), plot.x - 8, y);
  }
  ctx.restore();
}

function drawSymlogGrid(ctx, plot, yMin, yMax, constant, formatter) {
  const tMin = symlog(yMin, constant);
  const tMax = symlog(yMax, constant);
  ctx.save();
  ctx.strokeStyle = COLORS.grid;
  ctx.lineWidth = 1;
  ctx.fillStyle = COLORS.muted;
  ctx.font = "12px Inter, system-ui, sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (const value of symlogTickValues(yMin, yMax)) {
    const y = mapY(symlog(value, constant), tMin, tMax, plot);
    ctx.beginPath();
    ctx.moveTo(plot.x, y);
    ctx.lineTo(plot.x + plot.w, y);
    ctx.stroke();
    ctx.fillText(formatter(value), plot.x - 8, y);
  }
  ctx.restore();
}

function drawAxes(ctx, plot) {
  ctx.save();
  ctx.strokeStyle = COLORS.axis;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(plot.x, plot.y);
  ctx.lineTo(plot.x, plot.y + plot.h);
  ctx.lineTo(plot.x + plot.w, plot.y + plot.h);
  ctx.stroke();
  ctx.restore();
}

function drawDateTicks(ctx, plot, dates) {
  if (!dates?.length) return;
  ctx.save();
  ctx.fillStyle = COLORS.muted;
  ctx.font = "12px Inter, system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const ticks = plot.w < 420 ? 3 : 4;
  for (let i = 0; i <= ticks; i += 1) {
    const index = Math.round(((dates.length - 1) * i) / ticks);
    const x = clamp(mapX(index, dates.length, plot), plot.x + 34, plot.x + plot.w - 34);
    ctx.fillText(formatDate(dates[index]), x, plot.y + plot.h + 10);
  }
  ctx.restore();
}

function drawXTicks(ctx, plot, options = {}) {
  if (options.dates?.length) {
    drawDateTicks(ctx, plot, options.dates);
    return;
  }
  if (options.labels?.length) {
    drawNumericTicks(ctx, plot, options.labels, options.formatter ?? String);
  }
}

function drawNumericTicks(ctx, plot, values, formatter = String) {
  if (!values?.length) return;
  ctx.save();
  ctx.fillStyle = COLORS.muted;
  ctx.font = "12px Inter, system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const ticks = Math.min(plot.w < 420 ? 3 : 4, values.length - 1);
  if (ticks <= 0) {
    ctx.fillText(formatter(values[0]), plot.x + plot.w / 2, plot.y + plot.h + 10);
    ctx.restore();
    return;
  }
  for (let i = 0; i <= ticks; i += 1) {
    const index = Math.round(((values.length - 1) * i) / ticks);
    const x = clamp(mapX(index, values.length, plot), plot.x + 34, plot.x + plot.w - 34);
    ctx.fillText(formatter(values[index]), x, plot.y + plot.h + 10);
  }
  ctx.restore();
}

function drawAdlBands(ctx, plot, dailyRows) {
  const maxAdl = Math.max(0, ...dailyRows.map((row) => row.nAdl || 0));
  if (!maxAdl) return;
  dailyRows.forEach((row, i) => {
    if (!row.nAdl) return;
    const alpha = 0.08 + 0.24 * Math.log10(row.nAdl + 1) / Math.log10(maxAdl + 1);
    const x = mapX(i, dailyRows.length, plot);
    const w = Math.max(2, plot.w / Math.max(1, dailyRows.length));
    ctx.fillStyle = `rgba(148, 103, 189, ${alpha})`;
    ctx.fillRect(x - w / 2, plot.y, w, plot.h);
  });
}

function drawSeriesPath(ctx, values, options) {
  const { color, width, plot, yMin, yMax } = options;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  values.forEach((value, i) => {
    const x = mapX(i, values.length, plot);
    const y = mapY(value, yMin, yMax, plot);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.restore();
}

function fillSeriesArea(ctx, values, options) {
  const { color, plot, yMin, yMax } = options;
  const zeroY = mapY(clamp(0, yMin, yMax), yMin, yMax, plot);
  ctx.save();
  ctx.fillStyle = hexToRgba(color, 0.11);
  ctx.beginPath();
  values.forEach((value, i) => {
    const x = mapX(i, values.length, plot);
    const y = mapY(value, yMin, yMax, plot);
    if (i === 0) ctx.moveTo(x, zeroY);
    ctx.lineTo(x, y);
  });
  ctx.lineTo(mapX(values.length - 1, values.length, plot), zeroY);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function drawSymlogSeriesPath(ctx, values, options) {
  const { color, width, plot, tMin, tMax, constant } = options;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  values.forEach((value, i) => {
    const x = mapX(i, values.length, plot);
    const y = mapY(symlog(value, constant), tMin, tMax, plot);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.restore();
}

function fillSymlogSeriesArea(ctx, values, options) {
  const { color, plot, tMin, tMax, constant } = options;
  const zeroY = mapY(symlog(0, constant), tMin, tMax, plot);
  ctx.save();
  ctx.fillStyle = hexToRgba(color, 0.11);
  ctx.beginPath();
  values.forEach((value, i) => {
    const x = mapX(i, values.length, plot);
    const y = mapY(symlog(value, constant), tMin, tMax, plot);
    if (i === 0) ctx.moveTo(x, zeroY);
    ctx.lineTo(x, y);
  });
  ctx.lineTo(mapX(values.length - 1, values.length, plot), zeroY);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function fillBand(ctx, bottomValues, topValues, options) {
  const { color, plot, yMin, yMax } = options;
  if (!topValues.length) return;
  ctx.save();
  ctx.fillStyle = hexToRgba(color, 0.45);
  ctx.beginPath();
  topValues.forEach((value, i) => {
    const x = mapX(i, topValues.length, plot);
    const y = mapY(value, yMin, yMax, plot);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  for (let i = bottomValues.length - 1; i >= 0; i -= 1) {
    ctx.lineTo(mapX(i, bottomValues.length, plot), mapY(bottomValues[i], yMin, yMax, plot));
  }
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function mapX(index, length, plot) {
  if (length <= 1) return plot.x;
  return plot.x + (index / (length - 1)) * plot.w;
}

function mapY(value, min, max, plot) {
  return plot.y + plot.h - ((value - min) / (max - min || 1)) * plot.h;
}

function symlog(value, constant = 1_000) {
  return Math.sign(value) * Math.log10(1 + Math.abs(value) / constant);
}

function symlogTickValues(yMin, yMax) {
  const candidates = [
    -100_000_000,
    -10_000_000,
    -1_000_000,
    -100_000,
    -10_000,
    -1_000,
    -100,
    -10,
    0,
    10,
    100,
    1_000,
    10_000,
    100_000,
    1_000_000,
    10_000_000,
    100_000_000,
  ].filter((value) => value >= yMin && value <= yMax);

  const values = candidates.length ? candidates : [yMin, 0, yMax].filter((value) => value >= yMin && value <= yMax);
  if (values.length <= 6) return values;
  return Array.from({ length: 6 }, (_, i) => values[Math.round(((values.length - 1) * i) / 5)]);
}

function registerInteractiveChart(canvas, meta) {
  chartMeta.set(canvas.id, meta);
  if (canvas.dataset.interactive === "true") return;
  canvas.dataset.interactive = "true";
  canvas.addEventListener("mousemove", handleChartPointerMove);
  canvas.addEventListener("mouseleave", hideChartTooltip);
  canvas.addEventListener("wheel", handleChartWheel, { passive: false });
  canvas.addEventListener("dblclick", () => {
    chartZoom.delete(canvas.id);
    scheduleUpdate();
  });
  canvas.addEventListener("pointerdown", (event) => {
    const metaForCanvas = chartMeta.get(canvas.id);
    const zoom = chartZoom.get(canvas.id);
    if (!metaForCanvas || !zoom) return;
    canvas.setPointerCapture(event.pointerId);
    panState = {
      canvas,
      pointerId: event.pointerId,
      x: event.clientX,
      start: zoom.start,
      end: zoom.end,
    };
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!panState || panState.canvas !== canvas) return;
    const metaForCanvas = chartMeta.get(canvas.id);
    if (!metaForCanvas) return;
    const span = panState.end - panState.start + 1;
    const dx = event.clientX - panState.x;
    const shift = Math.round((-dx / Math.max(1, metaForCanvas.plot.w)) * span);
    const nextStart = clampInt(panState.start + shift, 0, Math.max(0, metaForCanvas.length - span));
    chartZoom.set(canvas.id, { start: nextStart, end: nextStart + span - 1 });
    scheduleUpdate();
  });
  canvas.addEventListener("pointerup", (event) => {
    if (panState?.canvas === canvas && panState.pointerId === event.pointerId) {
      panState = null;
    }
  });
}

function handleChartWheel(event) {
  const canvas = event.currentTarget;
  const meta = chartMeta.get(canvas.id);
  if (!meta || meta.length <= 2) return;
  const rect = canvas.getBoundingClientRect();
  const localX = event.clientX - rect.left;
  if (localX < meta.plot.x || localX > meta.plot.x + meta.plot.w) return;
  event.preventDefault();

  const current = chartZoom.get(canvas.id) ?? { start: 0, end: meta.length - 1 };
  const span = current.end - current.start + 1;
  const minSpan = Math.min(meta.length, 8);
  const nextSpan = clampInt(Math.round(span * (event.deltaY < 0 ? 0.78 : 1.26)), minSpan, meta.length);
  const ratio = clamp((localX - meta.plot.x) / meta.plot.w, 0, 1);
  const center = current.start + ratio * (span - 1);
  let nextStart = Math.round(center - ratio * (nextSpan - 1));
  nextStart = clampInt(nextStart, 0, Math.max(0, meta.length - nextSpan));
  chartZoom.set(canvas.id, { start: nextStart, end: nextStart + nextSpan - 1 });
  scheduleUpdate();
}

function handleChartPointerMove(event) {
  if (panState) return;
  const canvas = event.currentTarget;
  const meta = chartMeta.get(canvas.id);
  if (!meta) return;
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  if (x < meta.plot.x || x > meta.plot.x + meta.plot.w || y < meta.plot.y || y > meta.plot.y + meta.plot.h) {
    hideChartTooltip();
    return;
  }

  const span = meta.visibleEnd - meta.visibleStart + 1;
  const localIndex = clampInt(Math.round(((x - meta.plot.x) / meta.plot.w) * (span - 1)), 0, span - 1);
  const index = meta.visibleStart + localIndex;
  const payload = meta.getTooltip(index);
  if (!payload) {
    hideChartTooltip();
    return;
  }
  showChartTooltip(payload, event.clientX, event.clientY);
}

function showChartTooltip(payload, clientX, clientY) {
  if (!chartTooltip) {
    chartTooltip = document.createElement("div");
    chartTooltip.className = "chart-tooltip";
    document.body.appendChild(chartTooltip);
  }
  chartTooltip.innerHTML = `
    <strong>${payload.title}</strong>
    ${payload.rows.map((row) => `
      <span><i style="background:${row.color}"></i><em>${row.label}</em><b>${row.value}</b></span>
    `).join("")}
  `;
  chartTooltip.style.left = `${clientX + 14}px`;
  chartTooltip.style.top = `${clientY + 14}px`;
  chartTooltip.hidden = false;
}

function hideChartTooltip() {
  if (chartTooltip) chartTooltip.hidden = true;
}

function getVisibleRange(canvas, length) {
  const zoom = chartZoom.get(canvas.id);
  if (!zoom || length <= 0) return { start: 0, end: Math.max(0, length - 1) };
  const start = clampInt(zoom.start, 0, Math.max(0, length - 1));
  const end = clampInt(zoom.end, start, Math.max(0, length - 1));
  return { start, end };
}

function niceMax(value) {
  if (value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  return Math.ceil(value / power) * power;
}

function readParamsFromUrl() {
  const url = new URL(window.location.href);
  const next = {};
  for (const key of EDITABLE_IDS) {
    const raw = url.searchParams.get(key);
    if (raw === null) continue;
    const value = Number(raw);
    if (Number.isFinite(value)) next[key] = value;
  }
  return next;
}

function replaceUrlFromState() {
  const search = new URLSearchParams();
  for (const key of EDITABLE_IDS) {
    const value = params[key];
    const defaultValue = DEFAULTS[key];
    if (Math.abs(value - defaultValue) > 1e-9) {
      search.set(key, trimNumber(value, 6));
    }
  }
  const hash = window.location.hash === "#methodology" ? "#methodology" : "";
  const next = `${window.location.pathname}${search.toString() ? `?${search.toString()}` : ""}${hash}`;
  window.history.replaceState(null, "", next);
}

function clampParams(input) {
  const next = { ...DEFAULTS, ...input };
  for (const group of CONTROL_GROUPS) {
    for (const control of group.controls) {
      const view = internalToView(control, next[control.id]);
      const clampedView = clamp(view, control.min, control.max);
      next[control.id] = viewToInternal(control, control.integer ? Math.round(clampedView) : clampedView);
    }
  }
  return next;
}

function internalToView(control, value) {
  return value * (control.factor ?? 1);
}

function viewToInternal(control, value) {
  const safe = Number.isFinite(value) ? value : internalToView(control, DEFAULTS[control.id]);
  const clamped = clamp(safe, control.min, control.max);
  const next = clamped / (control.factor ?? 1);
  return control.integer ? Math.round(next) : next;
}

function formatControlValue(control, value) {
  if (control.format) return control.format(value);
  const view = internalToView(control, value);
  const decimals = decimalsFor(control.step ?? 1);
  return `${trimNumber(view, decimals)}${control.suffix ?? ""}`;
}

function flashStatus(text) {
  statusText.value = text;
  window.clearTimeout(flashStatus.timer);
  flashStatus.timer = window.setTimeout(() => {
    statusText.value = "Ready";
  }, 900);
}

function running(values) {
  let total = 0;
  return values.map((value) => {
    total += value;
    return total;
  });
}

function mulberry32(seed) {
  let t = seed >>> 0;
  return function next() {
    t += 0x6d2b79f5;
    let x = t;
    x = Math.imul(x ^ (x >>> 15), x | 1);
    x ^= x + Math.imul(x ^ (x >>> 7), x | 61);
    return ((x ^ (x >>> 14)) >>> 0) / 4_294_967_296;
  };
}

function randNormal(rand) {
  let u = 0;
  let v = 0;
  while (u === 0) u = rand();
  while (v === 0) v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

function logNormal(rand, median, sigma) {
  return Math.exp(Math.log(median) + sigma * randNormal(rand));
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function clampInt(value, min, max) {
  return Math.min(max, Math.max(min, Math.trunc(value)));
}

function debounce(fn, wait) {
  let timer = null;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), wait);
  };
}

function hexToRgba(hex, alpha) {
  const clean = hex.replace("#", "");
  const n = Number.parseInt(clean, 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function lerpColor(from, to, t) {
  const a = Number.parseInt(from.replace("#", ""), 16);
  const b = Number.parseInt(to.replace("#", ""), 16);
  const ar = (a >> 16) & 255;
  const ag = (a >> 8) & 255;
  const ab = a & 255;
  const br = (b >> 16) & 255;
  const bg = (b >> 8) & 255;
  const bb = b & 255;
  const rr = Math.round(ar + (br - ar) * t);
  const rg = Math.round(ag + (bg - ag) * t);
  const rb = Math.round(ab + (bb - ab) * t);
  return `rgb(${rr}, ${rg}, ${rb})`;
}

function decimalsFor(step) {
  const str = String(step);
  return str.includes(".") ? str.split(".")[1].length : 0;
}

function trimNumber(value, decimals = 2) {
  const text = Number(value).toFixed(decimals);
  return text.includes(".") ? text.replace(/\.?0+$/, "") : text;
}

function formatDate(date) {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "2-digit" }).format(date);
}

function formatDateFull(date) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
  }).format(date);
}

function formatUsdShort(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: Math.abs(value) >= 1000 ? 1 : 0,
  }).format(value);
}

function formatUsdSmall(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: Math.abs(value) < 1 ? 4 : 2,
    maximumFractionDigits: Math.abs(value) < 1 ? 6 : 2,
  }).format(value);
}

function formatCompact(value) {
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function formatPct(value) {
  return `${trimNumber(value * 100, value < 0.1 ? 1 : 0)}%`;
}

function formatNumber(value) {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: Math.abs(value) < 10 ? 2 : 1,
  }).format(value);
}
