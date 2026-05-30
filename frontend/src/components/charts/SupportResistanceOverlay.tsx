// SupportResistanceOverlay — derive support/resistance price levels either from
// the candle series (swing-pivot detection) OR from the scan's precomputed
// signals block (`analytics.signals.support_resistance`), and turn them into
// drawable `OverlayLevel[]`.
//
// Two entry points:
//   - `computeSupportResistance(candles, opts)` — local swing-pivot derivation.
//   - `levelsFromScanSignals(signals, opts)` — adopt server-computed levels.
// Both return `OverlayLevel[]`. A small declarative `<SupportResistanceOverlay>`
// pushes them onto a chart handle.

import { useEffect } from 'react';
import type { Candle, ChartHandle, OverlayLevel } from './types';

/**
 * Shape of the `support_resistance` block emitted by
 * `backend/analytics/signals.py::support_resistance`. All fields optional so we
 * degrade gracefully when the scan omits a side.
 */
export interface ScanSupportResistance {
  support?: number | null;
  resistance?: number | null;
  supports?: number[] | null;
  resistances?: number[] | null;
}

export interface SRPalette {
  support: string;
  resistance: string;
}

const DEFAULT_PALETTE: SRPalette = {
  support: '#26a69a',
  resistance: '#ef5350',
};

export interface SROptions {
  /** Confirming bars each side for a swing pivot. Default 3. */
  order?: number;
  /** Max levels to draw per side. Default 3. */
  maxPerSide?: number;
  palette?: Partial<SRPalette>;
}

function localMaxIndices(values: number[], order: number): number[] {
  const out: number[] = [];
  for (let i = order; i < values.length - order; i += 1) {
    const v = values[i];
    let isMax = true;
    for (let k = 1; k <= order; k += 1) {
      if (values[i - k] >= v || values[i + k] >= v) {
        isMax = false;
        break;
      }
    }
    if (isMax) out.push(i);
  }
  return out;
}

function localMinIndices(values: number[], order: number): number[] {
  const out: number[] = [];
  for (let i = order; i < values.length - order; i += 1) {
    const v = values[i];
    let isMin = true;
    for (let k = 1; k <= order; k += 1) {
      if (values[i - k] <= v || values[i + k] <= v) {
        isMin = false;
        break;
      }
    }
    if (isMin) out.push(i);
  }
  return out;
}

function fmt(price: number): string {
  return price.toFixed(2);
}

function resolvePalette(p?: Partial<SRPalette>): SRPalette {
  return { ...DEFAULT_PALETTE, ...(p ?? {}) };
}

/**
 * Derive nearest support/resistance levels from confirmed swing pivots in the
 * candle series. Resistances are swing highs above the last close; supports are
 * swing lows below it. Closest levels first, capped at `maxPerSide`.
 */
export function computeSupportResistance(
  candles: Candle[],
  options: SROptions = {},
): OverlayLevel[] {
  const order = options.order ?? 3;
  const maxPerSide = options.maxPerSide ?? 3;
  const palette = resolvePalette(options.palette);

  if (candles.length < order * 2 + 1) return [];

  const highs = candles.map((c) => c.high);
  const lows = candles.map((c) => c.low);
  const last = candles[candles.length - 1].close;

  const highPivots = localMaxIndices(highs, order).map((i) => highs[i]);
  const lowPivots = localMinIndices(lows, order).map((i) => lows[i]);

  // Dedupe, filter relative to price, sort by proximity to last close.
  const resistances = Array.from(new Set(highPivots.filter((p) => p > last)))
    .sort((a, b) => a - b)
    .slice(0, maxPerSide);
  const supports = Array.from(new Set(lowPivots.filter((p) => p < last)))
    .sort((a, b) => b - a)
    .slice(0, maxPerSide);

  return buildLevels(supports, resistances, palette);
}

/**
 * Build overlays from the scan's precomputed `support_resistance` block.
 * Prefers the multi-level `supports`/`resistances` arrays, falling back to the
 * single nearest `support`/`resistance`.
 */
export function levelsFromScanSignals(
  signals: ScanSupportResistance,
  options: SROptions = {},
): OverlayLevel[] {
  const maxPerSide = options.maxPerSide ?? 3;
  const palette = resolvePalette(options.palette);

  const supports = (
    signals.supports && signals.supports.length > 0
      ? signals.supports
      : signals.support != null
        ? [signals.support]
        : []
  ).slice(0, maxPerSide);

  const resistances = (
    signals.resistances && signals.resistances.length > 0
      ? signals.resistances
      : signals.resistance != null
        ? [signals.resistance]
        : []
  ).slice(0, maxPerSide);

  return buildLevels(supports, resistances, palette);
}

function buildLevels(
  supports: number[],
  resistances: number[],
  palette: SRPalette,
): OverlayLevel[] {
  const levels: OverlayLevel[] = [];

  supports.forEach((price, idx) => {
    levels.push({
      id: `sr-support-${idx}`,
      price,
      label: `${idx === 0 ? 'Support' : `S${idx + 1}`} ${fmt(price)}`,
      color: palette.support,
      lineStyle: idx === 0 ? 'solid' : 'dashed',
      lineWidth: idx === 0 ? 2 : 1,
    });
  });

  resistances.forEach((price, idx) => {
    levels.push({
      id: `sr-resistance-${idx}`,
      price,
      label: `${idx === 0 ? 'Resistance' : `R${idx + 1}`} ${fmt(price)}`,
      color: palette.resistance,
      lineStyle: idx === 0 ? 'solid' : 'dashed',
      lineWidth: idx === 0 ? 2 : 1,
    });
  });

  return levels;
}

export interface SupportResistanceOverlayProps {
  candles: Candle[];
  chartRef: React.RefObject<ChartHandle | null>;
  /** When provided, these scan levels take precedence over local derivation. */
  scanLevels?: ScanSupportResistance | null;
  options?: SROptions;
  visible?: boolean;
  onLevels?: (levels: OverlayLevel[]) => void;
}

/**
 * Declarative S/R overlay. Uses `scanLevels` when present, otherwise derives
 * from the candle series. Pushes onto the chart handle. Renders nothing.
 */
export function SupportResistanceOverlay(
  props: SupportResistanceOverlayProps,
): null {
  const { candles, chartRef, scanLevels, options, visible = true, onLevels } =
    props;

  useEffect(() => {
    const handle = chartRef.current;
    if (!handle) return;
    let levels: OverlayLevel[] = [];
    if (visible) {
      levels = scanLevels
        ? levelsFromScanSignals(scanLevels, options)
        : computeSupportResistance(candles, options);
    }
    handle.setOverlays(levels);
    onLevels?.(levels);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candles, scanLevels, visible]);

  return null;
}

export default SupportResistanceOverlay;
