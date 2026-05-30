/**
 * SectorDonut — sector exposure donut.
 *
 * Aggregates the portfolio's tagged holdings (`result.companies.tagged`) into
 * per-sector exposure and renders a donut. Each slice is colored by the
 * sector's rotation status (tailwind = green, risk = red, neutral = slate) so a
 * glance shows whether your weight sits in sectors rotating IN or OUT.
 *
 * Exposure is by **count** of holdings per sector unless the caller passes a
 * `weights` map (symbol -> weight, e.g. market value), in which case slices are
 * value-weighted. Pure inline SVG.
 */

import React, { useMemo } from 'react';
import type { TaggedHolding, RotationStatus } from './types';

export interface SectorDonutProps {
  /** `result.companies.tagged` — holdings tagged with their sector rotation. */
  tagged: TaggedHolding[] | null | undefined;
  /** Optional symbol -> weight (e.g. market value). Defaults to equal-weight. */
  weights?: Record<string, number>;
  /** Outer diameter in px. Defaults to 240. */
  size?: number;
  className?: string;
}

interface Slice {
  sector: string;
  value: number;
  pct: number;
  status: RotationStatus | 'unknown';
  color: string;
}

const STATUS_COLOR: Record<RotationStatus | 'unknown', string> = {
  'rotating-IN': '#22c55e',
  'rotating-OUT': '#ef4444',
  neutral: '#94a3b8',
  unknown: '#475569',
};

const STATUS_LABEL: Record<RotationStatus | 'unknown', string> = {
  'rotating-IN': 'rotating in',
  'rotating-OUT': 'rotating out',
  neutral: 'neutral',
  unknown: 'no read',
};

/** Polar -> cartesian on a unit circle, angle measured from 12 o'clock CW. */
function polar(cx: number, cy: number, r: number, angleDeg: number): [number, number] {
  const a = ((angleDeg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}

/** SVG arc path for a donut segment between two angles. */
function arcPath(
  cx: number,
  cy: number,
  rOuter: number,
  rInner: number,
  startAngle: number,
  endAngle: number,
): string {
  const [x1, y1] = polar(cx, cy, rOuter, endAngle);
  const [x2, y2] = polar(cx, cy, rOuter, startAngle);
  const [x3, y3] = polar(cx, cy, rInner, startAngle);
  const [x4, y4] = polar(cx, cy, rInner, endAngle);
  const largeArc = endAngle - startAngle > 180 ? 1 : 0;
  return [
    `M ${x1} ${y1}`,
    `A ${rOuter} ${rOuter} 0 ${largeArc} 0 ${x2} ${y2}`,
    `L ${x3} ${y3}`,
    `A ${rInner} ${rInner} 0 ${largeArc} 1 ${x4} ${y4}`,
    'Z',
  ].join(' ');
}

const SectorDonut: React.FC<SectorDonutProps> = ({ tagged, weights, size = 240, className }) => {
  const slices = useMemo<Slice[]>(() => {
    if (!tagged || tagged.length === 0) return [];
    const bySector = new Map<string, { value: number; status: RotationStatus | 'unknown' }>();
    for (const h of tagged) {
      const sector = h.sector ?? 'Unknown';
      const w = weights?.[h.symbol];
      const value = w != null && Number.isFinite(w) && w > 0 ? w : 1;
      const status = (h.status ?? 'unknown') as RotationStatus | 'unknown';
      const cur = bySector.get(sector);
      if (cur) {
        cur.value += value;
        // Keep the most decisive status seen for the sector.
        if (cur.status === 'unknown' || cur.status === 'neutral') cur.status = status;
      } else {
        bySector.set(sector, { value, status });
      }
    }
    const total = Array.from(bySector.values()).reduce((s, v) => s + v.value, 0);
    if (total <= 0) return [];
    return Array.from(bySector.entries())
      .map(([sector, v]) => ({
        sector,
        value: v.value,
        pct: (v.value / total) * 100,
        status: v.status,
        color: STATUS_COLOR[v.status],
      }))
      .sort((a, b) => b.value - a.value);
  }, [tagged, weights]);

  if (slices.length === 0) {
    return (
      <div className={className} style={emptyStyle}>
        No sector exposure to chart.
      </div>
    );
  }

  const cx = size / 2;
  const cy = size / 2;
  const rOuter = size / 2 - 4;
  const rInner = rOuter * 0.58;

  let cursor = 0;
  const paths = slices.map((s) => {
    const start = cursor;
    const sweep = (s.pct / 100) * 360;
    const end = cursor + sweep;
    cursor = end;
    // Full-circle single slice: draw a ring instead of a degenerate arc.
    const path =
      sweep >= 359.999
        ? `M ${cx} ${cy - rOuter} A ${rOuter} ${rOuter} 0 1 0 ${cx - 0.01} ${cy - rOuter} Z ` +
          `M ${cx} ${cy - rInner} A ${rInner} ${rInner} 0 1 1 ${cx - 0.01} ${cy - rInner} Z`
        : arcPath(cx, cy, rOuter, rInner, start, end);
    return { slice: s, path };
  });

  return (
    <div className={className} style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
      <svg width={size} height={size} role="img" aria-label="Sector exposure donut">
        {paths.map(({ slice, path }) => (
          <path key={slice.sector} d={path} fill={slice.color} fillRule="evenodd" stroke="#0f172a" strokeWidth={1}>
            <title>{`${slice.sector} — ${slice.pct.toFixed(1)}% (${STATUS_LABEL[slice.status]})`}</title>
          </path>
        ))}
        <text x={cx} y={cy - 4} fill="#e2e8f0" fontSize={13} textAnchor="middle" fontWeight={700}>
          {slices.length}
        </text>
        <text x={cx} y={cy + 12} fill="#64748b" fontSize={10} textAnchor="middle">
          sectors
        </text>
      </svg>

      <ul style={legendStyle}>
        {slices.map((s) => (
          <li key={s.sector} style={legendItemStyle}>
            <span style={{ ...swatchStyle, background: s.color }} />
            <span style={{ color: '#e2e8f0', flex: 1 }}>{s.sector}</span>
            <span style={{ color: '#94a3b8', fontVariantNumeric: 'tabular-nums' }}>{s.pct.toFixed(1)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
};

const emptyStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  minHeight: 120,
  color: '#64748b',
  fontSize: 13,
  border: '1px dashed #334155',
  borderRadius: 8,
  padding: 16,
};

const legendStyle: React.CSSProperties = {
  listStyle: 'none',
  margin: 0,
  padding: 0,
  fontSize: 12,
  minWidth: 160,
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
};

const legendItemStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
};

const swatchStyle: React.CSSProperties = {
  width: 10,
  height: 10,
  borderRadius: 2,
  flex: '0 0 auto',
};

export default SectorDonut;
