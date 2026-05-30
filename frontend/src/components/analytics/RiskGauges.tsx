/**
 * RiskGauges — radial gauges for portfolio-level risk metrics sourced from the
 * scan payload's `portfolio_risk` block.
 *
 * Gauges shown (each omitted gracefully if its source field is absent):
 *   - VaR 95% (1d)         : portfolio_risk.var_95.historical  (fraction loss)
 *   - Beta to SPY          : portfolio_risk.beta_to_spy
 *   - Effective N          : portfolio_risk.effective_number   (diversification)
 *   - Annualized Vol       : portfolio_risk.annualized_vol
 *
 * Pure inline SVG arcs (270° sweep). No external chart deps. Each gauge maps
 * its value onto a [0..1] fraction against a sensible domain, then colors the
 * arc green->amber->red by how "hot" the reading is.
 */

import React from 'react';
import type { PortfolioRisk } from '../../types/scanAnalytics';

export interface RiskGaugesProps {
  portfolioRisk: PortfolioRisk | null | undefined;
  className?: string;
}

const GREEN = '#00ff41';
const AMBER = '#ffb000';
const RED = '#ff003c';

interface GaugeSpec {
  key: string;
  label: string;
  /** Raw value or null when unavailable. */
  value: number | null;
  /** Pre-formatted display string. */
  display: string;
  /** 0..1 fill fraction of the arc. */
  fraction: number;
  /** 0..1 "severity" used to pick arc color (1 = most alarming). */
  severity: number;
  /** Sub-caption under the value. */
  note: string;
}

function num(v: number | null | undefined): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

function clamp01(x: number): number {
  if (x < 0) return 0;
  if (x > 1) return 1;
  return x;
}

function severityColor(severity: number): string {
  const s = clamp01(severity);
  if (s < 0.5) return GREEN;
  if (s < 0.8) return AMBER;
  return RED;
}

/** Build the arc path for a 270° gauge (start bottom-left, sweep clockwise). */
function arcPath(cx: number, cy: number, r: number, fraction: number): string {
  const startAngle = 135; // degrees
  const sweep = 270 * clamp01(fraction);
  const endAngle = startAngle + sweep;
  const toXY = (angleDeg: number): [number, number] => {
    const a = (angleDeg * Math.PI) / 180;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  };
  const [x0, y0] = toXY(startAngle);
  const [x1, y1] = toXY(endAngle);
  const largeArc = sweep > 180 ? 1 : 0;
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${largeArc} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

function buildGauges(pr: PortfolioRisk): GaugeSpec[] {
  const gauges: GaugeSpec[] = [];

  // VaR 95% — fraction-of-portfolio loss; domain 0..10% maps to full arc.
  const varHist = num(pr.var_95?.historical ?? null);
  if (varHist !== null) {
    const pct = varHist * 100;
    const frac = clamp01(pct / 10);
    gauges.push({
      key: 'var',
      label: 'VaR 95% / 1d',
      value: varHist,
      display: `${pct.toFixed(2)}%`,
      fraction: frac,
      severity: frac,
      note: 'max 1-day loss',
    });
  }

  // Beta to SPY — domain 0..2 maps to full arc; severity from |beta-1|.
  const beta = num(pr.beta_to_spy ?? null);
  if (beta !== null) {
    gauges.push({
      key: 'beta',
      label: 'Beta to SPY',
      value: beta,
      display: beta.toFixed(2),
      fraction: clamp01(beta / 2),
      severity: clamp01(Math.abs(beta - 1) / 1),
      note: beta >= 1 ? 'more volatile than mkt' : 'less volatile than mkt',
    });
  }

  // Effective number of positions — higher = better diversified (lower severity).
  const eff = num(pr.effective_number ?? null);
  if (eff !== null) {
    const holdingsCount = pr.holdings_used?.length ?? Object.keys(pr.weights ?? {}).length;
    const denom = holdingsCount > 0 ? holdingsCount : Math.max(eff, 1);
    const ratio = clamp01(eff / denom); // 1 = perfectly equal-weight
    gauges.push({
      key: 'eff',
      label: 'Effective N',
      value: eff,
      display: eff.toFixed(2),
      fraction: ratio,
      severity: clamp01(1 - ratio), // concentrated => high severity
      note: 'diversification',
    });
  }

  // Annualized vol — domain 0..60% maps to full arc.
  const vol = num(pr.annualized_vol ?? null);
  if (vol !== null) {
    const pct = vol * 100;
    const frac = clamp01(pct / 60);
    gauges.push({
      key: 'vol',
      label: 'Annualized Vol',
      value: vol,
      display: `${pct.toFixed(1)}%`,
      fraction: frac,
      severity: frac,
      note: 'portfolio sigma',
    });
  }

  return gauges;
}

const SIZE = 96;
const R = 36;
const CX = SIZE / 2;
const CY = SIZE / 2;

const Gauge: React.FC<{ spec: GaugeSpec }> = ({ spec }) => {
  const color = severityColor(spec.severity);
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 2,
        minWidth: SIZE,
      }}
    >
      <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label={`${spec.label}: ${spec.display}`}>
        {/* track */}
        <path
          d={arcPath(CX, CY, R, 1)}
          fill="none"
          stroke="var(--border)"
          strokeWidth={7}
          strokeLinecap="round"
        />
        {/* value arc */}
        <path
          d={arcPath(CX, CY, R, spec.fraction)}
          fill="none"
          stroke={color}
          strokeWidth={7}
          strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 4px ${color}66)` }}
        />
        <text
          x={CX}
          y={CY - 2}
          textAnchor="middle"
          fontSize={15}
          fontFamily="var(--font-mono)"
          fill={color}
          fontWeight={700}
        >
          {spec.display}
        </text>
        <text
          x={CX}
          y={CY + 13}
          textAnchor="middle"
          fontSize={7.5}
          fontFamily="var(--font-mono)"
          fill="var(--text-secondary)"
        >
          {spec.note}
        </text>
      </svg>
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--text-secondary)',
          textTransform: 'uppercase',
          letterSpacing: 0.5,
        }}
      >
        {spec.label}
      </span>
    </div>
  );
};

const RiskGauges: React.FC<RiskGaugesProps> = ({ portfolioRisk, className }) => {
  if (!portfolioRisk) {
    return (
      <div
        className={className}
        style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', fontSize: 12, padding: 12 }}
      >
        No portfolio risk data.
      </div>
    );
  }

  const gauges = buildGauges(portfolioRisk);

  if (gauges.length === 0) {
    return (
      <div
        className={className}
        style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', fontSize: 12, padding: 12 }}
      >
        Risk metrics unavailable (insufficient holdings/history).
      </div>
    );
  }

  return (
    <div
      className={className}
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 16,
        padding: 12,
        background: 'var(--bg-panel)',
        border: '1px solid var(--border)',
        borderRadius: 2,
      }}
    >
      {gauges.map((g) => (
        <Gauge key={g.key} spec={g} />
      ))}
    </div>
  );
};

export default RiskGauges;
