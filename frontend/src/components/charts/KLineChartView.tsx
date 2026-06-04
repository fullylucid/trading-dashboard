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
import { dispose, init } from 'klinecharts';
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

    const onResize = () => chart.resize();
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      dispose(el);
      chartRef.current = null;
      paneIdsRef.current = {};
      candleOverlaysRef.current.clear();
      customRenderedRef.current.clear();
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
