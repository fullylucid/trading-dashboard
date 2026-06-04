// klineApi — adapts the existing backend OHLCV feed to KLineChart's data shape.
//
// We REUSE the UDF datafeed (`backend/udf_routes.py`, GET /api/udf/history) — it
// already serves yfinance OHLCV across every resolution the Charts tab exposes
// (1/5/15/60/D/W), unlike the daily-only `/api/chart/{symbol}`. The only work
// here is converting the UDF column-oriented payload ({s,t,o,h,l,c,v}) into the
// row-oriented {timestamp, open, high, low, close, volume} KLineChart wants, and
// promoting the UDF epoch-SECONDS timestamps to the epoch-MILLISECONDS KLineChart
// expects. No backend change.

import axios from 'axios';
import type { KLineData } from 'klinecharts';

export type Resolution = '1' | '5' | '15' | '60' | 'D' | 'W';

/** Human labels for the timeframe selector, in display order. */
export const TIMEFRAMES: { value: Resolution; label: string }[] = [
  { value: '1', label: '1m' },
  { value: '5', label: '5m' },
  { value: '15', label: '15m' },
  { value: '60', label: '1H' },
  { value: 'D', label: '1D' },
  { value: 'W', label: '1W' },
];

// How far back to request per resolution. Bounded by yfinance's own intraday
// history limits (1m ≈ 7d, 5m/15m ≈ 60d, 60m ≈ 730d) so requests don't come
// back empty; daily/weekly get multi-year windows.
const LOOKBACK_DAYS: Record<Resolution, number> = {
  '1': 7,
  '5': 30,
  '15': 60,
  '60': 180,
  D: 730,
  W: 1825,
};

interface UdfHistory {
  s: 'ok' | 'no_data' | 'error';
  t?: number[];
  o?: number[];
  h?: number[];
  l?: number[];
  c?: number[];
  v?: number[];
  errmsg?: string;
}

/**
 * Fetch OHLCV for `symbol` at `resolution` and return ascending KLineChart bars.
 * Resolves to `[]` when the feed reports no data; throws on an error status so the
 * caller can surface it.
 */
export async function fetchKLineData(
  symbol: string,
  resolution: Resolution,
  signal?: AbortSignal,
): Promise<KLineData[]> {
  const to = Math.floor(Date.now() / 1000);
  const from = to - LOOKBACK_DAYS[resolution] * 86400;

  const { data } = await axios.get<UdfHistory>('/api/udf/history', {
    params: { symbol, resolution, from, to },
    signal,
  });

  if (data.s === 'no_data') return [];
  if (data.s !== 'ok' || !data.t) {
    throw new Error(data.errmsg || 'Chart data unavailable');
  }

  const { t, o = [], h = [], l = [], c = [], v = [] } = data;
  const out: KLineData[] = [];
  for (let i = 0; i < t.length; i++) {
    out.push({
      timestamp: t[i] * 1000, // UDF is epoch-seconds; KLineChart wants ms
      open: o[i],
      high: h[i],
      low: l[i],
      close: c[i],
      volume: v[i] ?? 0,
    });
  }
  return out;
}
