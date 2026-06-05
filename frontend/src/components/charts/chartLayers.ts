// chartLayers — turn the server-enriched /full payload into render-ready results
// for the KLineChart custom-indicator adapter (see customIndicators.addSpecIndicator).
//
// No client-side TA: the backend computed everything. We only shape it:
// - levels (fib + S/R) → constant horizontal lines on the candle pane
// - markers (buy/sell + insider) → circle dots at the relevant bars
// - RS-vs-SPY → a line in its own sub-pane
// All /full times are epoch SECONDS; KLineChart bars are ms (×1000 to align).

import type { KLineData } from 'klinecharts';

import type { ComputeResult, ComputedPlot, IndicatorSpec } from '../../lib/indicatorApi';
import type { ChartFullResponse } from '../../lib/chartFullApi';

const CYAN = '#22d3ee';
const MAGENTA = '#ff5cf4';

/**
 * VWAP = cumsum(hlc3 · volume) / cumsum(volume), expressed in the constrained
 * engine grammar (the `cumsum` op makes this possible). Computed over whatever
 * bars are passed: full bars = session/range VWAP; bars sliced from an anchor =
 * anchored VWAP. `color` distinguishes the two on the chart.
 */
export function vwapSpec(color = CYAN, label = 'VWAP'): IndicatorSpec {
  return {
    name: label,
    short_name: label,
    pane: 'overlay',
    precision: 2,
    steps: [
      { id: 'tp', op: 'series', ref: 'hlc3' },
      { id: 'v', op: 'series', ref: 'volume' },
      { id: 'tpv', op: 'mul', inputs: ['tp', 'v'] },
      { id: 'ctpv', op: 'cumsum', input: 'tpv' },
      { id: 'cv', op: 'cumsum', input: 'v' },
      { id: 'vw', op: 'div', inputs: ['ctpv', 'cv'] },
    ],
    plots: [{ step: 'vw', label, color }],
  };
}

export const VWAP_SESSION_COLOR = CYAN;
export const VWAP_ANCHORED_COLOR = MAGENTA;

const GREEN = '#00ff41';
const RED = '#ff3b3b';
const GOLD = '#ffcc00';
const GREY = '#888888';
const PURPLE = '#b388ff';

/** Constant-value horizontal line across every bar (a price level). */
function levelPlot(
  step: string,
  label: string,
  value: number,
  color: string,
  bars: KLineData[],
): ComputedPlot {
  return {
    step,
    label,
    type: 'line',
    color,
    points: bars.map((b) => ({ time: b.timestamp, value })),
  };
}

/** Fib retracements/extensions + nearest support/resistance as horizontal lines. */
export function buildLevelsResult(full: ChartFullResponse, bars: KLineData[]): ComputeResult | null {
  if (!bars.length) return null;
  const plots: ComputedPlot[] = [];
  const fib = full.overlays?.fib_levels;
  if (fib) {
    for (const [ratio, price] of Object.entries(fib.retracements || {})) {
      if (Number.isFinite(price)) plots.push(levelPlot(`fib-${ratio}`, `fib ${ratio}`, price, GOLD, bars));
    }
    for (const [ratio, price] of Object.entries(fib.extensions || {})) {
      if (Number.isFinite(price)) plots.push(levelPlot(`ext-${ratio}`, `ext ${ratio}`, price, GREY, bars));
    }
  }
  const sr = full.overlays?.support_resistance;
  if (sr) {
    (sr.resistances || []).slice(0, 3).forEach((p, i) => {
      if (Number.isFinite(p)) plots.push(levelPlot(`r${i + 1}`, `R${i + 1}`, p, RED, bars));
    });
    (sr.supports || []).slice(0, 3).forEach((p, i) => {
      if (Number.isFinite(p)) plots.push(levelPlot(`s${i + 1}`, `S${i + 1}`, p, GREEN, bars));
    });
  }
  if (!plots.length) return null;
  return { name: 'Levels', short_name: 'LVL', pane: 'overlay', precision: 2, plots, bars: bars.length };
}

/** Buy/sell signal markers + insider markers as colored circles at their bars. */
export function buildMarkersResult(full: ChartFullResponse, bars: KLineData[]): ComputeResult | null {
  if (!bars.length) return null;
  const byTime = new Map<number, KLineData>();
  for (const b of bars) byTime.set(b.timestamp, b);

  const bull: { time: number; value: number }[] = [];
  const bear: { time: number; value: number }[] = [];
  const insider: { time: number; value: number }[] = [];

  for (const m of full.markers?.signal_events || []) {
    const bar = byTime.get(m.time * 1000);
    if (!bar) continue;
    const lbl = (m.label || '').toLowerCase();
    if (lbl.includes('bear')) bear.push({ time: bar.timestamp, value: bar.high * 1.005 });
    else bull.push({ time: bar.timestamp, value: bar.low * 0.995 });
  }
  for (const m of full.markers?.insider_buys || []) {
    const bar = byTime.get(m.time * 1000);
    if (bar) insider.push({ time: bar.timestamp, value: bar.low * 0.99 });
  }

  const plots: ComputedPlot[] = [];
  if (bull.length) plots.push({ step: 'bull', label: 'bull', type: 'circle', color: GREEN, points: bull });
  if (bear.length) plots.push({ step: 'bear', label: 'bear', type: 'circle', color: RED, points: bear });
  if (insider.length)
    plots.push({ step: 'insider', label: 'insider', type: 'circle', color: PURPLE, points: insider });
  if (!plots.length) return null;
  return { name: 'Signals', short_name: 'SIG', pane: 'overlay', precision: 2, plots, bars: bars.length };
}

