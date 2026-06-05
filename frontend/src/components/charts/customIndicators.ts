// customIndicators — the render adapter that plots a server-computed indicator
// spec onto a KLineChart instance.
//
// SECURITY: there is no code execution here. The backend already computed the
// indicator (see indicatorApi); this only registers a KLineChart indicator whose
// `calc` maps the precomputed value arrays onto bars by timestamp. The "custom
// math" never runs in the browser — we're pure data plumbing.

import { registerIndicator } from 'klinecharts';
import type { Chart, KLineData } from 'klinecharts';

import type { ComputeResult } from '../../lib/indicatorApi';

const CANDLE_PANE_ID = 'candle_pane';

/** Handle returned when an indicator is created, needed to remove it later. */
export interface CustomHandle {
  name: string;
  paneId: string;
}

function figureType(t: string): string {
  // KLineChart figure types: 'line' | 'bar' | 'circle'. Map our plot types.
  if (t === 'histogram') return 'bar';
  if (t === 'circle') return 'circle';
  return 'line';
}

/**
 * Register (or override) a KLineChart indicator template named `name` that renders
 * `result`'s precomputed plots. The `calc` is a pure timestamp→value lookup.
 */
function registerSpecIndicator(name: string, result: ComputeResult): void {
  const lookups = result.plots.map((p) => {
    const m = new Map<number, number>();
    for (const pt of p.points) m.set(pt.time, pt.value);
    return m;
  });

  registerIndicator({
    name,
    shortName: result.short_name,
    precision: result.precision,
    figures: result.plots.map((p) => ({
      key: p.step,
      title: `${p.label}: `,
      type: figureType(p.type),
      styles: () => (p.color ? { color: p.color } : {}),
    })),
    calc: (dataList: KLineData[]) =>
      dataList.map((bar) => {
        const row: Record<string, number> = {};
        result.plots.forEach((p, i) => {
          const v = lookups[i].get(bar.timestamp);
          if (v !== undefined) row[p.step] = v;
        });
        return row;
      }),
  });
}

/** Register + create a custom-spec indicator on the chart. Returns its handle. */
export function addSpecIndicator(
  chart: Chart,
  key: string,
  result: ComputeResult,
): CustomHandle | null {
  const name = `CUSTOM_${key}`;
  registerSpecIndicator(name, result);
  const overlay = result.pane === 'overlay';
  const paneId = chart.createIndicator(
    name,
    overlay,
    overlay ? { id: CANDLE_PANE_ID } : undefined,
  );
  return paneId ? { name, paneId } : null;
}

/** Remove a previously-added custom-spec indicator. */
export function removeSpecIndicator(chart: Chart, handle: CustomHandle): void {
  chart.removeIndicator(handle.paneId, handle.name);
}
