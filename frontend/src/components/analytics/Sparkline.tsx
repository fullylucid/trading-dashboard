/**
 * Sparkline — a tiny inline SVG line chart for a price/return series.
 *
 * Zero-dependency: pure SVG path math. Renders nothing (a dim em-dash) when
 * there are fewer than two finite points. Auto-scales to the data's min/max
 * with a small vertical pad so flat-ish series don't clip.
 *
 * Color follows direction by default (last >= first => green, else red); pass
 * an explicit `color` to override.
 */

import React from 'react';

export interface SparklineProps {
  data: ReadonlyArray<number>;
  width?: number;
  height?: number;
  /** Stroke color; defaults to direction-based green/red. */
  color?: string;
  strokeWidth?: number;
  /** Fill a faint area under the line. */
  fill?: boolean;
  className?: string;
  ariaLabel?: string;
}

const GREEN = '#00ff41';
const RED = '#ff003c';

/** Keep only finite numbers (drops NaN / Infinity / nullish coerced values). */
function finiteSeries(data: ReadonlyArray<number>): number[] {
  const out: number[] = [];
  for (const v of data) {
    if (typeof v === 'number' && Number.isFinite(v)) out.push(v);
  }
  return out;
}

const Sparkline: React.FC<SparklineProps> = ({
  data,
  width = 80,
  height = 22,
  color,
  strokeWidth = 1.5,
  fill = false,
  className,
  ariaLabel,
}) => {
  const series = finiteSeries(data);

  if (series.length < 2) {
    return (
      <span
        className={className}
        style={{ color: 'var(--text-secondary)', fontSize: 11, opacity: 0.6 }}
        aria-label={ariaLabel ?? 'no data'}
      >
        —
      </span>
    );
  }

  const min = Math.min(...series);
  const max = Math.max(...series);
  const span = max - min;
  const pad = span === 0 ? 1 : span * 0.08;
  const lo = min - pad;
  const hi = max + pad;
  const range = hi - lo || 1;

  const n = series.length;
  const stepX = n > 1 ? width / (n - 1) : 0;

  const points = series.map((v, i) => {
    const x = i * stepX;
    // Invert Y: SVG origin is top-left.
    const y = height - ((v - lo) / range) * height;
    return { x, y };
  });

  const linePath = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(2)},${p.y.toFixed(2)}`)
    .join(' ');

  const stroke = color ?? (series[n - 1] >= series[0] ? GREEN : RED);

  const areaPath = fill
    ? `${linePath} L${width.toFixed(2)},${height.toFixed(2)} L0,${height.toFixed(2)} Z`
    : null;

  return (
    <svg
      className={className}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={ariaLabel ?? 'sparkline'}
      style={{ display: 'inline-block', verticalAlign: 'middle' }}
    >
      {areaPath && <path d={areaPath} fill={stroke} opacity={0.12} stroke="none" />}
      <path
        d={linePath}
        fill="none"
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
};

export default Sparkline;
