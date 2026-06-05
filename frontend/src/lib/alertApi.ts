// alertApi — client for chart-condition smart alerts (backend /api/alerts/*).
// An alert = an indicator spec + a condition on one of its plots; the backend
// evaluates it against the symbol's latest bars and delivers (Telegram) on a new
// bar that meets the condition.

import axios from 'axios';

import type { IndicatorSpec } from './indicatorApi';

export type AlertOp = 'gt' | 'lt' | 'cross_up' | 'cross_down';

export interface ChartAlert {
  id: string;
  symbol: string;
  plot_step: string;
  op: AlertOp;
  value: number;
  channel: string;
  note: string;
  created_at: string;
  active: boolean;
  last_fired_at: string | null;
}

export interface CreateAlertBody {
  symbol: string;
  spec: IndicatorSpec;
  plot_step: string;
  op: AlertOp;
  value: number;
  channel?: string;
  note?: string;
}

export async function listAlerts(): Promise<ChartAlert[]> {
  const { data } = await axios.get<{ alerts: ChartAlert[] }>('/api/alerts');
  return data.alerts ?? [];
}

export async function createAlert(body: CreateAlertBody): Promise<ChartAlert> {
  const { data } = await axios.post<ChartAlert>('/api/alerts', body);
  return data;
}

export async function deleteAlert(id: string): Promise<boolean> {
  const { data } = await axios.delete<{ deleted: boolean }>(`/api/alerts/${id}`);
  return data.deleted;
}

/** A bare close-price spec — the basis for price-level alerts. */
export function priceSpec(symbol: string): IndicatorSpec {
  return {
    name: `${symbol} price`,
    short_name: 'PRICE',
    steps: [{ id: 'c', op: 'series', ref: 'close' }],
    plots: [{ step: 'c', label: 'Close' }],
  };
}
