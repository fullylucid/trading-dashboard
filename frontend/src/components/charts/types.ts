// Shared types for the charts foundation (Lightweight Charts v5 wrappers).
//
// Kept deliberately framework-light so both the chart wrapper, the live-price
// hook, and the chart API client can share a single vocabulary.

import type { UTCTimestamp } from 'lightweight-charts';

/**
 * A single OHLCV bar. `time` is a UNIX timestamp in *seconds* (UTC), matching
 * Lightweight Charts' `UTCTimestamp`. Volume is optional (some feeds omit it).
 */
export interface Candle {
  time: UTCTimestamp;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

/**
 * Raw candle shape as returned by the backend `GET /api/chart/{symbol}`
 * endpoint (snake_case, epoch-ms or ISO timestamp). Normalized to {@link Candle}
 * by `chartApi.ts`.
 */
export interface RawCandle {
  timestamp: number | string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number | null;
}

/**
 * A horizontal price line drawn on the chart (support/resistance, fib level,
 * stop/target, etc.). Maps onto Lightweight Charts' `createPriceLine`.
 */
export interface OverlayLevel {
  /** Unique id so the consumer can update/remove a specific level. */
  id: string;
  price: number;
  label: string;
  color: string;
  /** Solid | dotted | dashed | large-dashed | sparse-dotted. Defaults to dashed. */
  lineStyle?: OverlayLineStyle;
  lineWidth?: 1 | 2 | 3 | 4;
  /** Show the label badge on the price axis. Defaults to true. */
  axisLabelVisible?: boolean;
}

export type OverlayLineStyle =
  | 'solid'
  | 'dotted'
  | 'dashed'
  | 'large-dashed'
  | 'sparse-dotted';

export type MarkerPosition = 'aboveBar' | 'belowBar' | 'inBar';
export type MarkerShape = 'circle' | 'square' | 'arrowUp' | 'arrowDown';

/**
 * A marker pinned to a specific bar (swing pivot, entry/exit, pattern point).
 */
export interface ChartMarker {
  id: string;
  time: UTCTimestamp;
  position: MarkerPosition;
  shape: MarkerShape;
  color: string;
  text?: string;
}

/**
 * Imperative handle exposed by {@link CandlestickChart} via `ref`.
 * Lets parents draw overlays/markers and push live updates without re-rendering
 * the whole candle series.
 */
export interface ChartHandle {
  /** Replace all overlay price-lines. */
  setOverlays: (levels: OverlayLevel[]) => void;
  /** Replace all bar markers. */
  setMarkers: (markers: ChartMarker[]) => void;
  /** Update (or append) the most recent candle for live ticking. */
  updateLastCandle: (candle: Candle) => void;
  /** Replace the full candle/volume dataset. */
  setData: (candles: Candle[]) => void;
  /** Fit the visible range to all data. */
  fitContent: () => void;
}

export interface CandlestickChartProps {
  candles: Candle[];
  /** Initial overlays; can also be driven imperatively via the ref. */
  overlays?: OverlayLevel[];
  /** Initial markers; can also be driven imperatively via the ref. */
  markers?: ChartMarker[];
  /** Render the volume histogram pane. Defaults to true. */
  showVolume?: boolean;
  /** Fixed height in px. Width is responsive to the container. Defaults to 480. */
  height?: number;
  /** Dark (default) or light color scheme. */
  theme?: ChartTheme;
  className?: string;
}

export type ChartTheme = 'dark' | 'light';
