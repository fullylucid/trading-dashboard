/**
 * SectorRotation — the daily sector-rotation intelligence cockpit.
 *
 * Loading is non-blocking by design (the sweep is slow + rate-limited):
 *   1. On mount, GET `/api/sector-rotation/latest` — an instant snapshot read
 *      that NEVER triggers a compute. The page renders whatever is cached.
 *   2. If there is no snapshot yet, or it is stale, POST `/refresh` to kick a
 *      background sweep and poll `/latest` until it lands. A cold load shows a
 *      "computing first sweep" state instead of hanging on the request.
 *
 * Renders:
 *   - RotationAssessment  (the LLM daily read: concise + deep-dive, result.assessment)
 *   - SectorContributors  (which stocks pull each sector up/down, result.contributors)
 *   - SectorRRG           (RS-Ratio vs RS-Momentum quadrants, result.market.sectors)
 *   - SectorDonut         (portfolio exposure tinted by rotation, result.companies.tagged)
 *   - rotating-IN / rotating-OUT leader boards (result.rotation)
 *   - affected holdings   (tailwinds / risks, result.companies)
 *
 * Strict TS, null-guarded throughout — the backend degrades any uncomputable
 * field to null/[] rather than raising, so every block renders defensively.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import SectorRRG from '../components/analytics/SectorRRG';
import SectorDonut from '../components/analytics/SectorDonut';
import SectorContributors from '../components/analytics/SectorContributors';
import RotationAssessment from '../components/analytics/RotationAssessment';
import ExplainButton from '../components/analytics/ExplainButton';
import type {
  RsRatioRow,
  RotationRow,
  CompaniesBlock,
  RotationStatus,
  ContributorsBlock,
  AssessmentBlock,
} from '../components/analytics/types';

/** `result` field of the sector-rotation envelope. */
interface SectorRotationResult {
  rotation?: Record<string, RotationRow> | null;
  companies?: CompaniesBlock | null;
  market?: { sectors?: Record<string, RsRatioRow> | null; benchmark?: string | null } | null;
  contributors?: ContributorsBlock | null;
  assessment?: AssessmentBlock | null;
  summary?: {
    headline?: string | null;
    rotating_in?: string[] | null;
    rotating_out?: string[] | null;
    sources_ok?: Record<string, boolean> | null;
  } | null;
  sources_ok?: Record<string, boolean> | null;
}

/** Envelope returned by `GET /api/sector-rotation/latest`. */
interface SectorRotationEnvelope {
  saved_at?: string | null;
  saved_at_pt?: string | null;
  age_minutes?: number | null;
  cached?: boolean | null;
  stale?: boolean | null;
  computing?: boolean | null;
  result?: SectorRotationResult | null;
}

const STATUS_COLOR: Record<RotationStatus, string> = {
  'rotating-IN': '#22c55e',
  'rotating-OUT': '#ef4444',
  neutral: '#94a3b8',
};

const POLL_INTERVAL_MS = 4000;
// A cold sweep is rate-limited (constituent quotes + news under Finnhub's
// 60/min ceiling) so it can run several minutes; the daily cron normally keeps
// the snapshot warm so users rarely hit this path.
const POLL_TIMEOUT_MS = 6 * 60 * 1000;

function fmtScore(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—';
  return v.toFixed(0);
}

function fmtConf(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—';
  return `${v.toFixed(0)}%`;
}

