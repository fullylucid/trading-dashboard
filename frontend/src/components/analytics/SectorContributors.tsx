/**
 * SectorContributors — which individual stocks are pulling each sector up/down.
 *
 * Consumes `result.contributors.by_etf`. For each sector (ordered by the absolute
 * size of its net constituent move), shows the leaders pulling it up and the
 * laggards dragging it down: % move (extended-hours aware — counts after-hours,
 * overnight, and pre-market), a contribution bar, a 📍 flag for names in the
 * book, and a news-tone dot + headline tooltip when available.
 *
 * Null-guarded throughout — the backend degrades any uncomputable field to
 * null/[] and may omit the whole block, so every level renders defensively.
 */

import { useMemo } from 'react';
import type { ContributorRow, ContributorsBlock, SectorContributorBlock } from './types';
import { useIsMobile } from '../../hooks/useMediaQuery';

const UP = '#22c55e';
const DOWN = '#ef4444';
const NEUTRAL = '#94a3b8';

const TONE_COLOR: Record<string, string> = {
  positive: UP,
  negative: DOWN,
  neutral: NEUTRAL,
};

export interface SectorContributorsProps {
  contributors: ContributorsBlock | null | undefined;
  /** Show at most this many sectors (default: all that have movers). */
  maxSectors?: number;
}

function fmtPct(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
}

const emptyStyle: React.CSSProperties = {
  fontSize: 12,
  color: 'var(--text-secondary)',
  border: '1px dashed var(--border)',
  borderRadius: 6,
  padding: '16px',
  textAlign: 'center',
};

const SectorContributors: React.FC<SectorContributorsProps> = ({ contributors, maxSectors }) => {
  const isMobile = useIsMobile();
  const sectors = useMemo<SectorContributorBlock[]>(() => {
    const byEtf = contributors?.by_etf ?? null;
    if (!byEtf) return [];
    const rows = Object.values(byEtf).filter(
      (s) => (s.leaders_up?.length ?? 0) > 0 || (s.leaders_down?.length ?? 0) > 0,
    );
    rows.sort((a, b) => Math.abs(b.net_contribution ?? 0) - Math.abs(a.net_contribution ?? 0));
    return typeof maxSectors === 'number' ? rows.slice(0, maxSectors) : rows;
  }, [contributors, maxSectors]);

  // Normalize bar widths against the single biggest absolute contribution shown.
  const maxAbs = useMemo<number>(() => {
    let m = 0;
    for (const s of sectors) {
      for (const r of [...(s.leaders_up ?? []), ...(s.leaders_down ?? [])]) {
        if (r.contribution != null) m = Math.max(m, Math.abs(r.contribution));
      }
    }
    return m || 1;
  }, [sectors]);

  if (sectors.length === 0) {
    return (
      <div style={emptyStyle}>
        No constituent moves yet — the next sweep will show which stocks are pulling each sector
        (counting after-hours and overnight moves).
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {sectors.map((s) => (
        <div key={s.etf}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>
              {s.sector ?? s.etf}
            </span>
            <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{s.etf}</span>
            <span style={{ fontSize: 11, color: s.net_contribution >= 0 ? UP : DOWN }}>
              net {s.net_contribution >= 0 ? '+' : ''}
              {(s.net_contribution * 100).toFixed(0)} bps
            </span>
            {s.breadth != null && (
              <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                · {Math.round(s.breadth * 100)}% of names up
              </span>
            )}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 14 }}>
            <ContributorColumn title="Pulling up" rows={s.leaders_up ?? []} color={UP} maxAbs={maxAbs} />
            <ContributorColumn title="Dragging down" rows={s.leaders_down ?? []} color={DOWN} maxAbs={maxAbs} />
          </div>
        </div>
      ))}
    </div>
  );
};

const ContributorColumn: React.FC<{
  title: string;
  rows: ContributorRow[];
  color: string;
  maxAbs: number;
}> = ({ title, rows, color, maxAbs }) => (
  <div>
    <div style={{ fontSize: 10, color, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>
      {title}
    </div>
    {rows.length === 0 ? (
      <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>—</div>
    ) : (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        {rows.map((r) => (
          <ContributorBar key={r.symbol} row={r} color={color} maxAbs={maxAbs} />
        ))}
      </div>
    )}
  </div>
);

const ContributorBar: React.FC<{ row: ContributorRow; color: string; maxAbs: number }> = ({
  row,
  color,
  maxAbs,
}) => {
  const pctOfMax = row.contribution != null ? Math.abs(row.contribution) / maxAbs : 0;
  const width = Math.max(2, Math.min(100, pctOfMax * 100));
  const tone = row.news?.label;
  const toneColor = tone ? TONE_COLOR[tone] ?? NEUTRAL : null;
  const headline = row.news?.top_headline ?? undefined;

  return (
    <div
      title={headline}
      style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: headline ? 'help' : 'default' }}
    >
      <span
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: 'var(--text-primary)',
          fontFamily: 'var(--font-mono)',
          minWidth: 56,
        }}
      >
        {row.symbol}
        {row.in_portfolio && <span title="In your portfolio"> 📍</span>}
      </span>
      <div style={{ flex: 1, height: 8, background: 'var(--bg-elevated)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${width}%`, height: '100%', background: color, opacity: 0.85 }} />
      </div>
      <span
        style={{
          fontSize: 11,
          color,
          fontVariantNumeric: 'tabular-nums',
          minWidth: 52,
          textAlign: 'right',
        }}
      >
        {fmtPct(row.pct_change)}
      </span>
      {toneColor && (
        <span
          title={headline ? `${tone}: ${headline}` : tone ?? undefined}
          style={{ width: 7, height: 7, borderRadius: '50%', background: toneColor, flexShrink: 0 }}
        />
      )}
    </div>
  );
};

export default SectorContributors;
