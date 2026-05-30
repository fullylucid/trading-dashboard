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

export default { getChart, getAiRead };
