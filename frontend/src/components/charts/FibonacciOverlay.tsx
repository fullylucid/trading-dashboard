// FibonacciOverlay — compute Fibonacci retracement + extension levels from the
// most recent significant swing high/low in a candle series.
//
// This module is pure/presentation-agnostic: it exposes `computeFibLevels`,
// which turns a `Candle[]` into `OverlayLevel[]` ready to hand to
// `CandlestickChart` (via the `overlays` prop or the imperative `setOverlays`).
// It also exports a tiny declarative `<FibonacciOverlay>` component that pushes
// the computed levels onto a chart handle for callers that prefer JSX wiring.
//
// Swing detection: we locate the most recent confirmed swing pivots (strict
// local extrema with `order` confirming bars each side, so the last `order`
// bars are never treated as confirmed — no look-ahead), then anchor the fib
// grid to the most recent high/low *pair*, oriented by which extreme is more
// recent (up-swing vs down-swing).

import { useEffect } from 'react';
import type { Candle, ChartHandle, OverlayLevel } from './types';

/** Standard retracement ratios (fraction of the swing range). */
const RETRACEMENT_RATIOS: readonly number[] = [0.236, 0.382, 0.5, 0.618, 0.786];
/** Standard extension ratios (beyond the swing range). */
const EXTENSION_RATIOS: readonly number[] = [1.272, 1.618];

/** Direction of the anchoring swing. */
export type SwingDirection = 'up' | 'down';

export interface SwingAnchor {
  /** Index of the swing low in the candle series. */
  lowIndex: number;
  /** Index of the swing high in the candle series. */
  highIndex: number;
  /** Price of the swing low. */
  lowPrice: number;
  /** Price of the swing high. */
  highPrice: number;
  /**
   * 'up' when the low precedes the high (rally → retracements drop from high);
   * 'down' when the high precedes the low (decline → retracements rise from low).
   */
  direction: SwingDirection;
}

export interface FibPalette {
  retracement: string;
  extension: string;
  /** Color for the 0% / 100% anchor lines. */
  anchor: string;
}

const DEFAULT_PALETTE: FibPalette = {
  retracement: '#c792ea',
  extension: '#f78c6c',
  anchor: '#787b86',
};

export interface FibOptions {
  /** Confirming bars each side required for a swing pivot. Default 3. */
  order?: number;
  /** Include the 1.272 / 1.618 extension levels. Default true. */
  includeExtensions?: boolean;
  palette?: Partial<FibPalette>;
}

/** Strict local-maximum indices with `order` confirming bars each side. */
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

/** Strict local-minimum indices with `order` confirming bars each side. */
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

/**
 * Find the most recent significant swing high/low pair to anchor the fib grid.
 * Returns `null` when the series is too short to confirm any pivot.
 */
export function findRecentSwing(candles: Candle[], order = 3): SwingAnchor | null {
  if (candles.length < order * 2 + 1) return null;

  const highs = candles.map((c) => c.high);
  const lows = candles.map((c) => c.low);

  const highPivots = localMaxIndices(highs, order);
  const lowPivots = localMinIndices(lows, order);

  // Fall back to the global confirmed extreme when one side has no pivot.
  const lastHighIdx =
    highPivots.length > 0 ? highPivots[highPivots.length - 1] : null;
  const lastLowIdx = lowPivots.length > 0 ? lowPivots[lowPivots.length - 1] : null;

  if (lastHighIdx === null && lastLowIdx === null) return null;

  // If only one side confirmed, pair it with the opposing global extreme within
  // the confirmable region so we always get a valid range.
  const confirmableEnd = candles.length - order;
  let highIndex: number;
  let lowIndex: number;

  if (lastHighIdx !== null && lastLowIdx !== null) {
    highIndex = lastHighIdx;
    lowIndex = lastLowIdx;
  } else if (lastHighIdx !== null) {
    highIndex = lastHighIdx;
    lowIndex = argExtreme(lows, 0, confirmableEnd, 'min');
  } else {
    // lastLowIdx !== null
    lowIndex = lastLowIdx as number;
    highIndex = argExtreme(highs, 0, confirmableEnd, 'max');
  }

  const highPrice = highs[highIndex];
  const lowPrice = lows[lowIndex];
  if (!(highPrice > lowPrice)) return null;

  const direction: SwingDirection = lowIndex < highIndex ? 'up' : 'down';
  return { lowIndex, highIndex, lowPrice, highPrice, direction };
}

