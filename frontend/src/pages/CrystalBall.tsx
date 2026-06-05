/**
 * Crystal Ball — the dark art of prediction.
 *
 * A calibrated reversal-probability read for one symbol. It does NOT claim to
 * call exact tops/bottoms; it estimates the odds a local reversal is near, the
 * direction, and a confidence GATED by how predictable the regime actually is
 * (Hurst distance from a random walk). The honesty is the feature — a coin-flip
 * tape reads "low confidence" no matter how loud the indicators.
 *
 * Pure rendering of GET /api/crystal-ball/{symbol} (see backend
 * crystal_ball/fusion.py). Convention kept: centered <PageHeader> carries the
 * symbol input; neon-terminal theme.
 */

import { useEffect, useState, useCallback } from 'react';

import PageHeader from '../components/PageHeader';

const GREEN = '#00ff41';
const DIM = 'rgba(0,255,65,0.55)';
const FAINT = 'rgba(0,255,65,0.25)';
const CYAN = '#00d9ff';
const RED = '#ff003c';
const AMBER = '#ffcc00';
const BG = '#0a0e0a';

type Signal = {
  name: string;
  label: string;
  value: string | number;
  vote: 'top' | 'bottom' | 'none';
  strength: number;
  weight: number;
  note: string;
};

type CrystalRead = {
  symbol: string;
  direction: 'top' | 'bottom' | 'none';
  reversal_probability: number;
  confidence: 'low' | 'medium' | 'high';
  predictability: number | null;
  physics: {
    hurst: number | null;
    ou_half_life: number | null;
    ou_z: number | null;
    permutation_entropy: number | null;
  };
  signals: Signal[];
  thesis: string;
  invalidation: { level: number; rule: string; distance_pct: number } | null;
  last_close?: number | null;
  range?: string;
  disclaimer: string;
};

type EquityPt = { t: string | number; equity: number };
type BacktestResult = {
  ok: boolean;
  symbol?: string;
  eval_bars?: number;
  stats: {
    total_return: number; cagr: number; sharpe: number; sortino: number;
    max_drawdown: number; calmar: number; exposure: number; n_trades: number;
    win_rate: number | null; profit_factor: number | null; expectancy: number | null;
    avg_bars_held: number | null;
  };
  benchmark: { total_return: number; cagr: number; sharpe: number; max_drawdown: number };
  calibration: { brier: number | null; n: number; buckets: { range: string; n: number; predicted: number; realized: number }[] };
  equity_curve: EquityPt[];
  params: Record<string, unknown>;
};
type Calibration = {
  n_resolved: number; n_open: number; hit_rate: number | null; brier: number | null;
  by_confidence: { confidence: string; n: number; hit_rate: number; avg_prob: number }[];
  by_probability: { range: string; n: number; predicted: number; realized: number }[];
  interpretation?: string; note?: string;
};

const pct = (x: number | null | undefined, d = 1) =>
  x == null ? '—' : `${(x * 100).toFixed(d)}%`;

const inputStyle: React.CSSProperties = {
  background: '#000', color: GREEN, border: `1px solid ${FAINT}`,
  fontFamily: 'monospace', fontSize: 13, padding: '5px 10px',
  borderRadius: 4, width: 120, textTransform: 'uppercase',
};
const btnStyle: React.CSSProperties = {
  background: '#000', color: GREEN, border: `1px solid ${FAINT}`,
  fontFamily: 'monospace', fontSize: 12, padding: '5px 14px',
  cursor: 'pointer', borderRadius: 4,
};
const card: React.CSSProperties = {
  border: `1px solid ${FAINT}`, borderRadius: 8, background: BG,
  padding: 16, fontFamily: 'monospace', color: GREEN,
};
const btStyle: React.CSSProperties = {
  background: '#000', color: CYAN, border: `1px solid rgba(0,217,255,0.4)`,
  fontFamily: 'monospace', fontSize: 11.5, padding: '5px 12px',
  cursor: 'pointer', borderRadius: 4,
};

