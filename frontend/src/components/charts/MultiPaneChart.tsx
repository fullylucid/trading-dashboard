// MultiPaneChart — the workspace-grade chart engine.
//
// A superset sibling of CandlestickChart (which it leaves untouched) that adds
// the four pieces the TradingView-style workspace needs:
//
//   1. OSCILLATOR SUB-PANES   — RSI / MACD / confluence line/histogram series in
//      their own stacked panes below price (v5 multi-pane via addSeries paneIndex).
//   2. MARKER SERIES          — buy/sell/divergence/insider markers on the price
//      series (createSeriesMarkers, supports atPrice* anchoring).
//   3. BACKGROUND SHADING     — regime + sector-rotation bands behind candles,
//      via the BackgroundBands pane primitive.
//   4. COMPARE MODE           — multiple normalized (% -from-start) line series +
//      an SPY benchmark overlaid on a single % price scale.
//
// All indicator math is computed upstream (reusing the tested analytics
// modules); this component is render-only and never recomputes signals.

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
} from 'react';
import {
  AreaSeries,
  BaselineSeries,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
} from 'lightweight-charts';
import type {
  AreaData,
  BaselineData,
  CandlestickData,
  HistogramData,
  IChartApi,
  IPriceLine,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  LineData,
  SeriesMarker,
  Time,
} from 'lightweight-charts';
import type {
  Candle,
  CompareSeries,
  IndicatorPoint,
  IndicatorSeries,
  Marker,
  MultiPaneChartHandle,
  MultiPaneChartMode,
  MultiPaneChartProps,
  OverlayLevel,
  OverlayLineStyle,
  ShadeBand,
} from './types';
import { BackgroundBands } from './lib/backgroundBands';

interface ThemePalette {
  background: string;
  text: string;
  grid: string;
  border: string;
  up: string;
  down: string;
  volume: string;
}

const PALETTES: Record<'dark' | 'light', ThemePalette> = {
  dark: {
    background: '#0b0e11',
    text: '#d1d4dc',
    grid: 'rgba(42, 46, 57, 0.6)',
    border: '#2a2e39',
    up: '#26a69a',
    down: '#ef5350',
    volume: 'rgba(120, 123, 134, 0.45)',
  },
  light: {
    background: '#ffffff',
    text: '#131722',
    grid: 'rgba(197, 203, 206, 0.6)',
    border: '#d6dcde',
    up: '#26a69a',
    down: '#ef5350',
    volume: 'rgba(120, 123, 134, 0.35)',
  },
};

const LINE_STYLE_MAP: Record<OverlayLineStyle, LineStyle> = {
  solid: LineStyle.Solid,
  dotted: LineStyle.Dotted,
  dashed: LineStyle.Dashed,
  'large-dashed': LineStyle.LargeDashed,
  'sparse-dotted': LineStyle.SparseDotted,
};

const DEFAULT_INDICATOR_COLOR = '#42a5f5';

// ---------------------------------------------------------------------------
// Pure data mappers
// ---------------------------------------------------------------------------

function toCandlestickData(candles: Candle[]): CandlestickData<Time>[] {
  return candles.map((c) => ({
    time: c.time,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
  }));
}

function toVolumeData(candles: Candle[], palette: ThemePalette): HistogramData<Time>[] {
  return candles.map((c) => ({
    time: c.time,
    value: c.volume ?? 0,
    color: c.close >= c.open ? palette.up : palette.down,
  }));
}

const PRICE_POSITIONS: ReadonlySet<string> = new Set([
  'atPriceTop',
  'atPriceBottom',
  'atPriceMiddle',
]);

function toSeriesMarkers(markers: Marker[]): SeriesMarker<Time>[] {
  // Already-sorted requirement of the library; sort defensively.
  return [...markers]
    .sort((a, b) => (a.time as number) - (b.time as number))
    .map((m): SeriesMarker<Time> => {
      // SeriesMarker is a discriminated union: bar-relative vs exact-price.
      if (PRICE_POSITIONS.has(m.position)) {
        return {
          time: m.time,
          position: m.position as 'atPriceTop' | 'atPriceBottom' | 'atPriceMiddle',
          shape: m.shape,
          color: m.color,
          text: m.text,
          size: m.size,
          // atPrice* markers require a price; fall back to 0 if omitted.
          price: m.price ?? 0,
        };
      }
      return {
        time: m.time,
        position: m.position as 'aboveBar' | 'belowBar' | 'inBar',
        shape: m.shape,
        color: m.color,
        text: m.text,
        size: m.size,
      };
    });
}

function toLineData(points: IndicatorPoint[]): LineData<Time>[] {
  return points.map((p) => ({ time: p.time, value: p.value }));
}

function toAreaData(points: IndicatorPoint[]): AreaData<Time>[] {
  return points.map((p) => ({ time: p.time, value: p.value }));
}

