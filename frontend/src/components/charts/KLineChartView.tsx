/**
 * KLineChartView — the Charts tab's chart engine, built on KLineChart (Apache-2.0).
 *
 * Replaces the old Lightweight-Charts ChartWorkspace on the Charts tab (that
 * workspace lives on — PortfolioScan still embeds it). KLineChart ships the
 * batteries we want out of the box: candles + volume, a stack of built-in
 * indicators (MA / BOLL on the candle pane; VOL / MACD / RSI as sub-panes), and
 * interactive drawing tools — all themed to the terminal-green look.
 *
 * Data comes from the existing backend OHLCV feed via `fetchKLineData` (see
 * ../../lib/klineApi). This component owns the chart instance, the indicator
 * toggles, and the drawing toolbar; the parent (Charts page) owns symbol +
 * timeframe selection and passes them down as props.
 */

import { useEffect, useRef, useState } from 'react';
import { ActionType, dispose, init } from 'klinecharts';
import type { Chart, DeepPartial, KLineData, Styles } from 'klinecharts';

import { TIMEFRAMES, fetchKLineData, type Resolution } from '../../lib/klineApi';
import {
  computeIndicator,
  listArsenal,
  saveToArsenal,
  type ArsenalItem,
  type IndicatorSpec,
} from '../../lib/indicatorApi';
import {
  addSpecIndicator,
  removeSpecIndicator,
  type CustomHandle,
} from './customIndicators';
import { EXAMPLE_SPECS } from './exampleSpecs';
import { fetchChartFull, type ChartFullResponse } from '../../lib/chartFullApi';
import {
  buildLevelsResult,
  buildMarkersResult,
  buildRsResult,
  buildVolumeProfileLevels,
  computeVolumeProfile,
  vwapSpec,
  VWAP_ANCHORED_COLOR,
  computeKeyLevels,
  buildKeyLevelsResult,
  sessionRuns,
  type VolumeProfile,
  type KeyLevel,
} from './chartLayers';
import MtfDashboard from './MtfDashboard';
import AlertsPanel from './AlertsPanel';
import ScreenerPanel from './ScreenerPanel';
import CopilotPanel from './CopilotPanel';

// Server-computed layers from /api/chart/{symbol}/full (re-homed onto KLineChart).
const LAYER_BUILDERS: Record<
  string,
  (full: ChartFullResponse, bars: KLineData[]) => import('../../lib/indicatorApi').ComputeResult | null
> = {
  Levels: buildLevelsResult,
  Signals: buildMarkersResult,
  RS: (full) => buildRsResult(full),
};
const LAYER_NAMES = ['Levels', 'Signals', 'RS'] as const;

const GREEN = '#00ff41';
const RED = '#ff3b3b';
const GREEN_DIM = 'rgba(0,255,65,0.3)';
const GREEN_FAINT = 'rgba(0,255,65,0.08)';

// Terminal-green theme: green axes/text/grid/crosshair on black, candles green
// (up) / red (down) so the chart stays readable as a trading chart.
const THEME: DeepPartial<Styles> = {
  grid: {
    horizontal: { color: GREEN_FAINT },
    vertical: { color: GREEN_FAINT },
  },
  candle: {
    bar: {
      upColor: GREEN,
      downColor: RED,
      noChangeColor: '#888888',
      upBorderColor: GREEN,
      downBorderColor: RED,
      noChangeBorderColor: '#888888',
      upWickColor: GREEN,
      downWickColor: RED,
      noChangeWickColor: '#888888',
    },
    priceMark: {
      high: { color: GREEN },
      low: { color: GREEN },
      last: {
        upColor: GREEN,
        downColor: RED,
        noChangeColor: '#888888',
        text: { color: '#000000' },
      },
    },
    tooltip: {
      text: { color: GREEN, family: 'monospace' },
    },
  },
  indicator: {
    tooltip: { text: { color: GREEN, family: 'monospace' } },
  },
  xAxis: {
    axisLine: { color: GREEN_DIM },
    tickLine: { color: GREEN_DIM },
    tickText: { color: GREEN, family: 'monospace' },
  },
  yAxis: {
    axisLine: { color: GREEN_DIM },
    tickLine: { color: GREEN_DIM },
    tickText: { color: GREEN, family: 'monospace' },
  },
  crosshair: {
    horizontal: {
      line: { color: 'rgba(0,255,65,0.5)' },
      text: { color: '#000000', backgroundColor: GREEN, family: 'monospace' },
    },
    vertical: {
      line: { color: 'rgba(0,255,65,0.5)' },
      text: { color: '#000000', backgroundColor: GREEN, family: 'monospace' },
    },
  },
  separator: { color: GREEN_DIM },
};

