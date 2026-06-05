// chartFullApi — client for the server-enriched chart payload (GET /api/chart/{symbol}/full).
//
// The backend already computes Fibonacci + support/resistance levels, buy/sell + insider
// markers, and a relative-strength-vs-SPY line (all via the tested analytics package, on
// completed bars, no look-ahead). These were rendered by the old Lightweight-Charts stack
// that we removed; this client re-homes that data onto KLineChart. NOTE: all times in this
// payload are epoch SECONDS (KLineChart wants ms — multiply by 1000).

import axios from 'axios';

export interface FibLevels {
  direction: 'up' | 'down' | null;
  swing_high: number | null;
  swing_low: number | null;
  retracements: Record<string, number>;
  extensions: Record<string, number>;
}

export interface SupportResistance {
  support: number | null;
  resistance: number | null;
  supports: number[];
  resistances: number[];
}

export interface SignalMarker {
  time: number; // epoch SECONDS
  type: string; // "cross" | "divergence" | "breakout"
  label: string;
}

export interface InsiderMarker {
  time: number; // epoch SECONDS
  label: string;
}

export interface ChartFullResponse {
  symbol: string;
  range: string;
  interval: string;
  overlays?: { fib_levels?: FibLevels; support_resistance?: SupportResistance };
  markers?: { signal_events?: SignalMarker[]; insider_buys?: InsiderMarker[] };
  rs_vs_spy?: { time: number; value: number }[]; // time epoch SECONDS
  data_gaps?: string[];
}

/** Fetch the server-enriched chart payload (levels, markers, RS line). */
export async function fetchChartFull(
  symbol: string,
  range = '1y',
  signal?: AbortSignal,
): Promise<ChartFullResponse> {
  const { data } = await axios.get<ChartFullResponse>(
    `/api/chart/${encodeURIComponent(symbol)}/full`,
    { params: { range }, signal },
  );
  return data;
}
