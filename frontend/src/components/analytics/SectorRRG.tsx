/**
 * SectorRRG — Relative Rotation Graph.
 *
 * Plots each sector ETF by RS-Ratio (x) vs RS-Momentum (y). Both axes are
 * centered at 100 (the RRG convention), splitting the plane into the four
 * rotation quadrants:
 *
 *     Improving (top-left)   |   Leading  (top-right)
 *     -----------------------+------------------------
 *     Lagging  (bottom-left) |  Weakening (bottom-right)
 *
 * Pure inline SVG — no chart lib. Consumes `result.market.sectors` (a map of
 * ETF symbol -> {@link RsRatioRow}).
 */

import React, { useMemo } from 'react';
import type { RsRatioRow, RrgQuadrant } from './types';
import { QUADRANT_COLORS } from './types';

export interface SectorRRGProps {
  /** `result.market.sectors` — ETF symbol -> RRG row. */
  sectors: Record<string, RsRatioRow> | null | undefined;
  /** Square plot size in px. Defaults to 360. */
  size?: number;
  className?: string;
}

interface PlottedPoint {
  etf: string;
  label: string;
  ratio: number;
  momentum: number;
  quadrant: RrgQuadrant;
}

/** Quadrant a point falls in from its (ratio, momentum) relative to 100. */
function quadrantFor(ratio: number, momentum: number): RrgQuadrant {
  if (ratio >= 100 && momentum >= 100) return 'Leading';
  if (ratio < 100 && momentum >= 100) return 'Improving';
  if (ratio < 100 && momentum < 100) return 'Lagging';
  return 'Weakening';
}

const PADDING = 36;
const DOT_R = 6;

const SectorRRG: React.FC<SectorRRGProps> = ({ sectors, size = 360, className }) => {
  const points = useMemo<PlottedPoint[]>(() => {
    if (!sectors) return [];
    const out: PlottedPoint[] = [];
    for (const [etf, row] of Object.entries(sectors)) {
      const ratio = row?.rs_ratio;
      const momentum = row?.rs_momentum;
      if (ratio == null || momentum == null || !Number.isFinite(ratio) || !Number.isFinite(momentum)) {
        continue;
      }
      out.push({
        etf,
        label: row.sector ?? etf,
        ratio,
        momentum,
        quadrant: row.quadrant ?? quadrantFor(ratio, momentum),
      });
    }
    return out;
  }, [sectors]);

  // Symmetric domain around 100 so the center cross is always dead-center.
  const span = useMemo(() => {
    let max = 2; // floor so a tight cluster still has breathing room
    for (const p of points) {
      max = Math.max(max, Math.abs(p.ratio - 100), Math.abs(p.momentum - 100));
    }
    return max * 1.15;
  }, [points]);

  const inner = size - PADDING * 2;
  const scaleX = (ratio: number): number => PADDING + ((ratio - 100 + span) / (2 * span)) * inner;
  // SVG y grows downward; momentum grows upward -> invert.
  const scaleY = (momentum: number): number =>
    PADDING + inner - ((momentum - 100 + span) / (2 * span)) * inner;

  const cx = PADDING + inner / 2;
  const cy = PADDING + inner / 2;

  if (points.length === 0) {
    return (
      <div className={className} style={emptyStyle}>
        No RRG data yet — run a sector-rotation sweep.
      </div>
    );
  }

  return (
    <div className={className}>
      <svg width={size} height={size} role="img" aria-label="Sector relative rotation graph">
        {/* Quadrant background tints (very faint). */}
        <rect x={cx} y={PADDING} width={inner / 2} height={inner / 2} fill={QUADRANT_COLORS.Leading} opacity={0.06} />
        <rect x={PADDING} y={PADDING} width={inner / 2} height={inner / 2} fill={QUADRANT_COLORS.Improving} opacity={0.06} />
        <rect x={PADDING} y={cy} width={inner / 2} height={inner / 2} fill={QUADRANT_COLORS.Lagging} opacity={0.06} />
        <rect x={cx} y={cy} width={inner / 2} height={inner / 2} fill={QUADRANT_COLORS.Weakening} opacity={0.06} />

        {/* Center cross (RS-Ratio = RS-Momentum = 100). */}
        <line x1={cx} y1={PADDING} x2={cx} y2={PADDING + inner} stroke="#475569" strokeWidth={1} />
        <line x1={PADDING} y1={cy} x2={PADDING + inner} y2={cy} stroke="#475569" strokeWidth={1} />

        {/* Quadrant labels. */}
        <text x={PADDING + inner - 6} y={PADDING + 14} fill={QUADRANT_COLORS.Leading} fontSize={11} textAnchor="end" fontWeight={600}>
          Leading
        </text>
        <text x={PADDING + 6} y={PADDING + 14} fill={QUADRANT_COLORS.Improving} fontSize={11} fontWeight={600}>
          Improving
        </text>
        <text x={PADDING + 6} y={PADDING + inner - 6} fill={QUADRANT_COLORS.Lagging} fontSize={11} fontWeight={600}>
          Lagging
        </text>
        <text x={PADDING + inner - 6} y={PADDING + inner - 6} fill={QUADRANT_COLORS.Weakening} fontSize={11} textAnchor="end" fontWeight={600}>
          Weakening
        </text>

        {/* Axis captions. */}
        <text x={cx} y={size - 8} fill="#64748b" fontSize={10} textAnchor="middle">
          RS-Ratio →
        </text>
        <text
          x={12}
          y={cy}
          fill="#64748b"
          fontSize={10}
          textAnchor="middle"
          transform={`rotate(-90 12 ${cy})`}
        >
          RS-Momentum →
        </text>

        {/* Sector dots + tickers. */}
        {points.map((p) => {
          const px = scaleX(p.ratio);
          const py = scaleY(p.momentum);
          const color = QUADRANT_COLORS[p.quadrant];
          return (
            <g key={p.etf}>
              <circle cx={px} cy={py} r={DOT_R} fill={color} stroke="#0f172a" strokeWidth={1.5}>
                <title>{`${p.label} (${p.etf}) — ${p.quadrant}\nRS-Ratio ${p.ratio.toFixed(1)} · RS-Mom ${p.momentum.toFixed(1)}`}</title>
              </circle>
              <text x={px + DOT_R + 2} y={py + 3} fill="#e2e8f0" fontSize={10} fontWeight={600}>
                {p.etf}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
};

const emptyStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  minHeight: 160,
  color: '#64748b',
  fontSize: 13,
  border: '1px dashed #334155',
  borderRadius: 8,
  padding: 16,
};

export default SectorRRG;
