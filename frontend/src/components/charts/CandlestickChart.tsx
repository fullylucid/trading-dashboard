// Typed Lightweight-Charts v5 candlestick + volume wrapper.
//
// - Renders candles and an (optional) overlaid volume histogram.
// - Exposes an imperative handle (overlays, markers, live last-candle update).
// - Handles container resize via ResizeObserver and full cleanup on unmount.

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
} from 'react';
import {
  CandlestickSeries,
  HistogramSeries,
  ColorType,
  CrosshairMode,
  LineStyle,
  createChart,
  createSeriesMarkers,
} from 'lightweight-charts';
import type {
  CandlestickData,
  HistogramData,
  IChartApi,
  IPriceLine,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  SeriesMarker,
  Time,
  UTCTimestamp,
} from 'lightweight-charts';
import type {
  Candle,
  CandlestickChartProps,
  ChartHandle,
  ChartMarker,
  ChartTheme,
  OverlayLevel,
  OverlayLineStyle,
} from './types';

interface ThemePalette {
  background: string;
  text: string;
  grid: string;
  border: string;
  up: string;
  down: string;
  volume: string;
}

const PALETTES: Record<ChartTheme, ThemePalette> = {
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

function toSeriesMarkers(markers: ChartMarker[]): SeriesMarker<Time>[] {
  return markers.map((m) => ({
    time: m.time,
    position: m.position,
    shape: m.shape,
    color: m.color,
    text: m.text,
  }));
}

const CandlestickChart = forwardRef<ChartHandle, CandlestickChartProps>(
  function CandlestickChart(props, ref) {
    const {
      candles,
      overlays,
      markers,
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

    // ----- create the chart once -----
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

      const candleSeries = chart.addSeries(CandlestickSeries, {
        upColor: palette.up,
        downColor: palette.down,
        wickUpColor: palette.up,
        wickDownColor: palette.down,
        borderVisible: false,
      });

      chartRef.current = chart;
      candleSeriesRef.current = candleSeries;
      markerPluginRef.current = createSeriesMarkers(candleSeries, []);

      if (showVolume) {
        const volumeSeries = chart.addSeries(HistogramSeries, {
          priceFormat: { type: 'volume' },
          priceScaleId: 'volume',
        });
        // Pin volume to the bottom ~20% of the pane.
        volumeSeries.priceScale().applyOptions({
          scaleMargins: { top: 0.8, bottom: 0 },
        });
        volumeSeriesRef.current = volumeSeries;
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
        markerPluginRef.current = null;
        volumeSeriesRef.current = null;
        candleSeriesRef.current = null;
        chartRef.current = null;
        chart.remove();
      };
      // Recreate only when structural options change.
    }, [theme, height, showVolume]);

    // ----- push candle data -----
    useEffect(() => {
      const candleSeries = candleSeriesRef.current;
      if (!candleSeries) return;
      candleSeries.setData(toCandlestickData(candles));
      if (volumeSeriesRef.current) {
        volumeSeriesRef.current.setData(toVolumeData(candles, PALETTES[theme]));
      }
      chartRef.current?.timeScale().fitContent();
    }, [candles, theme]);

    // ----- declarative overlays -----
    const applyOverlays = (levels: OverlayLevel[]): void => {
      const candleSeries = candleSeriesRef.current;
      if (!candleSeries) return;
      const existing = priceLinesRef.current;
      existing.forEach((line) => candleSeries.removePriceLine(line));
      existing.clear();
      for (const level of levels) {
        const line = candleSeries.createPriceLine({
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
      // applyOverlays reads refs; only re-run when the overlays prop changes.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [overlays]);

    // ----- declarative markers -----
    const applyMarkers = (next: ChartMarker[]): void => {
      markerPluginRef.current?.setMarkers(toSeriesMarkers(next));
    };

    useEffect(() => {
      applyMarkers(markers ?? []);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [markers]);

    // ----- imperative handle -----
    useImperativeHandle(
      ref,
      (): ChartHandle => ({
        setOverlays: (levels) => applyOverlays(levels),
        setMarkers: (next) => applyMarkers(next),
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
      [theme],
    );

    return (
      <div
        ref={containerRef}
        className={className}
        style={{ width: '100%', height }}
      />
    );
  },
);

export default CandlestickChart;

// Re-export the timestamp helper type so consumers can build candles ergonomically.
export type { UTCTimestamp };
