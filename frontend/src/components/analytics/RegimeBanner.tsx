/**
 * RegimeBanner — current market regime + position-sizing / stop bias.
 *
 * Renders the payload-level {@link RegimeBlock} (`scan_analytics.regime_block`):
 * the regime label, the suggested position-size multiplier, the stop ATR
 * multiplier, and any note. The accent color encodes the regime class so the
 * cockpit shows "risk-on vs risk-off" at a glance.
 *
 * Pure inline CSS — drops to a muted "regime unavailable" strip when the block
 * is null (regime read failed / not computed yet).
 */

import React from 'react';
import type { RegimeBlock } from './types';
import ExplainButton from './ExplainButton';

export interface RegimeBannerProps {
  regime: RegimeBlock | null | undefined;
  className?: string;
}

interface RegimeStyle {
  accent: string;
  bg: string;
  glyph: string;
}

/** Map a regime class / label to an accent + glyph. Defensive about casing. */
function styleFor(regime: RegimeBlock): RegimeStyle {
  const key = `${regime.regime_class ?? ''} ${regime.label ?? ''} ${regime.trend_direction ?? ''}`.toLowerCase();
  if (/bull|risk[- ]?on|uptrend|leading|expansion/.test(key)) {
    return { accent: '#22c55e', bg: 'rgba(34,197,94,0.10)', glyph: '▲' };
  }
  if (/bear|risk[- ]?off|downtrend|crisis|contraction|lagging/.test(key)) {
    return { accent: '#ef4444', bg: 'rgba(239,68,68,0.10)', glyph: '▼' };
  }
  if (/volatile|high[- ]?vol|choppy|transition/.test(key)) {
    return { accent: '#f59e0b', bg: 'rgba(245,158,11,0.10)', glyph: '◆' };
  }
  return { accent: '#94a3b8', bg: 'rgba(148,163,184,0.10)', glyph: '—' };
}

function fmtMult(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return '—';
  return `${x.toFixed(2)}×`;
}

function fmtPct(x: number | null | undefined): string {
  if (x == null || !Number.isFinite(x)) return '—';
  return `${(x * 100).toFixed(0)}%`;
}

const RegimeBanner: React.FC<RegimeBannerProps> = ({ regime, className }) => {
  if (!regime || (regime.label == null && regime.regime_class == null)) {
    return (
      <div className={className} style={unavailableStyle}>
        <span style={{ fontWeight: 600 }}>Market Regime</span>
        <span style={{ color: '#64748b' }}>unavailable — run a scan to read the benchmark.</span>
      </div>
    );
  }

  const s = styleFor(regime);
  const title = regime.label ?? regime.regime_class ?? 'Unknown';

  return (
    <div
      className={className}
      style={{
        ...bannerStyle,
        background: s.bg,
        borderLeft: `4px solid ${s.accent}`,
      }}
      role="status"
      aria-label={`Market regime: ${title}`}
    >
      <div style={headStyle}>
        <span style={{ color: s.accent, fontSize: 18, lineHeight: 1 }}>{s.glyph}</span>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span style={{ fontSize: 11, letterSpacing: 0.5, color: '#94a3b8', textTransform: 'uppercase' }}>
            Market Regime{regime.benchmark ? ` · ${regime.benchmark}` : ''}
          </span>
          <span style={{ fontSize: 16, fontWeight: 700, color: s.accent }}>{title}</span>
        </div>
      </div>

      <div style={metricsStyle}>
        <Metric label="Size bias" value={fmtMult(regime.size_multiplier)} accent={s.accent} />
        <Metric label="Stop ATR" value={fmtMult(regime.stop_atr_multiplier)} />
        {regime.volatility_regime != null && <Metric label="Volatility" value={regime.volatility_regime} />}
        {regime.estimated_probability != null && (
          <Metric label="Confidence" value={fmtPct(regime.estimated_probability)} />
        )}
      </div>

      {regime.note && <p style={noteStyle}>{regime.note}</p>}

      <ExplainButton kind="regime" context={{ regime }} label="✦ Explain this regime" />
    </div>
  );
};

const Metric: React.FC<{ label: string; value: string; accent?: string }> = ({ label, value, accent }) => (
  <div style={metricStyle}>
    <span style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5 }}>{label}</span>
    <span style={{ fontSize: 15, fontWeight: 600, color: accent ?? '#e2e8f0', fontVariantNumeric: 'tabular-nums' }}>
      {value}
    </span>
  </div>
);

const bannerStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 10,
  padding: '12px 16px',
  borderRadius: 8,
  background: 'rgba(148,163,184,0.10)',
};

const headStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
};

const metricsStyle: React.CSSProperties = {
  display: 'flex',
  gap: 24,
  flexWrap: 'wrap',
};

const metricStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 2,
};

const noteStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 12,
  color: '#94a3b8',
  lineHeight: 1.4,
};

const unavailableStyle: React.CSSProperties = {
  display: 'flex',
  gap: 10,
  alignItems: 'center',
  padding: '10px 14px',
  borderRadius: 8,
  border: '1px dashed #334155',
  fontSize: 13,
  color: '#94a3b8',
};

export default RegimeBanner;
