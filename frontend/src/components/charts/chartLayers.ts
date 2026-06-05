// chartLayers — turn the server-enriched /full payload into render-ready results
// for the KLineChart custom-indicator adapter (see customIndicators.addSpecIndicator).
//
// No client-side TA: the backend computed everything. We only shape it:
// - levels (fib + S/R) → constant horizontal lines on the candle pane
// - markers (buy/sell + insider) → circle dots at the relevant bars
// - RS-vs-SPY → a line in its own sub-pane
// All /full times are epoch SECONDS; KLineChart bars are ms (×1000 to align).

import type { KLineData } from 'klinecharts';

import type { ComputeResult, ComputedPlot } from '../../lib/indicatorApi';
import type { ChartFullResponse } from '../../lib/chartFullApi';

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