function argExtreme(
  values: number[],
  start: number,
  end: number,
  kind: 'min' | 'max',
): number {
  let bestIdx = start;
  let best = values[start];
  for (let i = start + 1; i < end; i += 1) {
    const v = values[i];
    if ((kind === 'max' && v > best) || (kind === 'min' && v < best)) {
      best = v;
      bestIdx = i;
    }
  }
  return bestIdx;
}

function fmt(price: number): string {
  return price.toFixed(2);
}

/**
 * Compute Fibonacci retracement + extension price levels for a candle series,
 * returning ready-to-draw {@link OverlayLevel}s. Empty array if no swing found.
 */
export function computeFibLevels(
  candles: Candle[],
  options: FibOptions = {},
): OverlayLevel[] {
  const order = options.order ?? 3;
  const includeExtensions = options.includeExtensions ?? true;
  const palette: FibPalette = { ...DEFAULT_PALETTE, ...(options.palette ?? {}) };

  const swing = findRecentSwing(candles, order);
  if (!swing) return [];

  const { highPrice, lowPrice, direction } = swing;
  const range = highPrice - lowPrice;
  const levels: OverlayLevel[] = [];

  // 0% and 100% anchors.
  levels.push({
    id: 'fib-0',
    price: direction === 'up' ? highPrice : lowPrice,
    label: `Fib 0% ${fmt(direction === 'up' ? highPrice : lowPrice)}`,
    color: palette.anchor,
    lineStyle: 'solid',
    lineWidth: 1,
  });
  levels.push({
    id: 'fib-100',
    price: direction === 'up' ? lowPrice : highPrice,
    label: `Fib 100% ${fmt(direction === 'up' ? lowPrice : highPrice)}`,
    color: palette.anchor,
    lineStyle: 'solid',
    lineWidth: 1,
  });

  for (const ratio of RETRACEMENT_RATIOS) {
    // In an up-swing retracements pull DOWN from the high; in a down-swing they
    // push UP from the low. Both reduce to: level = high - ratio*range for 'up'
    // and level = low + ratio*range for 'down'.
    const price =
      direction === 'up' ? highPrice - ratio * range : lowPrice + ratio * range;
    levels.push({
      id: `fib-ret-${ratio}`,
      price,
      label: `Fib ${(ratio * 100).toFixed(1)}% ${fmt(price)}`,
      color: palette.retracement,
      lineStyle: ratio === 0.618 ? 'solid' : 'dashed',
      lineWidth: ratio === 0.618 ? 2 : 1,
    });
  }

  if (includeExtensions) {
    for (const ratio of EXTENSION_RATIOS) {
      // Extensions project beyond the move in its direction of travel.
      const price =
        direction === 'up'
          ? lowPrice + ratio * range
          : highPrice - ratio * range;
      levels.push({
        id: `fib-ext-${ratio}`,
        price,
        label: `Fib ${(ratio * 100).toFixed(1)}% ext ${fmt(price)}`,
        color: palette.extension,
        lineStyle: 'dotted',
        lineWidth: 1,
      });
    }
  }

  return levels;
}

export interface FibonacciOverlayProps {
  /** The candle series to anchor the fib grid to. */
  candles: Candle[];
  /** Imperative chart handle to push the levels onto. */
  chartRef: React.RefObject<ChartHandle | null>;
  options?: FibOptions;
  /** Toggle visibility without unmounting. When false, clears the overlays. */
  visible?: boolean;
  /** Callback with the computed levels (e.g. for a legend). */
  onLevels?: (levels: OverlayLevel[]) => void;
}

/**
 * Declarative wrapper: recomputes fib levels whenever the candles change and
 * pushes them onto the given chart handle. Renders nothing.
 */
export function FibonacciOverlay(props: FibonacciOverlayProps): null {
  const { candles, chartRef, options, visible = true, onLevels } = props;

  useEffect(() => {
    const handle = chartRef.current;
    if (!handle) return;
    const levels = visible ? computeFibLevels(candles, options) : [];
    handle.setOverlays(levels);
    onLevels?.(levels);
    // chartRef is a stable ref; options is treated as value-stable by callers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candles, visible]);

  return null;
}

export default FibonacciOverlay;
