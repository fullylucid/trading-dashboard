// ChartWorkspace — the centerpiece: a TradingView-style chart workspace.
//
// Three view modes (mode switcher):
//   1. INDIVIDUAL — one ticker, full candlestick chart with every AI layer.
//   2. COMPARE    — 2+ tickers (and/or SPY) overlaid as normalized % lines.
//   3. PORTFOLIO  — the portfolio-weighted equity series (blended, normalized).
//
// Four toggleable CUSTOM-AI INDICATOR layers (all sourced from the server's
// `/api/chart/{symbol}/full` endpoint — the frontend never recomputes TA):
//   a) STRUCTURE  — Fib + S/R + pattern/divergence structure overlays.
//   b) MOMENTUM   — confluence oscillator sub-pane (RSI + MACD) + signal markers
//                   (MACD crosses, RSI divergence).
//   c) RELATIVE   — insider-buy markers + RS-vs-SPY line + on-demand AI read.
//   d) CONTEXT    — regime + sector-rotation background shading.
//
// All indicator math is delegated to the tested backend analytics modules and
// arrives pre-marshalled; this component marshals it onto MultiPaneChart (the
// workspace chart engine) and never reinvents signal logic. A ticker picker
// (driven by the scan's holdings), a live-price badge, and a clean indicator
// toolbar round out the cockpit.

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { UTCTimestamp } from 'lightweight-charts';

import MultiPaneChart from './MultiPaneChart';
import { computeFibLevels } from './FibonacciOverlay';
import { levelsFromScanSignals } from './SupportResistanceOverlay';
import { useLivePrice } from './useLivePrice';
import {
  getChartFull,
  getChartPortfolio,
  getAiRead,
} from '../../lib/chartApi';
import type {
  ChartFullResponse,
  ChartPortfolioResponse,
  ChartRange,
  AiReadLevel,
  AiReadResponse,
  SignalEventMarker,
} from '../../lib/chartApi';
import type {
  Candle,
  ChartTheme,
  CompareSeries,
  IndicatorPoint,
  IndicatorSeries,
  Marker,
  MultiPaneChartHandle,
  MultiPaneChartMode,
  OverlayLevel,
  ShadeBand,
} from './types';

// ---------------------------------------------------------------------------
// Public props
// ---------------------------------------------------------------------------

export type WorkspaceMode = 'individual' | 'compare' | 'portfolio';