const directionColor = (d: string) => (d === 'top' ? RED : d === 'bottom' ? GREEN : DIM);
const directionLabel = (d: string) =>
  d === 'top' ? 'LOCAL TOP — bearish reversal'
    : d === 'bottom' ? 'LOCAL BOTTOM — bullish reversal'
    : 'NO REVERSAL EDGE';
const confColor = (c: string) => (c === 'high' ? GREEN : c === 'medium' ? AMBER : DIM);

function Bar({ value, color, height = 8 }: { value: number; color: string; height?: number }) {
  return (
    <div style={{ background: 'rgba(255,255,255,0.06)', borderRadius: 4, height, width: '100%', overflow: 'hidden' }}>
      <div style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, background: color, height: '100%',
        boxShadow: `0 0 8px ${color}`, transition: 'width .4s' }} />
    </div>
  );
}

function EquityCurve({ series, color = CYAN, width = 600, height = 80 }:
  { series: number[]; color?: string; width?: number; height?: number }) {
  if (series.length < 2) return null;
  const min = Math.min(...series), max = Math.max(...series), span = (max - min) || 1;
  const line = series
    .map((v, i) => `${(i / (series.length - 1)) * width},${height - ((v - min) / span) * height}`)
    .join(' ');
  const baseY = height - ((1 - min) / span) * height; // equity = 1.0 reference
  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none"
      style={{ display: 'block', background: 'rgba(0,255,65,0.03)', borderRadius: 4 }}>
      {min < 1 && max > 1 && (
        <line x1={0} y1={baseY} x2={width} y2={baseY} stroke={FAINT} strokeWidth={0.5} strokeDasharray="4 4" />
      )}
      <polyline points={line} fill="none" stroke={color} strokeWidth={1.6} />
    </svg>
  );
}

function hurstLabel(h: number | null): string {
  if (h == null) return '—';
  if (h < 0.45) return `${h.toFixed(2)} · mean-reverting`;
  if (h > 0.55) return `${h.toFixed(2)} · trending`;
  return `${h.toFixed(2)} · random walk`;
}