// Indicators drawn ON the candle pane (overlays).
const OVERLAY_INDICATORS = ['MA', 'BOLL'] as const;
// Indicators that get their own stacked sub-pane.
const PANE_INDICATORS = ['VOL', 'MACD', 'RSI'] as const;
const ALL_INDICATORS = [...OVERLAY_INDICATORS, ...PANE_INDICATORS] as const;

// Built-in KLineChart drawing-tool overlay templates exposed in the toolbar.
const DRAW_TOOLS: { name: string; label: string }[] = [
  { name: 'segment', label: 'Trend' },
  { name: 'horizontalStraightLine', label: 'H-line' },
  { name: 'rayLine', label: 'Ray' },
  { name: 'priceLine', label: 'Price' },
  { name: 'fibonacciLine', label: 'Fib' },
  { name: 'rect', label: 'Rect' },
];

// Candle pane id is a KLineChart constant.
const CANDLE_PANE_ID = 'candle_pane';

interface Props {
  symbol: string;
  /** Starting timeframe; the component owns the selector after that. Default 'D'. */
  initialResolution?: Resolution;
  /** Show the built-in timeframe selector row. Default true. */
  showTimeframe?: boolean;
  /** CSS height for the chart canvas. Defaults to a tall, responsive pane. */
  height?: number | string;
  /** Custom specs to render on mount (e.g. a scout idea being demoed). */
  initialCustomSpecs?: { spec: IndicatorSpec; label: string }[];
}

function btnStyle(active: boolean): React.CSSProperties {
  return {
    background: active ? 'rgba(0,255,65,0.18)' : '#000',
    color: GREEN,
    border: `1px solid ${active ? GREEN : GREEN_DIM}`,
    fontFamily: 'monospace',
    fontSize: 12,
    padding: '4px 10px',
    cursor: 'pointer',
    borderRadius: 4,
    lineHeight: 1.4,
  };
}