export interface ChartWorkspaceProps {
  /** Candidate tickers for the picker (typically the scan's ranked holdings). */
  tickers: string[];
  /** Initially-selected ticker for INDIVIDUAL/COMPARE. Defaults to first ticker. */
  initialSymbol?: string;
  /** Starting view mode. Defaults to `'individual'`. */
  initialMode?: WorkspaceMode;
  /** Default history range. Defaults to `'1y'`. */
  initialRange?: ChartRange;
  theme?: ChartTheme;
  /** Main pane height in px. Defaults to 520. */
  height?: number;
  className?: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const RANGE_OPTIONS: ChartRange[] = ['5d', '1m', '3m', '6m', '1y', '2y', '5y', 'max'];

/** A small benchmark/sector menu offered in COMPARE mode alongside holdings. */
const COMPARE_BENCHMARKS: string[] = ['SPY', 'QQQ', 'IWM'];

/** Distinct line colors for COMPARE mode (benchmark always dashed/dimmed). */
const COMPARE_COLORS: string[] = [
  '#42a5f5',
  '#ef5350',
  '#26a69a',
  '#ffa726',
  '#c792ea',
  '#66bb6a',
  '#ec407a',
  '#29b6f6',
];

const AI_READ_COLORS: Record<AiReadLevel['kind'], string> = {
  support: '#26a69a',
  resistance: '#ef5350',
  target: '#42a5f5',
  stop: '#ffa726',
  fib: '#c792ea',
  pivot: '#787b86',
};

interface Palette {
  panel: string;
  border: string;
  text: string;
  sub: string;
  accent: string;
}

const PALETTES: Record<ChartTheme, Palette> = {
  dark: {
    panel: '#0b0e11',
    border: '#2a2e39',
    text: '#d1d4dc',
    sub: '#787b86',
    accent: '#42a5f5',
  },
  light: {
    panel: '#ffffff',
    border: '#d6dcde',
    text: '#131722',
    sub: '#6a7079',
    accent: '#2962ff',
  },
};

// ---------------------------------------------------------------------------
// Indicator-layer toggles (a/b/c/d). Defaults: structure + momentum on.
// ---------------------------------------------------------------------------

interface LayerToggles {
  /** (a) Fib + S/R + structure overlays. */
  structure: boolean;
  /** (b) Confluence oscillator sub-pane + signal markers. */
  momentum: boolean;
  /** (c) Insider markers + RS-vs-SPY line + AI read. */
  relative: boolean;
  /** (d) Regime + sector-rotation background shading. */
  context: boolean;
}

const DEFAULT_LAYERS: LayerToggles = {
  structure: true,
  momentum: true,
  relative: false,
  context: false,
};

// ---------------------------------------------------------------------------
// Marshalling helpers (pure) — server payload -> chart-engine inputs.
// ---------------------------------------------------------------------------

function asTime(epochSeconds: number): UTCTimestamp {
  return epochSeconds as UTCTimestamp;
}

/** (a) Structure overlays: server Fib + S/R, falling back to local Fib. */
function buildStructureOverlays(full: ChartFullResponse): OverlayLevel[] {
  const out: OverlayLevel[] = [];

  // Support / resistance from the server's pivot block.
  const sr = full.overlays.support_resistance;
  if (sr) {
    out.push(...levelsFromScanSignals(sr));
  }

  // Fibonacci: prefer server-anchored levels; fall back to local candle derivation.
  const fib = full.overlays.fib_levels;
  if (fib && fib.swing_high != null && fib.swing_low != null) {
    const anchor = '#787b86';
    const retr = '#c792ea';
    const ext = '#5c6bc0';
    out.push({
      id: 'fib-swing-high',
      price: fib.swing_high,
      label: `Swing H ${fib.swing_high.toFixed(2)}`,
      color: anchor,
      lineStyle: 'solid',
      lineWidth: 1,
    });
    out.push({
      id: 'fib-swing-low',
      price: fib.swing_low,
      label: `Swing L ${fib.swing_low.toFixed(2)}`,
      color: anchor,
      lineStyle: 'solid',
      lineWidth: 1,
    });
    for (const [ratio, price] of Object.entries(fib.retracements)) {
      const r = Number(ratio);
      out.push({
        id: `fib-ret-${ratio}`,
        price,
        label: `Fib ${(r * 100).toFixed(1)}% ${price.toFixed(2)}`,
        color: retr,
        lineStyle: Math.abs(r - 0.618) < 1e-6 ? 'solid' : 'dashed',
        lineWidth: Math.abs(r - 0.618) < 1e-6 ? 2 : 1,
      });
    }
    for (const [ratio, price] of Object.entries(fib.extensions)) {
      const r = Number(ratio);
      out.push({
        id: `fib-ext-${ratio}`,
        price,
        label: `Fib ${(r * 100).toFixed(1)}% ext ${price.toFixed(2)}`,
        color: ext,
        lineStyle: 'dotted',
        lineWidth: 1,
      });
    }
  } else {
    // No server swing → derive locally off the candles.
    out.push(...computeFibLevels(full.candles));
  }

  return out;
}

/** (b) Momentum: RSI + MACD oscillator sub-panes from the server series. */
function buildMomentumIndicators(full: ChartFullResponse): IndicatorSeries[] {
  const series: IndicatorSeries[] = [];

  const rsi = full.indicators.rsi;
  if (rsi.length > 0) {
    series.push({
      id: 'rsi',
      label: 'RSI(14)',
      kind: 'line',
      paneId: 'rsi',
      paneHeight: 110,
      color: '#ab47bc',
      lineWidth: 2,
      data: rsi.map((p): IndicatorPoint => ({ time: asTime(p.time), value: p.value })),
      guides: [
        { value: 70, color: 'rgba(239,83,80,0.6)', label: '70', lineStyle: 'dotted' },
        { value: 30, color: 'rgba(38,166,154,0.6)', label: '30', lineStyle: 'dotted' },
      ],
    });
  }

  const macd = full.indicators.macd;
  if (macd.length > 0) {
    series.push({
      id: 'macd-hist',
      label: 'MACD hist',
      kind: 'histogram',
      paneId: 'macd',
      paneHeight: 120,
      data: macd.map((p): IndicatorPoint => ({ time: asTime(p.time), value: p.hist })),
    });
    series.push({
      id: 'macd-line',
      label: 'MACD',
      kind: 'line',
      paneId: 'macd',
      color: '#42a5f5',
      lineWidth: 2,
      data: macd.map((p): IndicatorPoint => ({ time: asTime(p.time), value: p.macd })),
      guides: [{ value: 0, color: 'rgba(120,123,134,0.5)', lineStyle: 'dotted' }],
    });
    series.push({
      id: 'macd-signal',
      label: 'signal',
      kind: 'line',
      paneId: 'macd',
      color: '#ffa726',
      lineWidth: 1,
      data: macd.map((p): IndicatorPoint => ({ time: asTime(p.time), value: p.signal })),
    });
  }

  return series;
}

/** (b) Signal markers: MACD crosses + RSI divergence, anchored to bar time. */
function buildSignalMarkers(events: SignalEventMarker[]): Marker[] {
  return events.map((e, i): Marker => {
    const bullish = /bull/i.test(e.label);
    const bearish = /bear/i.test(e.label);
    if (e.type === 'divergence') {
      return {
        id: `sig-div-${i}`,
        time: asTime(e.time),
        position: bullish ? 'belowBar' : 'aboveBar',
        shape: bullish ? 'arrowUp' : 'arrowDown',
        color: bullish ? '#26a69a' : '#ef5350',
        text: e.label,
        size: 2,
      };
    }
    // cross / breakout
    return {
      id: `sig-${e.type}-${i}`,
      time: asTime(e.time),
      position: bullish ? 'belowBar' : bearish ? 'aboveBar' : 'inBar',
      shape: bullish ? 'arrowUp' : bearish ? 'arrowDown' : 'circle',
      color: bullish ? '#26a69a' : bearish ? '#ef5350' : '#787b86',
      text: e.label,
    };
  });
}

/** (c) Insider-buy markers (cluster windows from EDGAR Form-4). */
function buildInsiderMarkers(full: ChartFullResponse): Marker[] {
  return full.markers.insider_buys.map((m, i): Marker => ({
    id: `insider-${i}`,
    time: asTime(m.time),
    position: 'belowBar',
    shape: 'square',
    color: '#ffd54f',
    text: m.label,
    size: 2,
  }));
}

/** (c) RS-vs-SPY line, drawn in its own sub-pane (% outperformance). */
function buildRsIndicator(full: ChartFullResponse): IndicatorSeries | null {
  if (full.rs_vs_spy.length === 0) return null;
  return {
    id: 'rs-vs-spy',
    label: 'RS vs SPY (%)',
    kind: 'baseline',
    paneId: 'rs',
    paneHeight: 100,
    baseValue: 0,
    data: full.rs_vs_spy.map((p): IndicatorPoint => ({ time: asTime(p.time), value: p.value })),
    guides: [{ value: 0, color: 'rgba(120,123,134,0.5)', lineStyle: 'dotted' }],
  };
}

/** (c) AI-read flagged levels -> overlays. */
function aiLevelsToOverlays(levels: AiReadLevel[]): OverlayLevel[] {
  return levels.map((lvl, i): OverlayLevel => ({
    id: `ai-${i}-${lvl.kind}`,
    price: lvl.price,
    label: `AI ${lvl.label}`,
    color: AI_READ_COLORS[lvl.kind],
    lineStyle: 'large-dashed',
    lineWidth: 2,
  }));
}

/** (d) Context shading: a regime band + a sector-rotation band behind price. */
function buildContextBands(full: ChartFullResponse): ShadeBand[] {
  const bands: ShadeBand[] = [];
  if (full.candles.length === 0) return bands;
  const fromTime = full.candles[0].time;

  const regime = full.context.regime;
  if (regime && (regime.label || regime.regime_class)) {
    const cls = (regime.regime_class ?? '').toLowerCase();
    const trend = (regime.trend_direction ?? '').toLowerCase();
    let color = 'rgba(120,123,134,0.06)';
    if (cls.includes('bull') || trend.includes('up')) color = 'rgba(38,166,154,0.08)';
    else if (cls.includes('bear') || trend.includes('down')) color = 'rgba(239,83,80,0.08)';
    else if (cls.includes('volat') || (regime.volatility_regime ?? '').toLowerCase().includes('high'))
      color = 'rgba(255,167,38,0.08)';
    bands.push({
      id: 'regime',
      fromTime,
      color,
      label: regime.label ?? regime.regime_class ?? 'Regime',
    });
  }

  const rot = full.context.sector_rotation;
  if (rot && rot.status && rot.status !== 'neutral') {
    bands.push({
      id: 'sector-rotation',
      fromTime,
      color:
        rot.status === 'rotating-IN'
          ? 'rgba(38,166,154,0.05)'
          : 'rgba(239,83,80,0.05)',
      label: `${rot.sector ?? 'Sector'} ${rot.status}`,
    });
  }

  return bands;
}

function formatPrice(price: number | null): string {
  return price == null ? '—' : price.toFixed(2);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ChartWorkspace(props: ChartWorkspaceProps): React.ReactElement {
  const {
    tickers,
    initialSymbol,
    initialMode = 'individual',
    initialRange = '1y',
    theme = 'dark',
    height = 520,
    className,
  } = props;

  const palette = PALETTES[theme];

  const tickerList = useMemo<string[]>(
    () => Array.from(new Set(tickers.map((t) => t.toUpperCase()))),
    [tickers],
  );

  const [mode, setMode] = useState<WorkspaceMode>(initialMode);
  const [range, setRange] = useState<ChartRange>(initialRange);
  const [symbol, setSymbol] = useState<string>(
    (initialSymbol ?? tickerList[0] ?? '').toUpperCase(),
  );
  const [layers, setLayers] = useState<LayerToggles>(DEFAULT_LAYERS);

  // COMPARE selection (a set of symbols + benchmarks overlaid).
  const [compareSyms, setCompareSyms] = useState<string[]>(() =>
    [tickerList[0], 'SPY'].filter((s): s is string => Boolean(s)),
  );

  // Loaded server payloads.
  const [full, setFull] = useState<ChartFullResponse | null>(null);
  const [compareFulls, setCompareFulls] = useState<Record<string, ChartFullResponse>>({});
  const [portfolio, setPortfolio] = useState<ChartPortfolioResponse | null>(null);

  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // AI read state (INDIVIDUAL mode only).
  const [aiRead, setAiRead] = useState<AiReadResponse | null>(null);
  const [aiLoading, setAiLoading] = useState<boolean>(false);
  const [aiError, setAiError] = useState<string | null>(null);

  const chartRef = useRef<MultiPaneChartHandle | null>(null);

  // Live price for the active symbol (individual mode badge). Compare/portfolio
  // do not subscribe (the badge is per-symbol).
  const liveSymbol = mode === 'individual' ? symbol : null;
  const live = useLivePrice(liveSymbol || null);

  const chartMode: MultiPaneChartMode = mode === 'individual' ? 'price' : 'compare';

  // ----- keep symbol valid as the ticker list changes -----
  useEffect(() => {
    if (tickerList.length === 0) return;
    if (!tickerList.includes(symbol)) setSymbol(tickerList[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tickerList]);

  // ----- INDIVIDUAL: fetch /full for the selected symbol -----
  useEffect(() => {
    if (mode !== 'individual' || !symbol) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setAiRead(null);
    setAiError(null);
    getChartFull(symbol, range)
      .then((res) => {
        if (!cancelled) setFull(res);
      })
      .catch(() => {
        if (!cancelled) setError(`Could not load ${symbol}.`);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [mode, symbol, range]);

  // ----- COMPARE: fetch /full for each selected symbol -----
  useEffect(() => {
    if (mode !== 'compare' || compareSyms.length === 0) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all(
      compareSyms.map((s) =>
        getChartFull(s, range)
          .then((res): [string, ChartFullResponse | null] => [s, res])
          .catch((): [string, ChartFullResponse | null] => [s, null]),
      ),
    )
      .then((entries) => {
        if (cancelled) return;
        const next: Record<string, ChartFullResponse> = {};
        for (const [s, res] of entries) {
          if (res) next[s] = res;
        }
        setCompareFulls(next);
        if (Object.keys(next).length === 0) setError('No comparison data available.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [mode, compareSyms, range]);

  // ----- PORTFOLIO: fetch the blended equity series -----
  useEffect(() => {
    if (mode !== 'portfolio') return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getChartPortfolio(range)
      .then((res) => {
        if (!cancelled) setPortfolio(res);
      })
      .catch(() => {
        if (!cancelled) setError('Could not load portfolio series.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [mode, range]);

  // ----- live tick -> push onto the most-recent candle (individual mode) -----
  useEffect(() => {
    if (mode !== 'individual') return;
    if (live.price == null || !full || full.candles.length === 0) return;
    const last = full.candles[full.candles.length - 1];
    chartRef.current?.updateLastCandle({
      time: last.time,
      open: last.open,
      high: Math.max(last.high, live.price),
      low: Math.min(last.low, live.price),
      close: live.price,
      volume: last.volume,
    });
  }, [live.price, mode, full]);

  // ----- derived chart inputs (per mode + layer toggles) -----
  const candles: Candle[] = useMemo(() => {
    if (mode === 'individual') return full?.candles ?? [];
    return [];
  }, [mode, full]);

  const overlays = useMemo<OverlayLevel[]>(() => {
    if (mode !== 'individual' || !full) return [];
    const merged: OverlayLevel[] = [];
    if (layers.structure) merged.push(...buildStructureOverlays(full));
    if (layers.relative && aiRead) merged.push(...aiLevelsToOverlays(aiRead.levels));
    return merged;
  }, [mode, full, layers.structure, layers.relative, aiRead]);

  const indicators = useMemo<IndicatorSeries[]>(() => {
    if (mode !== 'individual' || !full) return [];
    const out: IndicatorSeries[] = [];
    if (layers.momentum) out.push(...buildMomentumIndicators(full));
    if (layers.relative) {
      const rs = buildRsIndicator(full);
      if (rs) out.push(rs);
    }
    return out;
  }, [mode, full, layers.momentum, layers.relative]);

  const markers = useMemo<Marker[]>(() => {
    if (mode !== 'individual' || !full) return [];
    const out: Marker[] = [];
    if (layers.momentum) out.push(...buildSignalMarkers(full.markers.signal_events));
    if (layers.relative) out.push(...buildInsiderMarkers(full));
    return out;
  }, [mode, full, layers.momentum, layers.relative]);

  const shadeBands = useMemo<ShadeBand[]>(() => {
    if (mode !== 'individual' || !full || !layers.context) return [];
    return buildContextBands(full);
  }, [mode, full, layers.context]);

  // COMPARE: normalized % lines from each symbol's candles + benchmark flag.
  const compareSeries = useMemo<CompareSeries[]>(() => {
    if (mode !== 'compare') return [];
    return compareSyms
      .map((s, i): CompareSeries | null => {
        const data = compareFulls[s];
        if (!data) return null;
        const isBench = COMPARE_BENCHMARKS.includes(s);
        return {
          symbol: s,
          color: COMPARE_COLORS[i % COMPARE_COLORS.length],
          isBenchmark: isBench,
          data: data.candles.map((c): IndicatorPoint => ({ time: c.time, value: c.close })),
        };
      })
      .filter((x): x is CompareSeries => x !== null);
  }, [mode, compareSyms, compareFulls]);

  // PORTFOLIO: blended return line as a single normalized compare series.
  const portfolioSeries = useMemo<CompareSeries[]>(() => {
    if (mode !== 'portfolio' || !portfolio) return [];
    if (portfolio.returns.length === 0) return [];
    // The returns series is already rebased to 0% at start; feed close=value+? —
    // we hand the equity series (growth of $1) so normalizeToPercent rebases it
    // cleanly to "% from start", which equals the cumulative return.
    const src = portfolio.equity.length > 0 ? portfolio.equity : portfolio.returns;
    return [
      {
        symbol: 'PORTFOLIO',
        color: '#42a5f5',
        lineWidth: 2,
        data: src.map((p): IndicatorPoint => ({ time: asTime(p.time), value: p.value })),
      },
    ];
  }, [mode, portfolio]);

  const activeCompareSeries =
    mode === 'portfolio' ? portfolioSeries : compareSeries;

  // ----- AI read handler (individual) -----
  const handleAiRead = useCallback(async (): Promise<void> => {
    if (!symbol) return;
    setAiLoading(true);
    setAiError(null);
    try {
      const ctx: Record<string, unknown> = {};
      if (full?.confluence) ctx.confluence = full.confluence;
      if (full?.context) ctx.context = full.context;
      const res = await getAiRead(symbol, { timeframe: range, context: ctx });
      setAiRead(res);
    } catch {
      setAiError('AI read failed. Try again.');
    } finally {
      setAiLoading(false);
    }
  }, [symbol, range, full]);

  // ----- live-badge math -----
  const lastClose =
    mode === 'individual' && full && full.candles.length > 0
      ? full.candles[full.candles.length - 1].close
      : null;
  const badgePrice = live.price ?? lastClose;
  const change = badgePrice != null && lastClose != null ? badgePrice - lastClose : null;
  const changePct =
    change != null && lastClose != null && lastClose !== 0
      ? (change / lastClose) * 100
      : null;
  const up = change != null && change >= 0;

  const confluence = full?.confluence ?? null;

  // ----- toggle helpers -----
  const toggleLayer = useCallback((key: keyof LayerToggles): void => {
    setLayers((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  const toggleCompareSym = useCallback((s: string): void => {
    setCompareSyms((prev) =>
      prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s],
    );
  }, []);

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div
      className={className}
      style={{
        background: palette.panel,
        border: `1px solid ${palette.border}`,
        borderRadius: 8,
        overflow: 'hidden',
        color: palette.text,
        fontFamily: 'monospace',
      }}
    >
      {/* ---- header: mode switch + symbol + live badge + range ---- */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '8px 12px',
          borderBottom: `1px solid ${palette.border}`,
          flexWrap: 'wrap',
        }}
      >
        <ModeSwitcher mode={mode} onChange={setMode} palette={palette} />

        {mode === 'individual' && (
          <>
            <select
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              style={selectStyle(palette)}
              aria-label="Ticker"
            >
              {tickerList.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span
                title={live.connected ? 'Live' : 'Disconnected'}
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: live.connected ? '#26a69a' : palette.sub,
                  display: 'inline-block',
                }}
              />
              <span style={{ fontSize: 18, fontWeight: 700 }}>{formatPrice(badgePrice)}</span>
              {changePct != null && change != null && (
                <span style={{ fontSize: 12, color: up ? '#26a69a' : '#ef5350' }}>
                  {up ? '+' : ''}
                  {change.toFixed(2)} ({up ? '+' : ''}
                  {changePct.toFixed(2)}%)
                </span>
              )}
            </div>
          </>
        )}

        {mode === 'portfolio' && portfolio && (
          <span style={{ fontSize: 12, color: palette.sub }}>
            {portfolio.holdings.length} holdings
            {portfolio.skipped.length > 0 ? ` · ${portfolio.skipped.length} skipped` : ''}
          </span>
        )}

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 11, color: palette.sub }}>Range</span>
          <select
            value={range}
            onChange={(e) => setRange(e.target.value as ChartRange)}
            style={selectStyle(palette)}
            aria-label="Range"
          >
            {RANGE_OPTIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* ---- COMPARE ticker chooser ---- */}
      {mode === 'compare' && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '6px 12px',
            borderBottom: `1px solid ${palette.border}`,
            flexWrap: 'wrap',
            fontSize: 12,
          }}
        >
          <span style={{ color: palette.sub, marginRight: 4 }}>Compare:</span>
          {[...COMPARE_BENCHMARKS, ...tickerList].map((s, i) => {
            const active = compareSyms.includes(s);
            const color = active
              ? COMPARE_COLORS[compareSyms.indexOf(s) % COMPARE_COLORS.length]
              : palette.sub;
            return (
              <button
                key={`${s}-${i}`}
                type="button"
                onClick={() => toggleCompareSym(s)}
                style={chipStyle(active, color, palette)}
              >
                {s}
              </button>
            );
          })}
        </div>
      )}

      {/* ---- indicator toolbar (individual only) ---- */}
      {mode === 'individual' && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '6px 12px',
            borderBottom: `1px solid ${palette.border}`,
            fontSize: 12,
            flexWrap: 'wrap',
          }}
        >
          <LayerToggle
            label="Structure"
            title="Fib + S/R + structure overlays"
            on={layers.structure}
            onClick={() => toggleLayer('structure')}
            palette={palette}
          />
          <LayerToggle
            label="Momentum"
            title="RSI/MACD oscillators + signal markers"
            on={layers.momentum}
            onClick={() => toggleLayer('momentum')}
            palette={palette}
          />
          <LayerToggle
            label="Relative"
            title="Insider markers + RS-vs-SPY + AI read"
            on={layers.relative}
            onClick={() => toggleLayer('relative')}
            palette={palette}
          />
          <LayerToggle
            label="Context"
            title="Regime + sector-rotation shading"
            on={layers.context}
            onClick={() => toggleLayer('context')}
            palette={palette}
          />

          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
            {confluence && (
              <span
                title="Current confluence read"
                style={{
                  fontSize: 11,
                  padding: '2px 8px',
                  borderRadius: 10,
                  border: `1px solid ${palette.border}`,
                  color:
                    confluence.direction === 'bullish'
                      ? '#26a69a'
                      : confluence.direction === 'bearish'
                        ? '#ef5350'
                        : palette.sub,
                }}
              >
                {confluence.bucket.toUpperCase()} {confluence.confidence.toFixed(0)} ·{' '}
                {confluence.direction}
              </span>
            )}
            {aiRead && (
              <button
                type="button"
                onClick={() => {
                  setAiRead(null);
                  setAiError(null);
                }}
                style={buttonStyle(palette.border, palette.text, false)}
              >
                Clear AI
              </button>
            )}
            <button
              type="button"
              onClick={() => void handleAiRead()}
              disabled={aiLoading || !layers.relative}
              title={layers.relative ? 'On-demand AI technical read' : 'Enable Relative layer first'}
              style={buttonStyle(palette.accent, palette.panel, true)}
            >
              {aiLoading ? 'Reading…' : 'AI read'}
            </button>
          </div>
        </div>
      )}

      {/* ---- status line ---- */}
      {(loading || error) && (
        <div
          style={{
            padding: '6px 12px',
            fontSize: 12,
            color: error ? '#ef5350' : palette.sub,
            borderBottom: `1px solid ${palette.border}`,
          }}
        >
          {error ?? 'Loading…'}
        </div>
      )}

      {/* ---- the chart engine ---- */}
      <MultiPaneChart
        ref={chartRef}
        mode={chartMode}
        candles={candles}
        overlays={overlays}
        indicators={indicators}
        markers={markers}
        shadeBands={shadeBands}
        compareSeries={activeCompareSeries}
        showVolume={mode === 'individual'}
        theme={theme}
        height={height}
      />

      {/* ---- empty-portfolio note ---- */}
      {mode === 'portfolio' && portfolio && portfolio.equity.length === 0 && !loading && (
        <div style={{ padding: '8px 12px', fontSize: 12, color: palette.sub }}>
          No portfolio series available
          {portfolio.note === 'no_holdings' ? ' (no holdings).' : '.'}
        </div>
      )}

      {/* ---- AI read result ---- */}
      {mode === 'individual' && (aiError || aiRead) && (
        <div
          style={{
            padding: '8px 12px',
            borderTop: `1px solid ${palette.border}`,
            fontSize: 12,
            lineHeight: 1.5,
          }}
        >
          {aiError && <span style={{ color: '#ef5350' }}>{aiError}</span>}
          {aiRead && (
            <div>
              <div style={{ marginBottom: 4 }}>
                <span style={{ fontWeight: 700 }}>AI read</span>
                {aiRead.bias && (
                  <span
                    style={{
                      marginLeft: 8,
                      color:
                        aiRead.bias === 'bullish'
                          ? '#26a69a'
                          : aiRead.bias === 'bearish'
                            ? '#ef5350'
                            : palette.sub,
                    }}
                  >
                    {aiRead.bias}
                  </span>
                )}
              </div>
              <div>{aiRead.thesis}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface ModeSwitcherProps {
  mode: WorkspaceMode;
  onChange: (m: WorkspaceMode) => void;
  palette: Palette;
}

function ModeSwitcher(props: ModeSwitcherProps): React.ReactElement {
  const { mode, onChange, palette } = props;
  const modes: Array<{ key: WorkspaceMode; label: string }> = [
    { key: 'individual', label: 'Individual' },
    { key: 'compare', label: 'Compare' },
    { key: 'portfolio', label: 'Portfolio' },
  ];
  return (
    <div
      style={{
        display: 'inline-flex',
        border: `1px solid ${palette.border}`,
        borderRadius: 6,
        overflow: 'hidden',
      }}
    >
      {modes.map((m) => {
        const active = m.key === mode;
        return (
          <button
            key={m.key}
            type="button"
            onClick={() => onChange(m.key)}
            style={{
              background: active ? palette.accent : 'transparent',
              color: active ? palette.panel : palette.text,
              border: 'none',
              padding: '4px 12px',
              fontSize: 12,
              fontFamily: 'monospace',
              cursor: 'pointer',
              fontWeight: active ? 700 : 400,
            }}
          >
            {m.label}
          </button>
        );
      })}
    </div>
  );
}

interface LayerToggleProps {
  label: string;
  title: string;
  on: boolean;
  onClick: () => void;
  palette: Palette;
}

function LayerToggle(props: LayerToggleProps): React.ReactElement {
  const { label, title, on, onClick, palette } = props;
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 5,
        background: on ? 'rgba(66,165,245,0.12)' : 'transparent',
        border: `1px solid ${on ? palette.accent : palette.border}`,
        color: on ? palette.text : palette.sub,
        borderRadius: 4,
        padding: '3px 9px',
        fontSize: 12,
        fontFamily: 'monospace',
        cursor: 'pointer',
      }}
    >
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: 2,
          background: on ? palette.accent : 'transparent',
          border: `1px solid ${on ? palette.accent : palette.sub}`,
          display: 'inline-block',
        }}
      />
      {label}
    </button>
  );
}

function selectStyle(palette: Palette): React.CSSProperties {
  return {
    background: palette.panel,
    color: palette.text,
    border: `1px solid ${palette.border}`,
    borderRadius: 4,
    padding: '3px 8px',
    fontSize: 12,
    fontFamily: 'monospace',
    cursor: 'pointer',
  };
}

function chipStyle(active: boolean, color: string, palette: Palette): React.CSSProperties {
  return {
    background: active ? `${color}22` : 'transparent',
    color: active ? color : palette.sub,
    border: `1px solid ${active ? color : palette.border}`,
    borderRadius: 12,
    padding: '2px 10px',
    fontSize: 12,
    fontFamily: 'monospace',
    cursor: 'pointer',
  };
}

function buttonStyle(bg: string, fg: string, filled: boolean): React.CSSProperties {
  return {
    background: filled ? bg : 'transparent',
    color: filled ? fg : bg,
    border: `1px solid ${bg}`,
    borderRadius: 4,
    padding: '3px 10px',
    fontSize: 12,
    fontFamily: 'monospace',
    cursor: 'pointer',
  };
}

export default ChartWorkspace;