// --- Volume Profile -------------------------------------------------------

export interface VolumeBin {
  low: number;
  high: number;
  mid: number;
  volume: number;
}
export interface VolumeProfile {
  bins: VolumeBin[];
  poc: number; // price of the point-of-control (highest-volume bin)
  vah: number; // value-area high
  val: number; // value-area low
  maxVol: number; // volume of the POC bin
}

/**
 * Volume-by-price profile from the displayed bars (TradingView "visible range"
 * style). Each bar's volume is spread evenly across the price bins it spans
 * (low→high). POC = highest-volume bin; value area = the contiguous band around
 * the POC holding ~70% of total volume. Pure — no charting, fully testable.
 */
export function computeVolumeProfile(bars: KLineData[], nBins = 24): VolumeProfile | null {
  if (bars.length < 2 || nBins < 2) return null;
  let lo = Infinity;
  let hi = -Infinity;
  for (const b of bars) {
    if (Number.isFinite(b.low)) lo = Math.min(lo, b.low);
    if (Number.isFinite(b.high)) hi = Math.max(hi, b.high);
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) return null;

  const size = (hi - lo) / nBins;
  const vols = new Array(nBins).fill(0);
  const binOf = (p: number) => Math.min(nBins - 1, Math.max(0, Math.floor((p - lo) / size)));
  for (const b of bars) {
    const v = Number.isFinite(b.volume as number) ? (b.volume as number) : 0;
    if (v <= 0 || !Number.isFinite(b.low) || !Number.isFinite(b.high)) continue;
    const a = binOf(b.low);
    const z = binOf(b.high);
    const span = z - a + 1;
    const per = v / span;
    for (let i = a; i <= z; i++) vols[i] += per;
  }

  const bins: VolumeBin[] = vols.map((vol, i) => ({
    low: lo + i * size,
    high: lo + (i + 1) * size,
    mid: lo + (i + 0.5) * size,
    volume: vol,
  }));
  let pocIdx = 0;
  for (let i = 1; i < nBins; i++) if (vols[i] > vols[pocIdx]) pocIdx = i;
  const total = vols.reduce((s, v) => s + v, 0);
  // Expand a band out from the POC until it holds ~70% of volume.
  let loI = pocIdx;
  let hiI = pocIdx;
  let acc = vols[pocIdx];
  while (acc < total * 0.7 && (loI > 0 || hiI < nBins - 1)) {
    const below = loI > 0 ? vols[loI - 1] : -1;
    const above = hiI < nBins - 1 ? vols[hiI + 1] : -1;
    if (above >= below) acc += vols[++hiI];
    else acc += vols[--loI];
  }
  return {
    bins,
    poc: bins[pocIdx].mid,
    vah: bins[hiI].high,
    val: bins[loI].low,
    maxVol: vols[pocIdx],
  };
}

/** POC + value-area-high/low as horizontal lines (reliable render path). */
export function buildVolumeProfileLevels(vp: VolumeProfile, bars: KLineData[]): ComputeResult | null {
  if (!bars.length) return null;
  const plots: ComputedPlot[] = [
    { step: 'poc', label: 'POC', type: 'line', color: GOLD, points: bars.map((b) => ({ time: b.timestamp, value: vp.poc })) },
    { step: 'vah', label: 'VAH', type: 'line', color: GREY, points: bars.map((b) => ({ time: b.timestamp, value: vp.vah })) },
    { step: 'val', label: 'VAL', type: 'line', color: GREY, points: bars.map((b) => ({ time: b.timestamp, value: vp.val })) },
  ];
  return { name: 'Volume Profile', short_name: 'VP', pane: 'overlay', precision: 2, plots, bars: bars.length };
}

/** Relative-strength-vs-SPY (% outperformance) as a sub-pane line. */
export function buildRsResult(full: ChartFullResponse): ComputeResult | null {
  const pts = (full.rs_vs_spy || [])
    .filter((p) => Number.isFinite(p.value))
    .map((p) => ({ time: p.time * 1000, value: p.value }));
  if (!pts.length) return null;
  return {
    name: 'RS vs SPY',
    short_name: 'RS%',
    pane: 'separate',
    precision: 3,
    plots: [{ step: 'rs', label: 'RS% vs SPY', type: 'line', color: GREEN, points: pts }],
    bars: pts.length,
  };
}
