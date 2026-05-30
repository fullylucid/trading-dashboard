// Typed axios client for the chart endpoints.
//
//   GET  /api/chart/{symbol}        -> OHLCV candles (+ optional overlays)
//   POST /api/chart/{symbol}/ai-read -> on-demand Claude TA annotation
//
// Candles are normalized from the backend's snake_case / epoch-ms shape into the
// {@link Candle} type the chart components consume (UNIX seconds time).

import axios from 'axios';
import type { AxiosInstance } from 'axios';
import type { Candle, OverlayLevel, RawCandle } from '../components/charts/types';
import type { UTCTimestamp } from 'lightweight-charts';

const client: AxiosInstance = axios.create({
  baseURL: '/api',
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
});

/** Response from GET /api/chart/{symbol}. */
export interface ChartResponse {
  symbol: string;
  candles: Candle[];
  /** Server-side precomputed overlays (S/R, fib, etc.), if any. */
  overlays: OverlayLevel[];
  /** Timeframe label echoed by the server (e.g. "1D", "1h"). */
  timeframe: string;
}

interface RawChartResponse {
  symbol?: string;
  timeframe?: string;
  candles?: RawCandle[];
  data?: RawCandle[];
  overlays?: OverlayLevel[];
}

/** A single level annotation in an AI read. */
export interface AiReadLevel {
  price: number;
  label: string;
  kind: 'support' | 'resistance' | 'target' | 'stop' | 'fib' | 'pivot';
}

/** Response from POST /api/chart/{symbol}/ai-read. */
export interface AiReadResponse {
  symbol: string;
  /** Plain-language TA thesis. */
  thesis: string;
  /** Key levels Claude flagged, ready to render as overlays. */
  levels: AiReadLevel[];
  /** Optional directional bias. */
  bias?: 'bullish' | 'bearish' | 'neutral';
}

export interface ChartQuery {
  /** Timeframe key, e.g. "1D" | "1h" | "5m". */
  timeframe?: string;
  /** How many bars back to request. */
  lookbackDays?: number;
}

export interface AiReadRequest {
  timeframe?: string;
  /** Optional extra context for the model (current signals, position, etc.). */
  context?: Record<string, unknown>;
}

function toUtcSeconds(ts: number | string): UTCTimestamp {
  if (typeof ts === 'number') {
    // Heuristic: treat values larger than a year-2001 epoch in seconds as ms.
    const seconds = ts > 1e12 ? Math.floor(ts / 1000) : Math.floor(ts);
    return seconds as UTCTimestamp;
  }
  const ms = Date.parse(ts);
  return Math.floor((Number.isNaN(ms) ? Date.now() : ms) / 1000) as UTCTimestamp;
}

function normalizeCandle(raw: RawCandle): Candle {
  return {
    time: toUtcSeconds(raw.timestamp),
    open: raw.open,
    high: raw.high,
    low: raw.low,
    close: raw.close,
    volume: raw.volume == null ? undefined : raw.volume,
  };
}

/** Fetch and normalize candles for a symbol. */
export async function getChart(symbol: string, query: ChartQuery = {}): Promise<ChartResponse> {
  const res = await client.get<RawChartResponse>(`/chart/${encodeURIComponent(symbol)}`, {
    params: {
      timeframe: query.timeframe,
      lookback_days: query.lookbackDays,
    },
  });
  const body = res.data;
  const rawCandles = body.candles ?? body.data ?? [];
  return {
    symbol: body.symbol ?? symbol.toUpperCase(),
    candles: rawCandles.map(normalizeCandle),
    overlays: body.overlays ?? [],
    timeframe: body.timeframe ?? query.timeframe ?? '1D',
  };
}

/** Request an on-demand AI technical read for a symbol. */
export async function getAiRead(symbol: string, req: AiReadRequest = {}): Promise<AiReadResponse> {
  const res = await client.post<AiReadResponse>(
    `/chart/${encodeURIComponent(symbol)}/ai-read`,
    { timeframe: req.timeframe, context: req.context },
  );
  return res.data;
}

// ---------------------------------------------------------------------------
// /full — server-enriched payload (overlays + indicators + markers + context)
//
// The backend (`GET /api/chart/{symbol}/full`) computes ALL indicator math via
// the tested `analytics` package (completed bars only, no look-ahead). The
// frontend is pure rendering: these types mirror the JSON shapes exactly so
// ChartWorkspace can marshal them straight onto the MultiPaneChart engine.
// ---------------------------------------------------------------------------

/** A history range token accepted by the chart endpoints. */
export type ChartRange = '5d' | '1m' | '3m' | '6m' | '1y' | '2y' | '5y' | 'max';

/** `overlays.fib_levels` — auto-anchored Fibonacci levels. */
export interface FullFibLevels {
  direction: 'up' | 'down' | null;
  swing_high: number | null;
  swing_low: number | null;
  retracements: Record<string, number>;
  extensions: Record<string, number>;
}

/** `overlays.support_resistance` — pivot S/R levels (mirrors ScanSupportResistance). */
export interface FullSupportResistance {
  support?: number | null;
  resistance?: number | null;
  supports?: number[] | null;
  resistances?: number[] | null;
}

export interface FullOverlays {
  fib_levels?: FullFibLevels;
  support_resistance?: FullSupportResistance;
}

/** One MACD bar: line / signal / histogram. */
export interface MacdPoint {
  time: number;
  macd: number;
  signal: number;
  hist: number;
}

