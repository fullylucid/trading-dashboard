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
  // 'circle' is a frontend-only render hint for sparse markers (the backend
  // engine only emits line/histogram/baseline); see chartLayers.
  type: 'line' | 'histogram' | 'baseline' | 'circle';
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

/** A spec saved in the arsenal (the approved-spec library). */
export interface ArsenalItem {
  id: string;
  name: string;
  short_name: string;
  pane: 'overlay' | 'separate';
  source: string;
  tags: string[];
  created_at: string;
  spec: IndicatorSpec;
}

/** List saved arsenal specs (newest first). Empty if storage is unavailable. */
export async function listArsenal(): Promise<ArsenalItem[]> {
  const { data } = await axios.get<{ items: ArsenalItem[] }>('/api/indicator/arsenal');
  return data.items ?? [];
}

/** Validate + persist a spec into the arsenal. */
export async function saveToArsenal(
  spec: IndicatorSpec,
  source = 'manual',
  tags: string[] = [],
): Promise<ArsenalItem> {
  const { data } = await axios.post<ArsenalItem>('/api/indicator/arsenal', { spec, source, tags });
  return data;
}

/** Remove a saved arsenal spec. */
export async function deleteFromArsenal(id: string): Promise<boolean> {
  const { data } = await axios.delete<{ deleted: boolean }>(`/api/indicator/arsenal/${id}`);
  return data.deleted;
}
