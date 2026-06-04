// indicatorApi — client for the constrained indicator-spec engine (backend
// /api/indicator/*). A spec is DATA (a bounded DAG of whitelisted ops over OHLCV),
// never code; the backend computes it deterministically and returns render-ready
// plot arrays. The frontend passes the exact bars it's already showing, so the
// computed series align on-chart. See backend/indicator_spec.py.

import axios from 'axios';
import type { KLineData } from 'klinecharts';

/** One step in the spec DAG (op-specific fields kept loose; the backend validates). */
export interface IndicatorStep {
  id: string;
  op: string;
  [k: string]: unknown;
}

export interface IndicatorPlotDef {
  step: string;
  label?: string;
  type?: 'line' | 'histogram' | 'baseline';
  color?: string;
}

export interface IndicatorSpec {
  name: string;
  short_name?: string;
  pane?: 'overlay' | 'separate';
  precision?: number;
  steps: IndicatorStep[];
  plots: IndicatorPlotDef[];
}

export interface ComputedPlot {
  step: string;
  label: string;
  type: 'line' | 'histogram' | 'baseline';
  color?: string;
  points: { time: number; value: number }[];
}

export interface ComputeResult {
  name: string;
  short_name: string;
  pane: 'overlay' | 'separate';
  precision: number;
  plots: ComputedPlot[];
  bars: number;
}

export interface ValidateResult {
  valid: boolean;
  errors?: string[];
  normalized?: IndicatorSpec;
}

/** Compute a spec over the supplied bars (the bars the chart is rendering). */
export async function computeIndicator(
  spec: IndicatorSpec,
  bars: KLineData[],
  signal?: AbortSignal,
): Promise<ComputeResult> {
  const { data } = await axios.post<ComputeResult>(
    '/api/indicator/compute',
    { spec, bars },
    { signal },
  );
  return data;
}

/** Validate a spec without computing. Never throws on a *spec* error — check `.valid`. */
export async function validateIndicator(spec: unknown): Promise<ValidateResult> {
  const { data } = await axios.post<ValidateResult>('/api/indicator/validate', { spec });
  return data;
}