const KLineChartView: React.FC<Props> = ({
  symbol,
  initialResolution = 'D',
  showTimeframe = true,
  height = '70vh',
  initialCustomSpecs,
}) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<Chart | null>(null);
  // Track which sub-pane each pane-indicator lives in so we can remove it.
  const paneIdsRef = useRef<Record<string, string>>({});
  const candleOverlaysRef = useRef<Set<string>>(new Set());

  const [resolution, setResolution] = useState<Resolution>(initialResolution);
  const [ready, setReady] = useState(false);
  const [enabled, setEnabled] = useState<Record<string, boolean>>({
    VOL: true,
    MA: true,
  });
  const [activeTool, setActiveTool] = useState<string | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading');
  const [errMsg, setErrMsg] = useState<string>('');
  const [barCount, setBarCount] = useState(0);

  // Custom (spec-driven) indicators. The currently-loaded bars are stashed so the
  // engine computes over exactly what's on screen; barsVersion bumps on each load
  // to trigger a recompute of every active custom indicator.
  const barsRef = useRef<KLineData[]>([]);
  const [barsVersion, setBarsVersion] = useState(0);
  const [customSpecs, setCustomSpecs] = useState<
    { key: string; spec: IndicatorSpec; label: string; error?: string }[]
  >(() => (initialCustomSpecs ?? []).map((s, i) => ({ key: `seed${i}`, spec: s.spec, label: s.label })));
  const customRenderedRef = useRef<Map<string, { handle: CustomHandle; version: number }>>(
    new Map(),
  );
  const customKeyRef = useRef(0);
  const [arsenal, setArsenal] = useState<ArsenalItem[]>([]);

  // Server-computed layers (fib/S-R levels, signal markers, RS-vs-SPY) from /full.
  const [layers, setLayers] = useState<Record<string, boolean>>({});
  const fullRef = useRef<ChartFullResponse | null>(null);
  const fullSymbolRef = useRef<string>('');
  const [fullVersion, setFullVersion] = useState(0);
  const layersRenderedRef = useRef<Map<string, { handle: CustomHandle; version: string }>>(new Map());
  const [showMtf, setShowMtf] = useState(false);
  const [showAlerts, setShowAlerts] = useState(false);
  const [showScreener, setShowScreener] = useState(false);
  const [showCopilot, setShowCopilot] = useState(false);
  // Volume Profile: POC/VA lines (reliable render) + a DOM histogram overlay.
  const [showVP, setShowVP] = useState(false);
  const [vpProfile, setVpProfile] = useState<VolumeProfile | null>(null);
  const [vpBars, setVpBars] = useState<{ top: number; height: number; widthPct: number; poc: boolean }[]>([]);
  const [vpTick, setVpTick] = useState(0); // bumped on zoom/scroll/resize to reposition the histogram
  const vpLevelsRef = useRef<CustomHandle | null>(null);
  // VWAP: session (cumsum over all bars) + anchored (cumsum from a clicked bar).
  const [showVwap, setShowVwap] = useState(false);
  const [vwapAnchor, setVwapAnchor] = useState<number | null>(null); // anchor bar timestamp (ms)
  const showVwapRef = useRef(false);
  const vwapRenderedRef = useRef<Map<string, { handle: CustomHandle; version: string }>>(new Map());
  // Auto key levels (prev D/W/M H-L, today open, 52w) from daily bars.
  const [showKeyLevels, setShowKeyLevels] = useState(false);
  const keyLevelsRef = useRef<CustomHandle | null>(null);
  const klCacheRef = useRef<{ symbol: string; levels: KeyLevel[] } | null>(null);
  // Session / kill-zone shading (intraday only) — vertical translucent bands.
  const [showSessions, setShowSessions] = useState(false);
  const [sessionRects, setSessionRects] = useState<{ left: number; width: number; color: string }[]>([]);
  const isIntraday = ['1', '5', '15', '60'].includes(resolution);

  // Load the saved-spec arsenal once (best-effort; empty if storage is down).
  useEffect(() => {
    let cancelled = false;
    listArsenal()
      .then((items) => !cancelled && setArsenal(items))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  // --- Init / dispose the chart instance (once). ---
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = init(el, { styles: THEME, locale: 'en-US' });
    if (!chart) return;
    chart.setPriceVolumePrecision(2, 0);
    chartRef.current = chart;
    setReady(true);

    const bumpVp = () => setVpTick((t) => t + 1);
    const onResize = () => {
      chart.resize();
      bumpVp();
    };
    window.addEventListener('resize', onResize);
    // Reposition the volume-profile histogram when the price axis moves.
    chart.subscribeAction(ActionType.OnZoom, bumpVp);
    chart.subscribeAction(ActionType.OnScroll, bumpVp);
    chart.subscribeAction(ActionType.OnVisibleRangeChange, bumpVp);
    // Bar click → set the anchored-VWAP anchor (only while VWAP is on).
    const onBarClick = (data?: unknown) => {
      if (!showVwapRef.current) return;
      const d = data as { timestamp?: number; kLineData?: { timestamp?: number }; data?: { timestamp?: number } };
      const ts = d?.timestamp ?? d?.kLineData?.timestamp ?? d?.data?.timestamp;
      if (typeof ts === 'number') setVwapAnchor(ts);
    };
    chart.subscribeAction(ActionType.OnCandleBarClick, onBarClick);
    return () => {
      window.removeEventListener('resize', onResize);
      chart.unsubscribeAction(ActionType.OnZoom, bumpVp);
      chart.unsubscribeAction(ActionType.OnScroll, bumpVp);
      chart.unsubscribeAction(ActionType.OnVisibleRangeChange, bumpVp);
      chart.unsubscribeAction(ActionType.OnCandleBarClick, onBarClick);
      dispose(el);
      chartRef.current = null;
      paneIdsRef.current = {};
      candleOverlaysRef.current.clear();
      customRenderedRef.current.clear();
      layersRenderedRef.current.clear();
      vpLevelsRef.current = null;
      vwapRenderedRef.current.clear();
      keyLevelsRef.current = null;
    };
  }, []);

  // --- Load data when symbol / timeframe changes. ---
  useEffect(() => {
    if (!ready) return;
    const chart = chartRef.current;
    if (!chart) return;
    const controller = new AbortController();
    setStatus('loading');
    setErrMsg('');
    fetchKLineData(symbol, resolution, controller.signal)
      .then((bars) => {
        if (controller.signal.aborted) return;
        chart.applyNewData(bars);
        barsRef.current = bars;
        setBarCount(bars.length);
        setStatus(bars.length === 0 ? 'empty' : 'ready');
        setBarsVersion((v) => v + 1); // triggers custom-indicator recompute
      })
      .catch((err) => {
        if (controller.signal.aborted || axiosCanceled(err)) return;
        setStatus('error');
        setErrMsg(err?.message || 'Failed to load chart data');
      });
    return () => controller.abort();
  }, [ready, symbol, resolution]);

  // --- Reconcile indicators with the toggle state. ---
  useEffect(() => {
    if (!ready) return;
    const chart = chartRef.current;
    if (!chart) return;

    for (const name of OVERLAY_INDICATORS) {
      const on = !!enabled[name];
      const present = candleOverlaysRef.current.has(name);
      if (on && !present) {
        chart.createIndicator(name, true, { id: CANDLE_PANE_ID });
        candleOverlaysRef.current.add(name);
      } else if (!on && present) {
        chart.removeIndicator(CANDLE_PANE_ID, name);
        candleOverlaysRef.current.delete(name);
      }
    }

    for (const name of PANE_INDICATORS) {
      const on = !!enabled[name];
      const paneId = paneIdsRef.current[name];
      if (on && !paneId) {
        const id = chart.createIndicator(name);
        if (id) paneIdsRef.current[name] = id;
      } else if (!on && paneId) {
        chart.removeIndicator(paneId);
        delete paneIdsRef.current[name];
      }
    }
  }, [ready, enabled]);

  // --- Fetch the server-enriched /full payload when a layer is on (once per symbol). ---
  useEffect(() => {
    if (!ready) return;
    const anyOn = LAYER_NAMES.some((n) => layers[n]);
    if (!anyOn) return;
    if (fullSymbolRef.current === symbol && fullRef.current) return; // cached
    const controller = new AbortController();
    fetchChartFull(symbol, '1y', controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        fullRef.current = data;
        fullSymbolRef.current = symbol;
        setFullVersion((v) => v + 1);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [ready, symbol, layers]);

  // Drop cached /full when the symbol changes so layers refetch for the new symbol.
  useEffect(() => {
    if (fullSymbolRef.current !== symbol) fullRef.current = null;
  }, [symbol]);

  // --- Reconcile server layers (levels / signals / RS) with toggle state + data. ---
  useEffect(() => {
    if (!ready) return;
    const chart = chartRef.current;
    if (!chart) return;
    const rendered = layersRenderedRef.current;
    const full = fullRef.current;
    const bars = barsRef.current;
    const version = `${barsVersion}:${fullVersion}`;

    for (const name of LAYER_NAMES) {
      const on = !!layers[name];
      const existing = rendered.get(name);
      if (!on) {
        if (existing) {
          removeSpecIndicator(chart, existing.handle);
          rendered.delete(name);
        }
        continue;
      }
      if (existing && existing.version === version) continue; // up to date
      if (!full || !bars.length) continue;
      const result = LAYER_BUILDERS[name](full, bars);
      if (existing) {
        removeSpecIndicator(chart, existing.handle);
        rendered.delete(name);
      }
      if (!result) continue; // no data for this layer
      const handle = addSpecIndicator(chart, `layer-${name}`, result);
      if (handle) rendered.set(name, { handle, version });
    }
  }, [ready, barsVersion, fullVersion, layers]);

  const toggleLayer = (name: string) => setLayers((prev) => ({ ...prev, [name]: !prev[name] }));

  // --- Volume Profile: compute from bars, render POC/VA lines (reliable), set profile for the histogram. ---
  useEffect(() => {
    if (!ready) return;
    const chart = chartRef.current;
    if (!chart) return;
    if (vpLevelsRef.current) {
      removeSpecIndicator(chart, vpLevelsRef.current);
      vpLevelsRef.current = null;
    }
    if (!showVP) {
      setVpProfile(null);
      setVpBars([]);
      return;
    }
    const vp = computeVolumeProfile(barsRef.current);
    setVpProfile(vp);
    if (vp) {
      const result = buildVolumeProfileLevels(vp, barsRef.current);
      if (result) vpLevelsRef.current = addSpecIndicator(chart, 'vp-levels', result);
    }
  }, [ready, barsVersion, showVP]);

  // --- Volume Profile histogram: map each bin to pixels (repositions on viewport change). ---
  useEffect(() => {
    const chart = chartRef.current;
    if (!showVP || !vpProfile || !chart) {
      setVpBars([]);
      return;
    }
    const points = vpProfile.bins.flatMap((b) => [{ value: b.high }, { value: b.low }]);
    const coords = chart.convertToPixel(points, { paneId: 'candle_pane' }) as Array<{ y?: number }>;
    const out: { top: number; height: number; widthPct: number; poc: boolean }[] = [];
    vpProfile.bins.forEach((b, i) => {
      const yHigh = coords[2 * i]?.y;
      const yLow = coords[2 * i + 1]?.y;
      if (yHigh == null || yLow == null || b.volume <= 0) return;
      out.push({
        top: yHigh,
        height: Math.max(1, yLow - yHigh),
        widthPct: vpProfile.maxVol > 0 ? (b.volume / vpProfile.maxVol) * 100 : 0,
        poc: b.mid === vpProfile.poc,
      });
    });
    setVpBars(out);
  }, [showVP, vpProfile, vpTick, barsVersion]);

  // --- Session / kill-zone shading: map each in-window bar run to x-pixel bands. ---
  useEffect(() => {
    const chart = chartRef.current;
    if (!showSessions || !isIntraday || !chart) {
      setSessionRects([]);
      return;
    }
    const bars = barsRef.current;
    if (!bars.length) {
      setSessionRects([]);
      return;
    }
    const rects: { left: number; width: number; color: string }[] = [];
    for (const s of sessionRuns(bars)) {
      for (const [startTs, endTs] of s.runs) {
        const coords = chart.convertToPixel(
          [{ timestamp: startTs }, { timestamp: endTs }],
          { paneId: 'candle_pane' },
        ) as Array<{ x?: number }>;
        const x0 = coords[0]?.x;
        const x1 = coords[1]?.x;
        if (x0 == null || x1 == null) continue;
        rects.push({ left: Math.min(x0, x1), width: Math.max(2, Math.abs(x1 - x0)), color: s.color });
      }
    }
    setSessionRects(rects);
  }, [showSessions, isIntraday, barsVersion, vpTick]);

  useEffect(() => {
    showVwapRef.current = showVwap;
  }, [showVwap]);

  // --- Auto key levels: daily-bar-derived horizontal lines (cached per symbol). ---
  useEffect(() => {
    if (!ready) return;
    const chart = chartRef.current;
    if (!chart) return;
    let aborted = false;
    const remove = () => {
      if (keyLevelsRef.current) {
        removeSpecIndicator(chart, keyLevelsRef.current);
        keyLevelsRef.current = null;
      }
    };
    if (!showKeyLevels) {
      remove();
      return;
    }
    (async () => {
      try {
        if (klCacheRef.current?.symbol !== symbol) {
          const daily = await fetchKLineData(symbol, 'D');
          if (aborted) return;
          klCacheRef.current = { symbol, levels: computeKeyLevels(daily) };
        }
        const bars = barsRef.current;
        const result = buildKeyLevelsResult(klCacheRef.current.levels, bars);
        if (aborted || !result) return;
        remove();
        keyLevelsRef.current = addSpecIndicator(chart, 'key-levels', result);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      aborted = true;
    };
  }, [ready, barsVersion, symbol, showKeyLevels]);

  // --- VWAP: session (all bars) + anchored (bars from the clicked anchor). ---
  useEffect(() => {
    if (!ready) return;
    const chart = chartRef.current;
    if (!chart) return;
    const rendered = vwapRenderedRef.current;
    let aborted = false;
    const remove = (key: string) => {
      const e = rendered.get(key);
      if (e) {
        removeSpecIndicator(chart, e.handle);
        rendered.delete(key);
      }
    };

    if (!showVwap) {
      remove('session');
      remove('anchored');
      return;
    }

    (async () => {
      const bars = barsRef.current;
      if (!bars.length) return;
      const sv = `${barsVersion}`;
      if (rendered.get('session')?.version !== sv) {
        try {
          const res = await computeIndicator(vwapSpec(), bars);
          if (aborted) return;
          remove('session');
          const h = addSpecIndicator(chart, 'vwap-session', res);
          if (h) rendered.set('session', { handle: h, version: sv });
        } catch {
          /* ignore */
        }
      }
      if (vwapAnchor != null) {
        const av = `${barsVersion}:${vwapAnchor}`;
        if (rendered.get('anchored')?.version !== av) {
          const slice = bars.filter((b) => b.timestamp >= vwapAnchor);
          if (slice.length >= 2) {
            try {
              const res = await computeIndicator(vwapSpec(VWAP_ANCHORED_COLOR, 'aVWAP'), slice);
              if (aborted) return;
              remove('anchored');
              const h = addSpecIndicator(chart, 'vwap-anchored', res);
              if (h) rendered.set('anchored', { handle: h, version: av });
            } catch {
              /* ignore */
            }
          }
        }
      } else {
        remove('anchored');
      }
    })();
    return () => {
      aborted = true;
    };
  }, [ready, barsVersion, showVwap, vwapAnchor]);

  // --- Reconcile custom spec indicators: compute over the current bars, then
  // register/create; recompute when the bars change; remove deactivated ones. ---
  useEffect(() => {
    if (!ready) return;
    const chart = chartRef.current;
    if (!chart) return;
    let aborted = false;
    const rendered = customRenderedRef.current;

    // Drop any rendered indicator whose spec was removed from state.
    const activeKeys = new Set(customSpecs.map((s) => s.key));
    for (const [key, entry] of rendered) {
      if (!activeKeys.has(key)) {
        removeSpecIndicator(chart, entry.handle);
        rendered.delete(key);
      }
    }

    (async () => {
      for (const s of customSpecs) {
        if (s.error) continue;
        const existing = rendered.get(s.key);
        if (existing && existing.version === barsVersion) continue; // up to date
        const bars = barsRef.current;
        if (!bars.length) continue;
        try {
          const result = await computeIndicator(s.spec, bars);
          if (aborted) return;
          if (existing) removeSpecIndicator(chart, existing.handle);
          const handle = addSpecIndicator(chart, s.key, result);
          if (handle) rendered.set(s.key, { handle, version: barsVersion });
        } catch (e) {
          setCustomSpecs((prev) =>
            prev.map((x) => (x.key === s.key ? { ...x, error: errMessage(e) } : x)),
          );
        }
      }
    })();

    return () => {
      aborted = true;
    };
  }, [ready, barsVersion, customSpecs]);

  const addCustomSpec = (spec: IndicatorSpec, label: string) => {
    const key = `c${customKeyRef.current++}`;
    setCustomSpecs((prev) => [...prev, { key, spec, label }]);
  };

  const removeCustomSpec = (key: string) =>
    setCustomSpecs((prev) => prev.filter((s) => s.key !== key));

  const saveSpecToArsenal = (spec: IndicatorSpec) => {
    saveToArsenal(spec, 'manual')
      .then(() => listArsenal())
      .then(setArsenal)
      .catch(() => undefined);
  };

  const toggleIndicator = (name: string) =>
    setEnabled((prev) => ({ ...prev, [name]: !prev[name] }));

  const startDrawing = (name: string) => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.createOverlay(name);
    setActiveTool(name);
  };

  const clearDrawings = () => {
    chartRef.current?.removeOverlay();
    setActiveTool(null);
  };

  // What's currently on the chart — passed to the AI copilot as context.
  const activeIndicators = [
    ...ALL_INDICATORS.filter((n) => enabled[n]),
    ...LAYER_NAMES.filter((n) => layers[n]),
    ...(showVP ? ['Volume Profile'] : []),
    ...(showVwap ? [`VWAP${vwapAnchor ? ' (anchored)' : ''}`] : []),
    ...(showKeyLevels ? ['Key Levels'] : []),
    ...(showSessions && isIntraday ? ['Sessions'] : []),
    ...customSpecs.filter((s) => !s.error).map((s) => s.label),
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {/* Timeframe selector */}
      {showTimeframe && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ color: GREEN_DIM, fontFamily: 'monospace', fontSize: 11 }}>
            timeframe
          </span>
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf.value}
              type="button"
              onClick={() => setResolution(tf.value)}
              style={btnStyle(resolution === tf.value)}
            >
              {tf.label}
            </button>
          ))}
        </div>
      )}

      {/* Indicator toggles */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ color: GREEN_DIM, fontFamily: 'monospace', fontSize: 11 }}>
          indicators
        </span>
        {ALL_INDICATORS.map((name) => (
          <button
            key={name}
            type="button"
            onClick={() => toggleIndicator(name)}
            style={btnStyle(!!enabled[name])}
          >
            {name}
          </button>
        ))}
      </div>

      {/* Server layers (fib/S-R levels, signal markers, RS-vs-SPY) from /full */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ color: GREEN_DIM, fontFamily: 'monospace', fontSize: 11 }}>
          layers
        </span>
        {LAYER_NAMES.map((name) => (
          <button
            key={name}
            type="button"
            onClick={() => toggleLayer(name)}
            style={btnStyle(!!layers[name])}
          >
            {name}
          </button>
        ))}
        <button type="button" onClick={() => setShowMtf((v) => !v)} style={btnStyle(showMtf)}>
          MTF
        </button>
        <button type="button" onClick={() => setShowAlerts((v) => !v)} style={btnStyle(showAlerts)}>
          Alerts
        </button>
        <button type="button" onClick={() => setShowScreener((v) => !v)} style={btnStyle(showScreener)}>
          Screen
        </button>
        <button type="button" onClick={() => setShowCopilot((v) => !v)} style={btnStyle(showCopilot)}>
          🤖 Copilot
        </button>
        <button type="button" onClick={() => setShowVP((v) => !v)} style={btnStyle(showVP)}>
          VolProfile
        </button>
        <button type="button" onClick={() => setShowKeyLevels((v) => !v)} style={btnStyle(showKeyLevels)}>
          KeyLevels
        </button>
        <button
          type="button"
          onClick={() => setShowSessions((v) => !v)}
          style={btnStyle(showSessions)}
          title={isIntraday ? 'London/NY/Asia sessions + kill zones' : 'Intraday timeframes only'}
        >
          Sessions
        </button>
        {showSessions && !isIntraday && (
          <span style={{ color: GREEN_DIM, fontFamily: 'monospace', fontSize: 11 }}>
            (intraday only)
          </span>
        )}
        <button
          type="button"
          onClick={() =>
            setShowVwap((v) => {
              if (v) setVwapAnchor(null);
              return !v;
            })
          }
          style={btnStyle(showVwap)}
        >
          VWAP
        </button>
        {showVwap && (
          <span style={{ color: GREEN_DIM, fontFamily: 'monospace', fontSize: 11 }}>
            {vwapAnchor
              ? `anchor ${new Date(vwapAnchor).toLocaleDateString()}`
              : 'click a bar to anchor'}
            {vwapAnchor && (
              <button
                type="button"
                aria-label="Clear VWAP anchor"
                onClick={() => setVwapAnchor(null)}
                style={{ background: 'transparent', color: GREEN, border: 'none', cursor: 'pointer', padding: '0 4px' }}
              >
                ×
              </button>
            )}
          </span>
        )}
      </div>

      {/* Multi-timeframe dashboard (condensed read across 15m/1H/1D/1W) */}
      {showMtf && <MtfDashboard symbol={symbol} />}

      {/* Chart-condition price alerts (delivered via Telegram) */}
      {showAlerts && <AlertsPanel symbol={symbol} />}

      {/* Multi-symbol screener (price condition across a watchlist) */}
      {showScreener && <ScreenerPanel symbol={symbol} />}

      {/* AI charting copilot — explains/advises on the current chart */}
      {showCopilot && <CopilotPanel symbol={symbol} indicators={activeIndicators} />}

      {/* Drawing tools */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ color: GREEN_DIM, fontFamily: 'monospace', fontSize: 11 }}>
          draw
        </span>
        {DRAW_TOOLS.map((tool) => (
          <button
            key={tool.name}
            type="button"
            onClick={() => startDrawing(tool.name)}
            style={btnStyle(activeTool === tool.name)}
          >
            {tool.label}
          </button>
        ))}
        <button type="button" onClick={clearDrawings} style={btnStyle(false)}>
          Clear
        </button>
      </div>

      {/* Custom spec indicators (computed by the backend engine — no eval) */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ color: GREEN_DIM, fontFamily: 'monospace', fontSize: 11 }}>
          custom
        </span>
        <select
          aria-label="Add custom indicator"
          value=""
          onChange={(e) => {
            const v = e.target.value;
            if (v.startsWith('arsenal:')) {
              const item = arsenal.find((a) => a.id === v.slice(8));
              if (item) addCustomSpec(item.spec, item.name);
            } else if (v.startsWith('example:')) {
              const spec = EXAMPLE_SPECS.find((s) => s.name === v.slice(8));
              if (spec) addCustomSpec(spec, spec.name);
            }
          }}
          style={{
            background: '#000',
            color: GREEN,
            border: `1px solid ${GREEN_DIM}`,
            fontFamily: 'monospace',
            fontSize: 12,
            padding: '4px 8px',
            borderRadius: 4,
          }}
        >
          <option value="">+ add spec…</option>
          {arsenal.length > 0 && (
            <optgroup label="Arsenal">
              {arsenal.map((a) => (
                <option key={a.id} value={`arsenal:${a.id}`}>
                  {a.name}
                </option>
              ))}
            </optgroup>
          )}
          <optgroup label="Examples">
            {EXAMPLE_SPECS.map((s) => (
              <option key={s.name} value={`example:${s.name}`}>
                {s.name}
              </option>
            ))}
          </optgroup>
        </select>
        {customSpecs.map((s) => (
          <span
            key={s.key}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              border: `1px solid ${s.error ? RED : GREEN}`,
              borderRadius: 4,
              padding: '2px 6px',
              fontFamily: 'monospace',
              fontSize: 12,
              color: s.error ? RED : GREEN,
            }}
            title={s.error || s.spec.name}
          >
            {s.label}
            {s.error ? ' ⚠' : ''}
            {!s.error && (
              <button
                type="button"
                aria-label={`Save ${s.label} to arsenal`}
                title="Save to arsenal"
                onClick={() => saveSpecToArsenal(s.spec)}
                style={{
                  background: 'transparent',
                  color: 'inherit',
                  border: 'none',
                  cursor: 'pointer',
                  fontSize: 12,
                  lineHeight: 1,
                  padding: 0,
                }}
              >
                💾
              </button>
            )}
            <button
              type="button"
              aria-label={`Remove ${s.label}`}
              onClick={() => removeCustomSpec(s.key)}
              style={{
                background: 'transparent',
                color: 'inherit',
                border: 'none',
                cursor: 'pointer',
                fontSize: 13,
                lineHeight: 1,
                padding: 0,
              }}
            >
              ×
            </button>
          </span>
        ))}
      </div>

      {/* Chart canvas */}
      <div style={{ position: 'relative' }}>
        <div
          ref={containerRef}
          style={{
            width: '100%',
            height,
            minHeight: 420,
            background: '#000',
            border: `1px solid ${GREEN_DIM}`,
            borderRadius: 4,
          }}
        />
        {/* Session / kill-zone shading — full-height vertical bands */}
        {showSessions && isIntraday && sessionRects.length > 0 && (
          <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden' }}>
            {sessionRects.map((r, i) => (
              <div
                key={i}
                style={{ position: 'absolute', top: 0, bottom: 0, left: r.left, width: r.width, background: r.color }}
              />
            ))}
          </div>
        )}
        {/* Volume Profile histogram — right-aligned bars at each price bin */}
        {showVP && vpBars.length > 0 && (
          <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
            {vpBars.map((b, i) => (
              <div
                key={i}
                style={{
                  position: 'absolute',
                  right: 56, // clear the price axis
                  top: b.top,
                  height: b.height,
                  width: `${Math.max(0.5, b.widthPct * 0.32)}%`,
                  background: b.poc ? 'rgba(255,204,0,0.55)' : 'rgba(0,255,65,0.22)',
                  borderTop: '1px solid rgba(0,0,0,0.4)',
                }}
              />
            ))}
          </div>
        )}
        {(status === 'loading' || status === 'empty' || status === 'error') && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              pointerEvents: 'none',
              color: status === 'error' ? RED : GREEN,
              fontFamily: 'monospace',
              fontSize: 13,
              textShadow: status === 'error' ? 'none' : `0 0 8px ${GREEN}`,
            }}
          >
            {status === 'loading' && `Loading ${symbol}…`}
            {status === 'empty' && `No data for ${symbol} @ ${resolution}`}
            {status === 'error' && `⚠ ${errMsg}`}
          </div>
        )}
      </div>

      <div style={{ color: GREEN_DIM, fontFamily: 'monospace', fontSize: 11 }}>
        {status === 'ready' ? `${barCount} bars` : status}
      </div>
    </div>
  );
};

/** Axios marks canceled requests; treat them as no-ops, not errors. */
function axiosCanceled(err: unknown): boolean {
  return (
    typeof err === 'object' &&
    err !== null &&
    ('code' in err
      ? (err as { code?: string }).code === 'ERR_CANCELED'
      : false)
  );
}

/** Best-effort human message from a compute/validate error (incl. backend detail). */
function errMessage(err: unknown): string {
  if (typeof err === 'object' && err !== null) {
    const resp = (err as { response?: { data?: { detail?: unknown } } }).response;
    const detail = resp?.data?.detail;
    if (detail) {
      if (typeof detail === 'string') return detail;
      const errors = (detail as { errors?: string[] }).errors;
      if (Array.isArray(errors) && errors.length) return errors.join('; ');
    }
    const msg = (err as { message?: string }).message;
    if (msg) return msg;
  }
  return 'compute failed';
}

export default KLineChartView;
