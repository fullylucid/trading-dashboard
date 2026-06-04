/**
 * SectorRRG — Relative Rotation Graph + decode legend.
 *
 * Plots each sector ETF by RS-Ratio (x) vs RS-Momentum (y). Both axes are
 * centered at 100 (the RRG convention), splitting the plane into the four
 * rotation quadrants:
 *
 *     Improving (top-left)   |   Leading  (top-right)
 *     -----------------------+------------------------
 *     Lagging  (bottom-left) |  Weakening (bottom-right)
 *
 * The scatter is pure inline SVG (no chart lib) and scales fluidly to its
 * container via a viewBox — it never overflows a narrow phone panel. Because
 * the bare ETF tickers (XLF, XLK…) are meaningless on a touch screen (the full
 * name used to live only in a hover <title>), every sector is decoded in a
 * legend beneath the plot: swatch · ETF · full sector name · quadrant · RS
 * values. Tapping a dot or a legend row highlights the pair, so the chart is
 * usable without hover. A short caption explains what each quadrant means.
 *
 * Consumes `result.market.sectors` (a map of ETF symbol -> {@link RsRatioRow}).
 */

import React, { useMemo, useState } from 'react';
import type { RsRatioRow, RrgQuadrant } from './types';
import { QUADRANT_COLORS } from './types';

export interface SectorRRGProps {
  /** `result.market.sectors` — ETF symbol -> RRG row. */
  sectors: Record<string, RsRatioRow> | null | undefined;
  /** SVG coordinate-space size in px; the plot renders fluid up to this width. */
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

// Reading order for the legend (strongest → weakest rotation phase) and the
// one-line plain-English meaning shown in the caption.
const QUADRANT_ORDER: Record<RrgQuadrant, number> = {
  Leading: 0,
  Improving: 1,
  Weakening: 2,
  Lagging: 3,
  Neutral: 4,
};
const QUADRANT_MEANING: Record<RrgQuadrant, string> = {
  Leading: 'strong & still strengthening',
  Improving: 'weak but gaining — early rotation in',
  Weakening: 'strong but losing momentum — rotation out starting',
  Lagging: 'weak & still weakening',
  Neutral: 'no clear rotation',
};

const PADDING = 36;
const DOT_R = 6;

const SectorRRG: React.FC<SectorRRGProps> = ({ sectors, size = 360, className }) => {
  const [selected, setSelected] = useState<string | null>(null);

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

  // Legend ordered by rotation phase, then by relative strength within a phase.
  const legend = useMemo<PlottedPoint[]>(
    () =>
      [...points].sort(
        (a, b) => QUADRANT_ORDER[a.quadrant] - QUADRANT_ORDER[b.quadrant] || b.ratio - a.ratio,
      ),
    [points],
  );

  // Which quadrants are actually present — only caption those.
  const presentQuadrants = useMemo<RrgQuadrant[]>(() => {
    const seen = new Set<RrgQuadrant>(points.map((p) => p.quadrant));
    return (Object.keys(QUADRANT_ORDER) as RrgQuadrant[])
      .filter((q) => seen.has(q))
      .sort((a, b) => QUADRANT_ORDER[a] - QUADRANT_ORDER[b]);
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

  const toggle = (etf: string): void => setSelected((cur) => (cur === etf ? null : etf));

  return (
    <div className={className}>
      <svg
        viewBox={`0 0 ${size} ${size}`}
        width="100%"
        preserveAspectRatio="xMidYMid meet"
        style={{ maxWidth: size, height: 'auto', display: 'block', margin: '0 auto', touchAction: 'manipulation' }}
        role="img"
        aria-label="Sector relative rotation graph"
      >
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

        {/* Sector dots + tickers. Selected dot gets a ring + always-on label. */}
        {points.map((p) => {
          const px = scaleX(p.ratio);
          const py = scaleY(p.momentum);
          const color = QUADRANT_COLORS[p.quadrant];
          const isSel = selected === p.etf;
          const dimmed = selected != null && !isSel;
          return (
            <g
              key={p.etf}
              onClick={() => toggle(p.etf)}
              style={{ cursor: 'pointer' }}
              opacity={dimmed ? 0.35 : 1}
            >
              {isSel && <circle cx={px} cy={py} r={DOT_R + 4} fill="none" stroke={color} strokeWidth={1.5} opacity={0.7} />}
              <circle cx={px} cy={py} r={isSel ? DOT_R + 1 : DOT_R} fill={color} stroke="#0f172a" strokeWidth={1.5}>
                <title>{`${p.label} (${p.etf}) — ${p.quadrant}\nRS-Ratio ${p.ratio.toFixed(1)} · RS-Mom ${p.momentum.toFixed(1)}`}</title>
              </circle>
              <text x={px + DOT_R + 2} y={py + 3} fill={isSel ? color : '#e2e8f0'} fontSize={isSel ? 11 : 9} fontWeight={isSel ? 700 : 600}>
                {isSel ? `${p.etf} · ${p.label}` : p.etf}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Decode legend — the names the plot can't show without hover. */}
      <div
        style={{
          marginTop: 14,
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))',
          gap: '6px 14px',
        }}
      >
        {legend.map((p) => {
          const color = QUADRANT_COLORS[p.quadrant];
          const isSel = selected === p.etf;
          return (
            <button
              key={p.etf}
              type="button"
              onClick={() => toggle(p.etf)}
              style={{
                display: 'flex',
                alignItems: 'baseline',
                gap: 8,
                width: '100%',
                textAlign: 'left',
                background: isSel ? 'rgba(148,163,184,0.12)' : 'transparent',
                border: '1px solid transparent',
                borderLeft: `3px solid ${color}`,
                borderRadius: 4,
                padding: '4px 8px',
                cursor: 'pointer',
                fontFamily: 'inherit',
              }}
            >
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700, color, minWidth: 38 }}>
                {p.etf}
              </span>
              <span style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                <span style={{ fontSize: 12, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {p.label}
                </span>
                <span style={{ fontSize: 10.5, color: 'var(--text-secondary)', fontVariantNumeric: 'tabular-nums' }}>
                  {p.quadrant} · R {p.ratio.toFixed(1)} · M {p.momentum.toFixed(1)}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      {/* What the quadrants mean for a trader. */}
      <div style={{ marginTop: 12, display: 'flex', flexWrap: 'wrap', gap: '4px 14px' }}>
        {presentQuadrants.map((q) => (
          <span key={q} style={{ fontSize: 10.5, color: 'var(--text-secondary)', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: QUADRANT_COLORS[q], display: 'inline-block' }} />
            <strong style={{ color: QUADRANT_COLORS[q], fontWeight: 600 }}>{q}</strong> {QUADRANT_MEANING[q]}
          </span>
        ))}
      </div>
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
