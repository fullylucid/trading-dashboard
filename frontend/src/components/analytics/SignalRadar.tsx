/**
 * SignalRadar — per-ticker signal-confluence radar.
 *
 * Takes one ticker's {@link SignalsBlock} (the `analytics.signals` sub-block in
 * the scan output) and projects its heterogeneous indicators onto a single
 * 0..100 "bullishness" scale per axis, then draws a radar polygon. A large,
 * balanced polygon = broad signal confluence; a spiky/small one = mixed or weak.
 *
 * Axes (each normalized so 50 = neutral, 100 = max bullish):
 *   Momentum (RSI), Trend (MA structure), MACD, Rel.Strength, ROC, Volume (RVOL).
 *
 * Pure inline SVG. Every axis degrades gracefully to the neutral midpoint when
 * its underlying field is null.
 */

import React, { useMemo } from 'react';
import type { SignalsBlock, MaStructure } from './types';

export interface SignalRadarProps {
  symbol: string;
  signals: SignalsBlock | null | undefined;
  /** Square size in px. Defaults to 260. */
  size?: number;
  className?: string;
}

interface Axis {
  key: string;
  label: string;
  /** 0..100, 50 = neutral. null when uncomputable (drawn at the center ring). */
  value: number | null;
}

const NEUTRAL = 50;

function clamp01to100(x: number): number {
  return Math.max(0, Math.min(100, x));
}

/** RSI: 0..100 already a bullishness axis (oversold low, overbought high). */
function rsiAxis(rsi: number | null): number | null {
  if (rsi == null || !Number.isFinite(rsi)) return null;
  return clamp01to100(rsi);
}

/** MA structure -> a 0..100 trend score from the boolean stack. */
function trendAxis(ms: MaStructure | null): number | null {
  if (!ms) return null;
  let score = NEUTRAL;
  if (ms.above_50 != null) score += ms.above_50 ? 12 : -12;
  if (ms.above_200 != null) score += ms.above_200 ? 18 : -18;
  if (ms.stacked_bullish) score += 12;
  if (ms.golden_cross) score += 8;
  if (ms.death_cross) score -= 8;
  return clamp01to100(score);
}

/** MACD histogram sign/magnitude -> 0..100 (saturating at ±2 units). */
function macdAxis(macd: SignalsBlock['macd']): number | null {
  if (!macd || macd.hist == null || !Number.isFinite(macd.hist)) return null;
  const sat = Math.max(-2, Math.min(2, macd.hist));
  return clamp01to100(NEUTRAL + (sat / 2) * 50);
}

/** Relative strength vs SPY (% outperformance) -> 0..100, saturating at ±20%. */
function rsAxis(rs: number | null): number | null {
  if (rs == null || !Number.isFinite(rs)) return null;
  const sat = Math.max(-20, Math.min(20, rs));
  return clamp01to100(NEUTRAL + (sat / 20) * 50);
}

/** ROC (%) -> 0..100, saturating at ±15%. */
function rocAxis(roc: number | null): number | null {
  if (roc == null || !Number.isFinite(roc)) return null;
  const sat = Math.max(-15, Math.min(15, roc));
  return clamp01to100(NEUTRAL + (sat / 15) * 50);
}

/** RVOL: 1.0 = neutral, 3.0+ = max (volume only adds conviction, never bearish). */
function volAxis(rvol: number | null): number | null {
  if (rvol == null || !Number.isFinite(rvol)) return null;
  const sat = Math.max(0.5, Math.min(3, rvol));
  return clamp01to100(((sat - 0.5) / 2.5) * 100);
}

function buildAxes(s: SignalsBlock | null | undefined): Axis[] {
  return [
    { key: 'rsi', label: 'RSI', value: rsiAxis(s?.rsi ?? null) },
    { key: 'trend', label: 'Trend', value: trendAxis(s?.ma_structure ?? null) },
    { key: 'macd', label: 'MACD', value: macdAxis(s?.macd ?? null) },
    { key: 'rs', label: 'Rel.Str', value: rsAxis(s?.relative_strength ?? null) },
    { key: 'roc', label: 'ROC', value: rocAxis(s?.roc ?? null) },
    { key: 'vol', label: 'RVOL', value: volAxis(s?.rvol ?? null) },
  ];
}

const SignalRadar: React.FC<SignalRadarProps> = ({ symbol, signals, size = 260, className }) => {
  const axes = useMemo(() => buildAxes(signals), [signals]);

  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 34;
  const n = axes.length;

  // Confluence = mean of the computed (non-null) axes. Drives the fill color.
  const confluence = useMemo(() => {
    const vals = axes.map((a) => a.value).filter((v): v is number => v != null);
    if (vals.length === 0) return null;
    return vals.reduce((a, b) => a + b, 0) / vals.length;
  }, [axes]);

  const fill =
    confluence == null
      ? '#475569'
      : confluence >= 62
        ? '#22c55e'
        : confluence <= 38
          ? '#ef4444'
          : '#f59e0b';

  // Vertex for axis i at a 0..100 value.
  const point = (i: number, value: number): [number, number] => {
    const angle = (Math.PI * 2 * i) / n - Math.PI / 2;
    const rr = (value / 100) * r;
    return [cx + rr * Math.cos(angle), cy + rr * Math.sin(angle)];
  };

  const polygon = axes
    .map((a, i) => point(i, a.value ?? NEUTRAL))
    .map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
    .join(' ');

  const rings = [25, 50, 75, 100];

  return (
    <div className={className}>
      <svg width={size} height={size} role="img" aria-label={`Signal confluence radar for ${symbol}`}>
        {/* Concentric reference rings. */}
        {rings.map((pct) => (
          <circle key={pct} cx={cx} cy={cy} r={(pct / 100) * r} fill="none" stroke="#1e293b" strokeWidth={1} />
        ))}
        {/* 50% neutral ring highlighted. */}
        <circle cx={cx} cy={cy} r={(NEUTRAL / 100) * r} fill="none" stroke="#334155" strokeWidth={1} strokeDasharray="3 3" />

        {/* Axis spokes + labels. */}
        {axes.map((a, i) => {
          const [ex, ey] = point(i, 100);
          const [lx, ly] = point(i, 118);
          return (
            <g key={a.key}>
              <line x1={cx} y1={cy} x2={ex} y2={ey} stroke="#1e293b" strokeWidth={1} />
              <text x={lx} y={ly} fill="#94a3b8" fontSize={10} textAnchor="middle" dominantBaseline="middle">
                {a.label}
              </text>
            </g>
          );
        })}

        {/* Confluence polygon. */}
        <polygon points={polygon} fill={fill} fillOpacity={0.22} stroke={fill} strokeWidth={2} />
        {axes.map((a, i) => {
          if (a.value == null) return null;
          const [px, py] = point(i, a.value);
          return (
            <circle key={a.key} cx={px} cy={py} r={3} fill={fill}>
              <title>{`${a.label}: ${a.value.toFixed(0)}/100`}</title>
            </circle>
          );
        })}

        {/* Center score badge. */}
        <text x={cx} y={cy + 2} fill="#e2e8f0" fontSize={14} textAnchor="middle" fontWeight={700}>
          {confluence == null ? '—' : confluence.toFixed(0)}
        </text>
      </svg>
    </div>
  );
};

export default SignalRadar;
