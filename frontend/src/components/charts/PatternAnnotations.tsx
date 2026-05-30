// PatternAnnotations — turn the scan's detected patterns / divergences into
// bar-pinned `ChartMarker[]` (arrows, labels) to render on the candlestick chart.
//
// The scan's `signals` block carries discrete events (divergences, gaps,
// detected chart patterns, swing pivots). This module maps those into markers,
// anchoring each to the nearest candle by timestamp. Pure derivation in
// `markersFromPatterns`; a declarative `<PatternAnnotations>` pushes onto a
// chart handle.

import { useEffect } from 'react';
import type {
  Candle,
  ChartHandle,
  ChartMarker,
  MarkerPosition,
  MarkerShape,
} from './types';
import type { UTCTimestamp } from 'lightweight-charts';

/** Bias of a detected event, driving marker color. */
export type PatternBias = 'bullish' | 'bearish' | 'neutral';

/**
 * A detected pattern / divergence event from the scan's signals block.
 * `time` is a UNIX timestamp in seconds (matching the candle series). When the
 * scan reports an index instead of a time, callers can pre-resolve it; if both
 * are absent the marker anchors to the latest bar.
 */
export interface PatternEvent {
  id: string;
  /** e.g. "Bullish RSI Divergence", "Ascending Triangle", "Gap Up". */
  label: string;
  bias: PatternBias;
  /** UNIX seconds; aligned to the nearest candle. Optional. */
  time?: UTCTimestamp;
  /** Alternative anchor: index into the candle series. Optional. */
  index?: number;
  /** Override marker placement. Defaults from bias. */
  position?: MarkerPosition;
  /** Override marker shape. Defaults from bias. */
  shape?: MarkerShape;
}

/**
 * Loose shape of the scan `signals` block we read from. Every field optional so
 * we degrade gracefully across scan versions.
 */
export interface ScanSignalsBlock {
  /** Divergence result, e.g. from `detect_divergence`. */
  divergence?: {
    type?: 'bullish' | 'bearish' | 'none' | null;
    time?: number | null;
    index?: number | null;
  } | null;
  /** Named chart patterns the scan flagged. */
  patterns?: Array<{
    name?: string;
    bias?: PatternBias | null;
    time?: number | null;
    index?: number | null;
  }> | null;
  /** Gap event. */
  gap?: { pct?: number | null; time?: number | null } | null;
}

export interface PatternPalette {
  bullish: string;
  bearish: string;
  neutral: string;
}

const DEFAULT_PALETTE: PatternPalette = {
  bullish: '#26a69a',
  bearish: '#ef5350',
  neutral: '#787b86',
};

function defaultPosition(bias: PatternBias): MarkerPosition {
  if (bias === 'bullish') return 'belowBar';
  if (bias === 'bearish') return 'aboveBar';
  return 'inBar';
}

function defaultShape(bias: PatternBias): MarkerShape {
  if (bias === 'bullish') return 'arrowUp';
  if (bias === 'bearish') return 'arrowDown';
  return 'circle';
}

function colorFor(bias: PatternBias, palette: PatternPalette): string {
  return palette[bias];
}

/** Resolve an event's anchor time against the candle series. */
function resolveTime(
  event: PatternEvent,
  candles: Candle[],
): UTCTimestamp | null {
  if (candles.length === 0) return null;

  if (typeof event.index === 'number') {
    const idx = Math.max(0, Math.min(candles.length - 1, event.index));
    return candles[idx].time;
  }

  if (typeof event.time === 'number') {
    // Snap to the nearest candle time so the marker lands on a real bar.
    let best = candles[0];
    let bestDiff = Math.abs(candles[0].time - event.time);
    for (let i = 1; i < candles.length; i += 1) {
      const diff = Math.abs(candles[i].time - event.time);
      if (diff < bestDiff) {
        bestDiff = diff;
        best = candles[i];
      }
    }
    return best.time;
  }

  // No anchor → pin to the latest bar.
  return candles[candles.length - 1].time;
}