function fmtAge(mins: number | null | undefined): string {
  if (mins == null) return '';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

const panel: React.CSSProperties = {
  background: 'var(--bg-panel)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  padding: 16,
};

const heading: React.CSSProperties = {
  fontSize: 14,
  fontWeight: 700,
  color: 'var(--text-primary)',
  margin: '0 0 12px',
  textTransform: 'uppercase',
  letterSpacing: 0.5,
};

const SectorRotation: React.FC = () => {
  const [envelope, setEnvelope] = useState<SectorRotationEnvelope | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [computing, setComputing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Poll lifecycle guards (survive re-renders, cleared on unmount).
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollDeadline = useRef<number>(0);
  const mounted = useRef<boolean>(true);

  const stopPolling = useCallback(() => {
    if (pollTimer.current) {
      clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  /** Instant snapshot read — never triggers a compute. Returns the envelope. */
  const fetchLatest = useCallback(async (): Promise<SectorRotationEnvelope | null> => {
    try {
      const resp = await axios.get<SectorRotationEnvelope>('/api/sector-rotation/latest');
      if (!mounted.current) return null;
      setEnvelope(resp.data);
      setComputing(Boolean(resp.data.computing));
      setError(null);
      return resp.data;
    } catch (err) {
      if (!mounted.current) return null;
      const msg = axios.isAxiosError(err)
        ? err.response?.data?.error ?? err.message
        : 'Failed to load sector rotation';
      setError(msg);
      return null;
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, []);

  const pollOnce = useCallback(async (): Promise<void> => {
    const env = await fetchLatest();
    if (!mounted.current) return;
    const done = env != null && !env.computing && env.result != null && env.stale !== true;
    if (done || Date.now() > pollDeadline.current) {
      stopPolling();
      setComputing(false);
      return;
    }
    pollTimer.current = setTimeout(() => void pollOnce(), POLL_INTERVAL_MS);
  }, [fetchLatest, stopPolling]);

  /** Kick a background sweep, then poll /latest until it lands. */
  const triggerRefresh = useCallback(async (): Promise<void> => {
    try {
      setComputing(true);
      setError(null);
      await axios.post('/api/sector-rotation/refresh');
    } catch (err) {
      // A 202 (already running) is expected and fine; only surface real errors.
      if (axios.isAxiosError(err) && err.response?.status === 202) {
        // already running — fall through to polling.
      } else if (mounted.current) {
        const msg = axios.isAxiosError(err)
          ? err.response?.data?.error ?? err.message
          : 'Failed to start sweep';
        setError(msg);
      }
    }
    pollDeadline.current = Date.now() + POLL_TIMEOUT_MS;
    stopPolling();
    pollTimer.current = setTimeout(() => void pollOnce(), POLL_INTERVAL_MS);
  }, [pollOnce, stopPolling]);

  // Mount: read the snapshot instantly; auto-refresh if missing or stale.
  useEffect(() => {
    mounted.current = true;
    void (async () => {
      const env = await fetchLatest();
      if (!mounted.current || env == null) return;
      const needsSweep = env.result == null || env.stale === true;
      if (needsSweep && !env.computing) {
        void triggerRefresh();
      } else if (env.computing) {
        // A sweep is already running (e.g. cron) — just poll for it.
        pollDeadline.current = Date.now() + POLL_TIMEOUT_MS;
        pollTimer.current = setTimeout(() => void pollOnce(), POLL_INTERVAL_MS);
      }
    })();
    return () => {
      mounted.current = false;
      stopPolling();
    };
  }, [fetchLatest, triggerRefresh, pollOnce, stopPolling]);

  const result = envelope?.result ?? null;

  const sectors = result?.market?.sectors ?? null;
  const companies = result?.companies ?? null;
  const tagged = companies?.tagged ?? null;
  const contributors = result?.contributors ?? null;
  const assessment = result?.assessment ?? null;

  // Rotation leader boards: split the fused rotation map by status, ranked.
  const { leadersIn, leadersOut } = useMemo(() => {
    const rows = Object.values(result?.rotation ?? {});
    const ins = rows
      .filter((r) => r.status === 'rotating-IN')
      .sort((a, b) => b.rotation_score - a.rotation_score);
    const outs = rows
      .filter((r) => r.status === 'rotating-OUT')
      .sort((a, b) => a.rotation_score - b.rotation_score);
    return { leadersIn: ins, leadersOut: outs };
  }, [result?.rotation]);

  const donutWeights = undefined;
  const tailwinds = companies?.tailwinds ?? [];
  const risks = companies?.risks ?? [];
  const topIn = companies?.top_in_sectors ?? [];

  const firstSweep = computing && result == null;

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '16px 16px 24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 20 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
            Sector Rotation
          </h1>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>
            {result?.summary?.headline ?? 'How capital is rotating across sectors, fused from 5 free streams.'}
          </div>
          {result != null && (
            <ExplainButton
              kind="sector"
              label="✦ Explain the rotation"
              context={{
                summary: result.summary,
                rotating_in: leadersIn.slice(0, 5),
                rotating_out: leadersOut.slice(0, 5),
              }}
            />
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {envelope?.saved_at != null && (
            <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
              {envelope.cached ? 'cached' : 'fresh'} · {fmtAge(envelope.age_minutes)}
              {envelope.stale ? ' · stale' : ''}
            </span>
          )}
          <button
            type="button"
            onClick={() => void triggerRefresh()}
            disabled={computing}
            style={{
              background: computing ? 'transparent' : 'var(--neon-green)',
              color: computing ? 'var(--text-secondary)' : 'var(--bg-base)',
              border: '1px solid var(--neon-green)',
              borderRadius: 4,
              padding: '6px 14px',
              fontFamily: 'var(--font-mono)',
              fontSize: 13,
              fontWeight: 600,
              cursor: computing ? 'not-allowed' : 'pointer',
            }}
          >
            {computing ? 'Sweeping…' : '↻ Refresh sweep'}
          </button>
        </div>
      </div>

      {error && (
        <div style={{ ...panel, borderColor: 'var(--danger)', color: 'var(--danger)', marginBottom: 16 }}>
          {error}
        </div>
      )}

      {loading && result == null && !computing && (
        <div style={{ ...panel, color: 'var(--text-secondary)', textAlign: 'center' }}>Loading…</div>
      )}

      {firstSweep && (
        <div style={{ ...panel, color: 'var(--text-secondary)', textAlign: 'center', lineHeight: 1.6 }}>
          <div style={{ fontSize: 15, color: 'var(--text-primary)', marginBottom: 6 }}>
            Running the first sector-rotation sweep…
          </div>
          This fuses price/RRG, insider flow, news sentiment, earnings/econ catalysts and policy
          across 11 sectors, then asks Opus for the daily read. It can take a minute on a cold
          start — results will appear here automatically.
        </div>
      )}

      {result && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* LLM daily read */}
          <RotationAssessment assessment={assessment} />

          {/* RRG + donut row */}
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.2fr) minmax(0, 1fr)', gap: 20 }}>
            <div style={panel}>
              <h2 style={heading}>Relative Rotation Graph</h2>
              <SectorRRG sectors={sectors} size={400} />
            </div>
            <div style={panel}>
              <h2 style={heading}>Portfolio Sector Exposure</h2>
              <SectorDonut tagged={tagged} weights={donutWeights} size={220} />
            </div>
          </div>

          {/* Who is pulling each sector */}
          <div style={panel}>
            <h2 style={heading}>Stocks Pulling Sectors</h2>
            <SectorContributors contributors={contributors} maxSectors={6} />
          </div>

          {/* Leader boards */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
            <div style={panel}>
              <h2 style={{ ...heading, color: STATUS_COLOR['rotating-IN'] }}>▲ Rotating In</h2>
              <LeaderTable rows={leadersIn} positive />
            </div>
            <div style={panel}>
              <h2 style={{ ...heading, color: STATUS_COLOR['rotating-OUT'] }}>▼ Rotating Out</h2>
              <LeaderTable rows={leadersOut} positive={false} />
            </div>
          </div>

          {/* Affected holdings */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
            <div style={panel}>
              <h2 style={{ ...heading, color: STATUS_COLOR['rotating-IN'] }}>Holdings With Tailwinds</h2>
              <SymbolChips symbols={tailwinds} color={STATUS_COLOR['rotating-IN']} empty="No holdings in rotating-in sectors." />
            </div>
            <div style={panel}>
              <h2 style={{ ...heading, color: STATUS_COLOR['rotating-OUT'] }}>Holdings At Risk</h2>
              <SymbolChips symbols={risks} color={STATUS_COLOR['rotating-OUT']} empty="No holdings in rotating-out sectors." />
            </div>
          </div>

          {/* Candidate tickers in strongest rotating-in sectors */}
          {topIn.length > 0 && (
            <div style={panel}>
              <h2 style={heading}>Candidates In Strongest Rotating-In Sectors</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {topIn.map((s, i) => (
                  <div key={`${s.sector ?? 'sec'}-${i}`} style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', minWidth: 160 }}>
                      {s.sector ?? '—'}
                      {s.etf ? <span style={{ color: 'var(--text-secondary)', marginLeft: 6 }}>{s.etf}</span> : null}
                    </span>
                    <span style={{ fontSize: 12, color: STATUS_COLOR['rotating-IN'], minWidth: 90 }}>
                      score {fmtScore(s.rotation_score)} · {fmtConf(s.confidence)}
                    </span>
                    <SymbolChips symbols={s.candidate_tickers ?? []} color="var(--neon-cyan)" empty="—" />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const LeaderTable: React.FC<{ rows: RotationRow[]; positive: boolean }> = ({ rows, positive }) => {
  if (rows.length === 0) {
    return (
      <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
        {positive ? 'No sectors rotating in.' : 'No sectors rotating out.'}
      </div>
    );
  }
  const color = positive ? STATUS_COLOR['rotating-IN'] : STATUS_COLOR['rotating-OUT'];
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
      <thead>
        <tr style={{ color: 'var(--text-secondary)', textAlign: 'left' }}>
          <th style={{ padding: '4px 6px' }}>Sector</th>
          <th style={{ padding: '4px 6px' }}>ETF</th>
          <th style={{ padding: '4px 6px' }}>Score</th>
          <th style={{ padding: '4px 6px' }}>Conf</th>
          <th style={{ padding: '4px 6px' }}>Phase</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.sector} style={{ borderTop: '1px solid var(--border)' }}>
            <td style={{ padding: '5px 6px', color: 'var(--text-primary)', fontWeight: 600 }}>{r.sector}</td>
            <td style={{ padding: '5px 6px', color: 'var(--text-secondary)' }}>{r.etf ?? '—'}</td>
            <td style={{ padding: '5px 6px', color, fontVariantNumeric: 'tabular-nums' }}>{fmtScore(r.rotation_score)}</td>
            <td style={{ padding: '5px 6px', color: 'var(--text-secondary)', fontVariantNumeric: 'tabular-nums' }}>{fmtConf(r.confidence)}</td>
            <td style={{ padding: '5px 6px', color: 'var(--text-secondary)' }}>{r.phase}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
};

const SymbolChips: React.FC<{ symbols: string[]; color: string; empty: string }> = ({ symbols, color, empty }) => {
  if (!symbols || symbols.length === 0) {
    return <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{empty}</span>;
  }
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {symbols.map((s) => (
        <span
          key={s}
          style={{
            fontSize: 12,
            fontWeight: 600,
            color,
            border: `1px solid ${color}`,
            borderRadius: 4,
            padding: '2px 8px',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {s}
        </span>
      ))}
    </div>
  );
};

export default SectorRotation;