const CrystalBall: React.FC = () => {
  const [symbol, setSymbol] = useState('SPY');
  const [draft, setDraft] = useState('SPY');
  const [data, setData] = useState<CrystalRead | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [bt, setBt] = useState<BacktestResult | null>(null);
  const [btLoading, setBtLoading] = useState(false);
  const [btErr, setBtErr] = useState<string | null>(null);
  const [cal, setCal] = useState<Calibration | null>(null);
  const [trackMsg, setTrackMsg] = useState<string | null>(null);

  const load = useCallback(async (sym: string) => {
    setLoading(true); setError(null);
    try {
      const r = await fetch(`/api/crystal-ball/${encodeURIComponent(sym)}`);
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j.detail || `Request failed (${r.status})`);
      }
      setData(await r.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to consult the Crystal Ball.');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadCalibration = useCallback(async () => {
    try {
      const r = await fetch('/api/crystal-ball/calibration');
      if (r.ok) setCal(await r.json());
    } catch { /* track record is best-effort */ }
  }, []);

  useEffect(() => { load(symbol); setBt(null); setBtErr(null); }, [symbol, load]);
  useEffect(() => { loadCalibration(); }, [loadCalibration]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const next = draft.trim().toUpperCase();
    if (next) setSymbol(next);
  };

  const runBacktest = async () => {
    setBtLoading(true); setBtErr(null);
    try {
      const r = await fetch(`/api/crystal-ball/${encodeURIComponent(symbol)}/backtest?range=2y`);
      if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.detail || `Backtest failed (${r.status})`); }
      setBt(await r.json());
    } catch (e) {
      setBtErr(e instanceof Error ? e.message : 'Backtest failed'); setBt(null);
    } finally { setBtLoading(false); }
  };

  const logPrediction = async () => {
    setTrackMsg('Logging…');
    try {
      const r = await fetch(`/api/crystal-ball/${encodeURIComponent(symbol)}/journal`, { method: 'POST' });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) setTrackMsg(j.detail || 'Failed to log.');
      else setTrackMsg(j.recorded
        ? `Logged ${symbol} ${j.entry?.direction} call @ ${j.entry?.confidence} confidence.`
        : `${symbol} has no directional call to log right now.`);
      loadCalibration();
    } catch { setTrackMsg('Failed to log.'); }
  };

  const resolveTrack = async () => {
    setTrackMsg('Resolving outcomes…');
    try {
      const r = await fetch('/api/crystal-ball/journal/resolve', { method: 'POST' });
      const j = await r.json().catch(() => ({}));
      setTrackMsg(r.ok ? `Resolved ${j.resolved}; ${j.skipped} still awaiting their horizon.` : 'Resolve failed.');
      loadCalibration();
    } catch { setTrackMsg('Resolve failed.'); }
  };

  const dir = data?.direction ?? 'none';
  const prob = data?.reversal_probability ?? 0;

  return (
    <div className="max-w-[1100px] mx-auto px-4 sm:px-6 lg:px-8 pt-2 pb-10">
      <PageHeader title="🔮 Crystal Ball" subtitle={`${symbol} · reversal divination`}>
        <form onSubmit={submit} style={{ display: 'flex', gap: 6 }}>
          <input aria-label="Symbol" value={draft} onChange={(e) => setDraft(e.target.value)}
            placeholder="SYMBOL" style={inputStyle} />
          <button type="submit" style={btnStyle}>Gaze</button>
        </form>
      </PageHeader>

      {loading && <p style={{ color: DIM, fontFamily: 'monospace', textAlign: 'center' }}>Consulting the ether…</p>}
      {error && (
        <div style={{ ...card, borderColor: RED, color: RED, textAlign: 'center' }}>
          {error}
        </div>
      )}

      {data && !loading && !error && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* ---- Headline read ---- */}
          <div style={{ ...card, borderColor: directionColor(dir), textAlign: 'center', padding: 22 }}>
            <div style={{ fontSize: 12, letterSpacing: 2, color: DIM }}>THE CRYSTAL BALL SEES</div>
            <div style={{ fontSize: 22, fontWeight: 700, margin: '8px 0', color: directionColor(dir),
              textShadow: `0 0 14px ${directionColor(dir)}` }}>
              {directionLabel(dir)}
            </div>
            <div style={{ fontSize: 48, fontWeight: 800, lineHeight: 1.1, color: directionColor(dir) }}>
              {(prob * 100).toFixed(0)}%
            </div>
            <div style={{ fontSize: 11, color: DIM, marginBottom: 12 }}>reversal probability</div>
            <div style={{ maxWidth: 420, margin: '0 auto' }}>
              <Bar value={prob} color={directionColor(dir)} height={10} />
            </div>
            <div style={{ marginTop: 14, display: 'flex', justifyContent: 'center', gap: 24, fontSize: 12 }}>
              <span>confidence{' '}
                <b style={{ color: confColor(data.confidence), textShadow: `0 0 8px ${confColor(data.confidence)}` }}>
                  {data.confidence.toUpperCase()}
                </b>
              </span>
              <span style={{ color: DIM }}>
                predictability{' '}
                <b style={{ color: GREEN }}>
                  {data.predictability != null ? `${(data.predictability * 100).toFixed(0)}%` : '—'}
                </b>
              </span>
            </div>
          </div>

          {/* ---- Thesis + invalidation ---- */}
          <div style={card}>
            <div style={{ fontSize: 11, letterSpacing: 1, color: CYAN, marginBottom: 8 }}>READING</div>
            <p style={{ margin: 0, lineHeight: 1.6, fontSize: 13.5 }}>{data.thesis}</p>
            {data.invalidation && (
              <p style={{ marginTop: 12, marginBottom: 0, fontSize: 12.5, color: AMBER }}>
                ✖ Invalidation: {data.invalidation.rule} ≈ <b>{data.invalidation.level}</b>
                {' '}({data.invalidation.distance_pct > 0 ? '+' : ''}{data.invalidation.distance_pct}% away)
              </p>
            )}
          </div>

          {/* ---- Physics ---- */}
          <div style={card}>
            <div style={{ fontSize: 11, letterSpacing: 1, color: CYAN, marginBottom: 10 }}>PHYSICS OF THE TAPE</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 14 }}>
              <Metric label="Hurst exponent" value={hurstLabel(data.physics.hurst)} />
              <Metric label="OU mean-rev half-life"
                value={data.physics.ou_half_life != null ? `${data.physics.ou_half_life} bars` : '—'} />
              <Metric label="OU stretch (z)"
                value={data.physics.ou_z != null ? `${data.physics.ou_z > 0 ? '+' : ''}${data.physics.ou_z}σ` : '—'} />
              <Metric label="Permutation entropy"
                value={data.physics.permutation_entropy != null ? data.physics.permutation_entropy.toFixed(3) : '—'}
                hint="diagnostic only" />
            </div>
          </div>

          {/* ---- Signal breakdown ---- */}
          <div style={card}>
            <div style={{ fontSize: 11, letterSpacing: 1, color: CYAN, marginBottom: 10 }}>CONTRIBUTING SIGNALS</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {data.signals.map((s) => (
                <div key={s.name} style={{ display: 'grid', gridTemplateColumns: '160px 70px 1fr', gap: 12, alignItems: 'center' }}>
                  <span style={{ fontSize: 12.5 }}>{s.label}</span>
                  <span style={{ fontSize: 12, fontWeight: 700, color: directionColor(s.vote), textAlign: 'center' }}>
                    {s.vote === 'none' ? '·' : s.vote.toUpperCase()}
                  </span>
                  <div>
                    <Bar value={s.strength} color={directionColor(s.vote)} />
                    <div style={{ fontSize: 10.5, color: DIM, marginTop: 3 }}>{s.note} · {String(s.value)}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* ---- Backtest ---- */}
          <div style={card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, flexWrap: 'wrap', gap: 8 }}>
              <span style={{ fontSize: 11, letterSpacing: 1, color: CYAN }}>BACKTEST · 2Y WALK-FORWARD · NO LOOK-AHEAD</span>
              <button onClick={runBacktest} disabled={btLoading} style={btStyle}>{btLoading ? 'Running…' : 'Run backtest'}</button>
            </div>
            {btErr && <p style={{ color: RED, fontSize: 12, margin: 0 }}>{btErr}</p>}
            {bt && bt.ok && (
              <>
                <EquityCurve series={bt.equity_curve.map((p) => p.equity)} color={bt.stats.total_return >= 0 ? GREEN : RED} />
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, color: DIM, margin: '4px 0 14px' }}>
                  <span>strategy equity · {bt.eval_bars} bars</span>
                  <span>vs buy &amp; hold {pct(bt.benchmark.total_return)} (Sharpe {bt.benchmark.sharpe.toFixed(2)})</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(108px, 1fr))', gap: 12 }}>
                  <Stat label="Total return" value={pct(bt.stats.total_return)} color={bt.stats.total_return >= 0 ? GREEN : RED} />
                  <Stat label="CAGR" value={pct(bt.stats.cagr)} />
                  <Stat label="Sharpe" value={bt.stats.sharpe.toFixed(2)} color={bt.stats.sharpe < 0 ? RED : bt.stats.sharpe >= 1 ? GREEN : AMBER} />
                  <Stat label="Sortino" value={bt.stats.sortino.toFixed(2)} />
                  <Stat label="Max drawdown" value={pct(bt.stats.max_drawdown)} color={RED} />
                  <Stat label="Calmar" value={bt.stats.calmar.toFixed(2)} />
                  <Stat label="Win rate" value={pct(bt.stats.win_rate, 0)} />
                  <Stat label="Profit factor" value={bt.stats.profit_factor != null ? bt.stats.profit_factor.toFixed(2) : '—'} />
                  <Stat label="Trades" value={String(bt.stats.n_trades)} />
                  <Stat label="Avg hold" value={bt.stats.avg_bars_held != null ? `${bt.stats.avg_bars_held}b` : '—'} />
                  <Stat label="Exposure" value={pct(bt.stats.exposure, 0)} />
                  <Stat label="Brier" value={bt.calibration.brier != null ? bt.calibration.brier.toFixed(3) : '—'} />
                </div>
              </>
            )}
            {!bt && !btErr && !btLoading && (
              <p style={{ color: DIM, fontSize: 12, margin: 0 }}>
                Walk-forward backtest of the reversal strategy on {symbol} — long bottoms, short tops,
                with commission &amp; slippage. Strictly no look-ahead; honest stats only.
              </p>
            )}
          </div>

          {/* ---- Track record / calibration ---- */}
          <div style={card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, flexWrap: 'wrap', gap: 8 }}>
              <span style={{ fontSize: 11, letterSpacing: 1, color: CYAN }}>TRACK RECORD · LIVE CALLS, SCORED</span>
              <div style={{ display: 'flex', gap: 6 }}>
                <button onClick={logPrediction} style={btStyle}>Log this call</button>
                <button onClick={resolveTrack} style={btStyle}>Resolve outcomes</button>
              </div>
            </div>
            {trackMsg && <p style={{ fontSize: 12, color: AMBER, marginTop: 0 }}>{trackMsg}</p>}
            {cal && (cal.n_resolved > 0 ? (
              <>
                <div style={{ display: 'flex', gap: 24, fontSize: 13, marginBottom: 8, flexWrap: 'wrap' }}>
                  <span>hit-rate <b style={{ color: (cal.hit_rate ?? 0) >= 0.55 ? GREEN : (cal.hit_rate ?? 0) < 0.45 ? RED : AMBER }}>{pct(cal.hit_rate, 0)}</b></span>
                  <span style={{ color: DIM }}>Brier <b style={{ color: GREEN }}>{cal.brier?.toFixed(3)}</b></span>
                  <span style={{ color: DIM }}>resolved <b style={{ color: GREEN }}>{cal.n_resolved}</b> · open <b style={{ color: GREEN }}>{cal.n_open}</b></span>
                </div>
                {cal.interpretation && <p style={{ fontSize: 12, color: DIM, margin: '0 0 10px' }}>{cal.interpretation}</p>}
                {cal.by_confidence.length > 0 && (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10 }}>
                    {cal.by_confidence.map((b) => (
                      <div key={b.confidence} style={{ border: `1px solid ${FAINT}`, borderRadius: 6, padding: '8px 10px' }}>
                        <div style={{ fontSize: 10.5, color: DIM }}>{b.confidence} conf · n={b.n}</div>
                        <div style={{ fontSize: 14 }}>hit {pct(b.hit_rate, 0)} <span style={{ color: DIM, fontSize: 11 }}>(said {pct(b.avg_prob, 0)})</span></div>
                      </div>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <p style={{ color: DIM, fontSize: 12, margin: 0 }}>
                {cal.note || 'No resolved predictions yet.'}{cal.n_open > 0 ? ` ${cal.n_open} open, awaiting their horizon.` : ''}
              </p>
            ))}
          </div>

          <p style={{ fontSize: 10.5, color: FAINT, fontFamily: 'monospace', textAlign: 'center', lineHeight: 1.5 }}>
            {data.disclaimer}
          </p>
        </div>
      )}
    </div>
  );
};

function Stat({ label, value, color = GREEN }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <div style={{ fontSize: 10.5, color: DIM, marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 15, fontWeight: 600, color }}>{value}</div>
    </div>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <div style={{ fontSize: 10.5, color: DIM, marginBottom: 3 }}>
        {label}{hint && <span style={{ color: FAINT }}> · {hint}</span>}
      </div>
      <div style={{ fontSize: 15, fontWeight: 600 }}>{value}</div>
    </div>
  );
}

export default CrystalBall;