/** Build chart markers from a list of pattern events. */
export function markersFromPatterns(
  events: PatternEvent[],
  candles: Candle[],
  palette: Partial<PatternPalette> = {},
): ChartMarker[] {
  const pal: PatternPalette = { ...DEFAULT_PALETTE, ...palette };
  const markers: ChartMarker[] = [];

  for (const event of events) {
    const time = resolveTime(event, candles);
    if (time === null) continue;
    markers.push({
      id: event.id,
      time,
      position: event.position ?? defaultPosition(event.bias),
      shape: event.shape ?? defaultShape(event.bias),
      color: colorFor(event.bias, pal),
      text: event.label,
    });
  }

  // Lightweight Charts requires markers in ascending time order.
  markers.sort((a, b) => a.time - b.time);
  return markers;
}

/**
 * Normalize a raw scan `signals` block into `PatternEvent[]`. Skips anything
 * that isn't an actionable detected event ("none"/empty are dropped).
 */
export function eventsFromScanSignals(
  signals: ScanSignalsBlock,
): PatternEvent[] {
  const events: PatternEvent[] = [];

  const div = signals.divergence;
  if (div && div.type && div.type !== 'none') {
    const bias: PatternBias = div.type === 'bullish' ? 'bullish' : 'bearish';
    events.push({
      id: 'pattern-divergence',
      label: `${div.type === 'bullish' ? 'Bullish' : 'Bearish'} Divergence`,
      bias,
      time: div.time == null ? undefined : (div.time as UTCTimestamp),
      index: div.index == null ? undefined : div.index,
    });
  }

  const patterns = signals.patterns ?? [];
  patterns.forEach((p, i) => {
    if (!p.name) return;
    events.push({
      id: `pattern-${i}-${p.name}`,
      label: p.name,
      bias: p.bias ?? 'neutral',
      time: p.time == null ? undefined : (p.time as UTCTimestamp),
      index: p.index == null ? undefined : p.index,
    });
  });

  const gap = signals.gap;
  if (gap && typeof gap.pct === 'number' && Math.abs(gap.pct) >= 0.01) {
    const bias: PatternBias = gap.pct > 0 ? 'bullish' : 'bearish';
    events.push({
      id: 'pattern-gap',
      label: `Gap ${gap.pct > 0 ? 'Up' : 'Down'} ${(gap.pct * 100).toFixed(1)}%`,
      bias,
      time: gap.time == null ? undefined : (gap.time as UTCTimestamp),
    });
  }

  return events;
}

export interface PatternAnnotationsProps {
  candles: Candle[];
  chartRef: React.RefObject<ChartHandle | null>;
  /** Pre-normalized events, OR provide `scanSignals` to derive them. */
  events?: PatternEvent[];
  scanSignals?: ScanSignalsBlock | null;
  palette?: Partial<PatternPalette>;
  visible?: boolean;
  onMarkers?: (markers: ChartMarker[]) => void;
}

/**
 * Declarative pattern annotations. Resolves events from `events` or
 * `scanSignals`, builds markers, and pushes them onto the chart handle.
 */
export function PatternAnnotations(props: PatternAnnotationsProps): null {
  const {
    candles,
    chartRef,
    events,
    scanSignals,
    palette,
    visible = true,
    onMarkers,
  } = props;

  useEffect(() => {
    const handle = chartRef.current;
    if (!handle) return;
    let markers: ChartMarker[] = [];
    if (visible) {
      const resolved =
        events ?? (scanSignals ? eventsFromScanSignals(scanSignals) : []);
      markers = markersFromPatterns(resolved, candles, palette);
    }
    handle.setMarkers(markers);
    onMarkers?.(markers);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candles, events, scanSignals, visible]);

  return null;
}

export default PatternAnnotations;