function toBaselineData(points: IndicatorPoint[]): BaselineData<Time>[] {
  return points.map((p) => ({ time: p.time, value: p.value }));
}

function toIndicatorHistogram(points: IndicatorPoint[], color: string): HistogramData<Time>[] {
  return points.map((p) => ({ time: p.time, value: p.value, color }));
}

/**
 * Normalize a close-price point series to "% change from the first point" so
 * symbols with very different absolute prices overlay meaningfully in COMPARE
 * mode. The first finite point anchors the 0% baseline.
 */
function normalizeToPercent(points: IndicatorPoint[]): LineData<Time>[] {
  if (points.length === 0) return [];
  let base = NaN;
  for (const p of points) {
    if (Number.isFinite(p.value) && p.value !== 0) {
      base = p.value;
      break;
    }
  }
  if (!Number.isFinite(base)) return [];
  return points.map((p) => ({
    time: p.time,
    value: ((p.value - base) / base) * 100,
  }));
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const MultiPaneChart = forwardRef<MultiPaneChartHandle, MultiPaneChartProps>(
  function MultiPaneChart(props, ref) {
    const {
      candles,
      mode = 'price',
      overlays,
      indicators,
      markers,
      shadeBands,
      compareSeries,
      showVolume = true,
      height = 480,
      theme = 'dark',
      className,
    } = props;

    const containerRef = useRef<HTMLDivElement | null>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
    const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
    const markerPluginRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
    const priceLinesRef = useRef<Map<string, IPriceLine>>(new Map());
    const bandsPrimitiveRef = useRef<BackgroundBands | null>(null);

    // Dynamic series keyed by id, so we can diff/rebuild without leaking.
    const indicatorSeriesRef = useRef<Map<string, ISeriesApi<SeriesKind>>>(new Map());
    const indicatorGuidesRef = useRef<Map<string, IPriceLine[]>>(new Map());
    const compareSeriesRef = useRef<Map<string, ISeriesApi<'Line'>>>(new Map());
    // pane id (logical) -> pane index assigned in the chart.
    const paneIndexRef = useRef<Map<string, number>>(new Map());

    const isCompare = mode === 'compare';

    // ----- create the chart once (per structural option) -----
    useEffect(() => {
      const container = containerRef.current;
      if (!container) return;

      const palette = PALETTES[theme];
      const chart = createChart(container, {
        width: container.clientWidth,
        height,
        layout: {
          background: { type: ColorType.Solid, color: palette.background },
          textColor: palette.text,
          fontFamily: 'monospace',
          panes: { separatorColor: palette.border, enableResize: true },
        },
        grid: {
          vertLines: { color: palette.grid },
          horzLines: { color: palette.grid },
        },
        rightPriceScale: { borderColor: palette.border },
        timeScale: { borderColor: palette.border, timeVisible: true, secondsVisible: false },
        crosshair: { mode: CrosshairMode.Normal },
        autoSize: false,
      });
      chartRef.current = chart;

      if (!isCompare) {
        const candleSeries = chart.addSeries(CandlestickSeries, {
          upColor: palette.up,
          downColor: palette.down,
          wickUpColor: palette.up,
          wickDownColor: palette.down,
          borderVisible: false,
        });
        candleSeriesRef.current = candleSeries;
        markerPluginRef.current = createSeriesMarkers(candleSeries, []);

        // Background shading primitive on the main pane.
        const bands = new BackgroundBands({
          font: '11px monospace',
          color: palette.text,
        });
        const mainPane = chart.panes()[0];
        if (mainPane) {
          mainPane.attachPrimitive(bands);
          bandsPrimitiveRef.current = bands;
        }

        if (showVolume) {
          const volumeSeries = chart.addSeries(HistogramSeries, {
            priceFormat: { type: 'volume' },
            priceScaleId: 'volume',
          });
          volumeSeries.priceScale().applyOptions({
            scaleMargins: { top: 0.8, bottom: 0 },
          });
          volumeSeriesRef.current = volumeSeries;
        }
      } else {
        // Compare mode: a percent-formatted main pane, no candles/volume.
        chart.applyOptions({
          rightPriceScale: {
            borderColor: palette.border,
            scaleMargins: { top: 0.1, bottom: 0.1 },
          },
        });
      }

      const resizeObserver = new ResizeObserver((entries) => {
        const entry = entries[0];
        if (!entry) return;
        chart.applyOptions({ width: Math.floor(entry.contentRect.width) });
      });
      resizeObserver.observe(container);

      return () => {
        resizeObserver.disconnect();
        priceLinesRef.current.clear();
        indicatorGuidesRef.current.clear();
        indicatorSeriesRef.current.clear();
        compareSeriesRef.current.clear();
        paneIndexRef.current.clear();
        bandsPrimitiveRef.current = null;
        markerPluginRef.current = null;
        volumeSeriesRef.current = null;
        candleSeriesRef.current = null;
        chartRef.current = null;
        chart.remove();
      };
    }, [theme, height, showVolume, isCompare]);

    // ----- price candle data (price mode only) -----
    useEffect(() => {
      const candleSeries = candleSeriesRef.current;
      if (!candleSeries) return;
      candleSeries.setData(toCandlestickData(candles));
      if (volumeSeriesRef.current) {
        volumeSeriesRef.current.setData(toVolumeData(candles, PALETTES[theme]));
      }
      chartRef.current?.timeScale().fitContent();
    }, [candles, theme]);

    // ----- overlays (main-pane price lines) -----
    const applyOverlays = (levels: OverlayLevel[]): void => {
      const series = candleSeriesRef.current;
      if (!series) return;
      const existing = priceLinesRef.current;
      existing.forEach((line) => series.removePriceLine(line));
      existing.clear();
      for (const level of levels) {
        const line = series.createPriceLine({
          price: level.price,
          color: level.color,
          lineWidth: level.lineWidth ?? 1,
          lineStyle: LINE_STYLE_MAP[level.lineStyle ?? 'dashed'],
          axisLabelVisible: level.axisLabelVisible ?? true,
          title: level.label,
        });
        existing.set(level.id, line);
      }
    };

    useEffect(() => {
      applyOverlays(overlays ?? []);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [overlays]);

    // ----- markers -----
    const applyMarkers = (next: Marker[]): void => {
      markerPluginRef.current?.setMarkers(toSeriesMarkers(next));
    };

    useEffect(() => {
      applyMarkers(markers ?? []);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [markers]);

    // ----- background shade bands -----
    const applyShadeBands = (bands: ShadeBand[]): void => {
      bandsPrimitiveRef.current?.setBands(bands);
    };

    useEffect(() => {
      applyShadeBands(shadeBands ?? []);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [shadeBands]);

    // ----- indicator series (price overlays + oscillator sub-panes) -----
    const applyIndicators = (series: IndicatorSeries[]): void => {
      const chart = chartRef.current;
      if (!chart || isCompare) return;

      const liveSeries = indicatorSeriesRef.current;
      const liveGuides = indicatorGuidesRef.current;
      const paneIndex = paneIndexRef.current;

      // Tear down everything and rebuild — indicator sets are small and this
      // keeps pane assignment deterministic without fiddly diffing.
      liveGuides.forEach((guides, id) => {
        const s = liveSeries.get(id);
        if (s) guides.forEach((g) => s.removePriceLine(g));
      });
      liveSeries.forEach((s) => chart.removeSeries(s));
      liveSeries.clear();
      liveGuides.clear();
      paneIndex.clear();

      // Assign pane indices: 'price' = 0; each distinct oscillator paneId gets
      // the next free pane index, created on demand.
      let nextPane = volumeSeriesRef.current ? 1 : 1; // 0 reserved for price.
      const resolvePane = (paneId: string | undefined): number => {
        const key = paneId ?? 'price';
        if (key === 'price') return 0;
        const cached = paneIndex.get(key);
        if (cached != null) return cached;
        const idx = nextPane;
        nextPane += 1;
        paneIndex.set(key, idx);
        return idx;
      };

      for (const ind of series) {
        if (ind.hidden) continue;
        const color = ind.color ?? DEFAULT_INDICATOR_COLOR;
        const lineWidth = ind.lineWidth ?? 2;
        const lineStyle = LINE_STYLE_MAP[ind.lineStyle ?? 'solid'];
        const pane = resolvePane(ind.paneId);

        let api: ISeriesApi<SeriesKind>;
        if (ind.kind === 'histogram') {
          const h = chart.addSeries(HistogramSeries, { color, priceLineVisible: false }, pane);
          h.setData(toIndicatorHistogram(ind.data, color));
          api = h;
        } else if (ind.kind === 'area') {
          const a = chart.addSeries(
            AreaSeries,
            { lineColor: color, topColor: color, bottomColor: 'rgba(0,0,0,0)', lineWidth },
            pane,
          );
          a.setData(toAreaData(ind.data));
          api = a;
        } else if (ind.kind === 'baseline') {
          const b = chart.addSeries(
            BaselineSeries,
            { baseValue: { type: 'price', price: ind.baseValue ?? 0 } },
            pane,
          );
          b.setData(toBaselineData(ind.data));
          api = b;
        } else {
          const l = chart.addSeries(
            LineSeries,
            { color, lineWidth, lineStyle, priceLineVisible: false, lastValueVisible: false },
            pane,
          );
          l.setData(toLineData(ind.data));
          api = l;
        }

        // Size a freshly-created oscillator pane if requested.
        if (pane !== 0 && ind.paneHeight != null) {
          const panes = chart.panes();
          const target = panes[pane];
          if (target) target.setHeight(ind.paneHeight);
        }

        // Per-series horizontal guides (e.g. RSI 30/70, MACD zero).
        if (ind.guides && ind.guides.length > 0) {
          const lines: IPriceLine[] = ind.guides.map((g) =>
            api.createPriceLine({
              price: g.value,
              color: g.color,
              lineWidth: 1,
              lineStyle: LINE_STYLE_MAP[g.lineStyle ?? 'dotted'],
              axisLabelVisible: true,
              title: g.label ?? '',
            }),
          );
          liveGuides.set(ind.id, lines);
        }

        liveSeries.set(ind.id, api);
      }
    };

    useEffect(() => {
      applyIndicators(indicators ?? []);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [indicators]);

    // ----- compare mode: normalized % lines + benchmark -----
    const applyCompareSeries = (series: CompareSeries[]): void => {
      const chart = chartRef.current;
      if (!chart || !isCompare) return;

      const live = compareSeriesRef.current;
      live.forEach((s) => chart.removeSeries(s));
      live.clear();

      for (const cs of series) {
        const line = chart.addSeries(LineSeries, {
          color: cs.color,
          lineWidth: cs.lineWidth ?? (cs.isBenchmark ? 1 : 2),
          lineStyle: cs.isBenchmark ? LineStyle.Dashed : LineStyle.Solid,
          priceLineVisible: false,
          lastValueVisible: true,
          title: cs.symbol,
          priceFormat: { type: 'custom', formatter: (v: number) => `${v.toFixed(1)}%` },
        });
        line.setData(normalizeToPercent(cs.data));
        live.set(cs.symbol, line);
      }
      chart.timeScale().fitContent();
    };

    useEffect(() => {
      applyCompareSeries(compareSeries ?? []);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [compareSeries, isCompare]);

    // ----- imperative handle -----
    useImperativeHandle(
      ref,
      (): MultiPaneChartHandle => ({
        setOverlays: (levels) => applyOverlays(levels),
        setMarkers: (next) => applyMarkers(next),
        setIndicators: (next) => applyIndicators(next),
        setShadeBands: (bands) => applyShadeBands(bands),
        setCompareSeries: (next) => applyCompareSeries(next),
        updateLastCandle: (candle) => {
          candleSeriesRef.current?.update({
            time: candle.time,
            open: candle.open,
            high: candle.high,
            low: candle.low,
            close: candle.close,
          });
          if (volumeSeriesRef.current) {
            volumeSeriesRef.current.update({
              time: candle.time,
              value: candle.volume ?? 0,
              color: candle.close >= candle.open ? PALETTES[theme].up : PALETTES[theme].down,
            });
          }
        },
        setData: (next) => {
          candleSeriesRef.current?.setData(toCandlestickData(next));
          volumeSeriesRef.current?.setData(toVolumeData(next, PALETTES[theme]));
        },
        fitContent: () => chartRef.current?.timeScale().fitContent(),
      }),
      // eslint-disable-next-line react-hooks/exhaustive-deps
      [theme, isCompare],
    );

    // Optional simple legend for oscillator panes / compare lines.
    const legend = useMemo<LegendEntry[]>(() => {
      if (isCompare) {
        return (compareSeries ?? []).map((c) => ({
          id: c.symbol,
          label: c.isBenchmark ? `${c.symbol} (bench)` : c.symbol,
          color: c.color,
        }));
      }
      return (indicators ?? [])
        .filter((i) => !i.hidden)
        .map((i) => ({ id: i.id, label: i.label, color: i.color ?? DEFAULT_INDICATOR_COLOR }));
    }, [isCompare, compareSeries, indicators]);

    const palette = PALETTES[theme];

    return (
      <div className={className} style={{ position: 'relative', width: '100%' }}>
        {legend.length > 0 && (
          <div
            style={{
              position: 'absolute',
              top: 6,
              left: 8,
              zIndex: 3,
              display: 'flex',
              flexWrap: 'wrap',
              gap: 10,
              fontFamily: 'monospace',
              fontSize: 11,
              color: palette.text,
              pointerEvents: 'none',
            }}
          >
            {legend.map((e) => (
              <span key={e.id} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <span
                  style={{
                    width: 10,
                    height: 2,
                    background: e.color,
                    display: 'inline-block',
                  }}
                />
                {e.label}
              </span>
            ))}
          </div>
        )}
        <div ref={containerRef} style={{ width: '100%', height }} />
      </div>
    );
  },
);

interface LegendEntry {
  id: string;
  label: string;
  color: string;
}

// Union of the series types this component instantiates dynamically.
type SeriesKind = 'Line' | 'Area' | 'Histogram' | 'Baseline';

export default MultiPaneChart;