export interface FullIndicators {
  /** RSI(14) series, `[{time, value}]`. */
  rsi: Array<{ time: number; value: number }>;
  /** MACD(12/26/9) series. */
  macd: MacdPoint[];
}

/** A signal event marker: MACD cross / RSI divergence / breakout. */
export interface SignalEventMarker {
  time: number;
  type: 'cross' | 'divergence' | 'breakout';
  label: string;
}

export interface FullMarkers {
  signal_events: SignalEventMarker[];
  insider_buys: Array<{ time: number; label: string }>;
}

/** `confluence` — single CURRENT alert summary (mirrors analytics.alerts.score_alert). */
export interface ConfluenceRead {
  symbol: string;
  bucket: 'alert' | 'watch' | 'log';
  confidence: number;
  direction: 'bullish' | 'bearish' | 'neutral';
  contributing_factors?: Array<{
    factor: string;
    detail: string;
    points: number;
    direction: string;
  }>;
  score_breakdown?: { bullish: number; bearish: number };
}

/** `context.regime` — market-regime read (subset used by the workspace). */
export interface ChartRegime {
  regime_class: string | null;
  label: string | null;
  trend_direction?: string | null;
  volatility_regime?: string | null;
  size_multiplier?: number | null;
  note?: string | null;
}

/** `context.sector_rotation` — this symbol's sector rotation tag. */
export interface ChartSectorRotation {
  sector?: string | null;
  etf?: string | null;
  rotation_score?: number | null;
  status?: 'rotating-IN' | 'rotating-OUT' | 'neutral' | null;
  phase?: string | null;
  alert?: string | null;
}

export interface ChartContext {
  regime?: ChartRegime | null;
  sector_rotation?: ChartSectorRotation | null;
}

/** Response from GET /api/chart/{symbol}/full. */
export interface ChartFullResponse {
  symbol: string;
  range: string;
  interval: string;
  count: number;
  candles: Candle[];
  indicators: FullIndicators;
  overlays: FullOverlays;
  markers: FullMarkers;
  /** Cumulative % outperformance vs SPY, `[{time, value}]`. */
  rs_vs_spy: Array<{ time: number; value: number }>;
  context: ChartContext;
  confluence: ConfluenceRead | null;
  data_gaps: string[];
}

/** Raw `/full` body (candles arrive already in {time(s),o,h,l,c,v} form here). */
interface RawChartFullResponse {
  symbol?: string;
  range?: string;
  interval?: string;
  count?: number;
  candles?: RawCandle[];
  indicators?: FullIndicators;
  overlays?: FullOverlays;
  markers?: FullMarkers;
  rs_vs_spy?: Array<{ time: number; value: number }>;
  context?: ChartContext;
  confluence?: ConfluenceRead | null;
  data_gaps?: string[];
}

/** Fetch the server-enriched chart payload (overlays + indicators + context). */
export async function getChartFull(
  symbol: string,
  range: ChartRange = '1y',
): Promise<ChartFullResponse> {
  const res = await client.get<RawChartFullResponse>(
    `/chart/${encodeURIComponent(symbol)}/full`,
    { params: { range } },
  );
  const body = res.data;
  return {
    symbol: body.symbol ?? symbol.toUpperCase(),
    range: body.range ?? range,
    interval: body.interval ?? '1d',
    count: body.count ?? (body.candles?.length ?? 0),
    candles: (body.candles ?? []).map(normalizeCandle),
    indicators: body.indicators ?? { rsi: [], macd: [] },
    overlays: body.overlays ?? {},
    markers: body.markers ?? { signal_events: [], insider_buys: [] },
    rs_vs_spy: body.rs_vs_spy ?? [],
    context: body.context ?? {},
    confluence: body.confluence ?? null,
    data_gaps: body.data_gaps ?? [],
  };
}

// ---------------------------------------------------------------------------
// /portfolio — blended, normalized portfolio equity / return series
// ---------------------------------------------------------------------------

export interface PortfolioHolding {
  symbol: string;
  weight: number;
}

/** Response from GET /api/chart/portfolio. */
export interface ChartPortfolioResponse {
  range: string;
  interval: string;
  /** Growth of $1, indexed to 1.0 at window start: `[{time, value}]`. */
  equity: Array<{ time: number; value: number }>;
  /** Cumulative % return rebased to 0% at start: `[{time, value}]`. */
  returns: Array<{ time: number; value: number }>;
  holdings: PortfolioHolding[];
  weights_used: Record<string, number>;
  skipped: string[];
  count: number;
  /** Present (= "no_holdings") when the book is empty. */
  note?: string;
}

/** Fetch the portfolio-weighted equity/return series. */
export async function getChartPortfolio(
  range: ChartRange = '1y',
): Promise<ChartPortfolioResponse> {
  const res = await client.get<ChartPortfolioResponse>('/chart/portfolio', {
    params: { range },
  });
  const body = res.data;
  return {
    range: body.range ?? range,
    interval: body.interval ?? '1d',
    equity: body.equity ?? [],
    returns: body.returns ?? [],
    holdings: body.holdings ?? [],
    weights_used: body.weights_used ?? {},
    skipped: body.skipped ?? [],
    count: body.count ?? (body.equity?.length ?? 0),
    note: body.note,
  };
}

export default { getChart, getAiRead, getChartFull, getChartPortfolio };
