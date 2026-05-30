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

// ---------------------------------------------------------------------------
// Workspace chart-engine extensions (MultiPaneChart).
//
// These extend the candlestick foundation so a TradingView-style workspace can
// drive: oscillator sub-panes (RSI/MACD/confluence), marker series on price
// (buy/sell/divergence/insider), background regime / sector-rotation shading,
// and a normalized COMPARE mode (multiple % -from-start lines + SPY benchmark).
// All indicator math is computed upstream (reusing the tested analytics
// modules) and passed in as plain point arrays — these types are render-only.
// ---------------------------------------------------------------------------

/** A single (time, value) point for a line/area/histogram indicator series. */
export interface IndicatorPoint {
  time: UTCTimestamp;
  value: number;
}

/** How an {@link IndicatorSeries} is drawn. */
export type IndicatorSeriesKind = 'line' | 'area' | 'histogram' | 'baseline';

/**
 * Where an {@link IndicatorSeries} lives:
 *  - `'price'`   → overlaid on the main candle pane (e.g. EMA, VWAP).
 *  - `'oscillator'` → a separate sub-pane below price (RSI, MACD, confluence).
 * Series sharing the same `paneId` are stacked into the same sub-pane.
 */
export interface IndicatorSeries {
  /** Stable id (used for incremental update + React keys). */
  id: string;
  /** Legend label, e.g. "RSI(14)", "MACD hist", "Confluence". */
  label: string;
  kind: IndicatorSeriesKind;
  data: IndicatorPoint[];
  color?: string;
  lineWidth?: 1 | 2 | 3 | 4;
  lineStyle?: OverlayLineStyle;
  /**
   * Target pane. `'price'` overlays the candles. Any other string id creates /
   * reuses a dedicated oscillator sub-pane (declaration order = stack order).
   * Defaults to `'price'`.
   */
  paneId?: 'price' | string;
  /** Per-series horizontal guide lines (e.g. RSI 30/70, MACD zero). */
  guides?: IndicatorGuide[];
  /** Baseline value for `kind: 'baseline'` (default 0). */
  baseValue?: number;
  /** Fixed pane height in px when this series owns a new sub-pane. */
  paneHeight?: number;
  /** Hide from render without unmounting (legend stays). Defaults false. */
  hidden?: boolean;
}

/** A horizontal guide line inside an oscillator pane (e.g. RSI 70). */
export interface IndicatorGuide {
  value: number;
  color: string;
  label?: string;
  lineStyle?: OverlayLineStyle;
}

/**
 * A marker pinned to the price series. Superset of {@link ChartMarker} that also
 * supports exact-price anchoring (`atPrice*`) for insider/fill markers and an
 * optional marker size. Maps onto Lightweight-Charts' `SeriesMarker`.
 */
export interface Marker {
  id: string;
  time: UTCTimestamp;
  /** Bar-relative (`aboveBar`…) or exact-price (`atPrice*`) placement. */
  position: MarkerPosition | MarkerPricePosition;
  shape: MarkerShape;
  color: string;
  text?: string;
  /** Marker size multiplier (default 1). */
  size?: number;
  /** Required when `position` is one of the `atPrice*` variants. */
  price?: number;
}

export type MarkerPricePosition = 'atPriceTop' | 'atPriceBottom' | 'atPriceMiddle';

/**
 * A vertical background shading band spanning a time interval on the main pane.
 * Used to paint regime context (HMM state) and sector-rotation phases behind
 * price. `toTime` omitted ⇒ band extends to the latest bar / right edge.
 */
export interface ShadeBand {
  id: string;
  /** Band start (UNIX seconds). */
  fromTime: UTCTimestamp;
  /** Band end (UNIX seconds). Open-ended if omitted. */
  toTime?: UTCTimestamp;
  /** Fill color. Use an rgba() with low alpha so candles stay readable. */
  color: string;
  /** Optional label drawn at the top-left of the band. */
  label?: string;
}

/**
 * One symbol's normalized line in COMPARE mode. Provide raw candles (or a
 * precomputed point series) — the chart normalizes each to "% change from the
 * first visible bar" so disparate price scales overlay meaningfully.
 */
export interface CompareSeries {
  symbol: string;
  /** Closing-price points (UNIX seconds). Normalized to % internally. */
  data: IndicatorPoint[];
  color: string;
  /** Mark this line as the benchmark (e.g. SPY) — rendered dashed/dimmed. */
  isBenchmark?: boolean;
  lineWidth?: 1 | 2 | 3 | 4;
}

/**
 * Imperative handle for {@link MultiPaneChart}. Superset of {@link ChartHandle}
 * adding indicator / shade / compare control. Marker control widens to the
 * richer {@link Marker} type while remaining compatible with {@link ChartMarker}.
 */
export interface MultiPaneChartHandle {
  /** Replace all overlay price-lines on the main pane. */
  setOverlays: (levels: OverlayLevel[]) => void;
  /** Replace all price-series markers (buy/sell/divergence/insider). */
  setMarkers: (markers: Marker[]) => void;
  /** Replace the full set of indicator series (price overlays + oscillators). */
  setIndicators: (series: IndicatorSeries[]) => void;
  /** Replace all background shade bands. */
  setShadeBands: (bands: ShadeBand[]) => void;
  /** Replace the compare-mode line set (no-op outside compare mode). */
  setCompareSeries: (series: CompareSeries[]) => void;
  /** Update (or append) the most recent candle for live ticking. */
  updateLastCandle: (candle: Candle) => void;
  /** Replace the full candle/volume dataset. */
  setData: (candles: Candle[]) => void;
  /** Fit the visible range to all data. */
  fitContent: () => void;
}

export interface MultiPaneChartProps {
  /**
   * Main price candles. Ignored for rendering candles when `mode: 'compare'`,
   * but still used to seed the time scale if no compare series are supplied.
   */
  candles: Candle[];
  /** `'price'` (default) draws candles; `'compare'` draws normalized lines. */
  mode?: MultiPaneChartMode;
  /** Horizontal price-lines on the main pane. */
  overlays?: OverlayLevel[];
  /** Indicator series — `paneId: 'price'` overlay candles, others sub-pane. */
  indicators?: IndicatorSeries[];
  /** Price-series markers. */
  markers?: Marker[];
  /** Background regime / sector-rotation shading bands. */
  shadeBands?: ShadeBand[];
  /** Normalized comparison lines (used when `mode: 'compare'`). */
  compareSeries?: CompareSeries[];
  /** Render the volume histogram pane (price mode only). Defaults to true. */
  showVolume?: boolean;
  /** Fixed height in px for the main price pane. Defaults to 480. */
  height?: number;
  theme?: ChartTheme;
  className?: string;
}

export type MultiPaneChartMode = 'price' | 'compare';
