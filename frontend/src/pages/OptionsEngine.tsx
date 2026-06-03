import { useState, useCallback } from 'react';
import { GREEKS, STRATEGIES, METRICS } from './optionsEducation';
import TVWidget from '../components/TVWidget';
import PageHeader from '../components/PageHeader';

const GREEN = '#00ff41';
const RED = '#ff5555';
const DIM = 'rgba(0,255,65,0.55)';

type Contract = {
  strike: number; kind: string; bid: number; ask: number; mid: number;
  volume: number; open_interest: number; iv: number; delta: number; theta: number; prob_itm: number;
};
type Chain = {
  symbol: string; spot: number; rate: number; expiration: string;
  expirations: string[]; calls: Contract[]; puts: Contract[];
};
type Vertical = {
  label: string; kind: string; direction: string; debit_credit: string; net: number;
  long_strike: number; short_strike: number; max_profit: number; max_loss: number;
  breakeven: number; rr: number; pop: number;
};
type Income = {
  label: string; type: string; strike: number; premium: number; breakeven: number;
  max_profit: number; pop: number; annual_yield: number; cushion: number; theta: number; dte: number;
};
type Leg = { action: string; kind: string; strike: number; premium: number };
type MultiLeg = {
  label: string; type: string; side: string; net: number; max_profit: number;
  max_loss: number; breakevens: number[]; pop: number; undefined_risk: boolean; legs: Leg[];
};
type WheelSugg = { strike: number; premium: number; breakeven: number; pop: number; annual_yield: number; cushion: number };
type Wheel = {
  symbol: string; spot: number; expiration: string; shares_held: number; phase: string;
  current_step: string; next_move: string; suggestions: WheelSugg[];
  steps: { id: string; text: string }[];
};
type Mode = 'spreads' | 'cash_secured_put' | 'covered_call' | 'iron_condor' | 'strangle' | 'straddle' | 'wheel';

const box: React.CSSProperties = {
  background: '#000', color: GREEN, border: `1px solid ${DIM}`, borderRadius: 4,
  fontFamily: 'monospace', padding: '4px 8px',
};
const td: React.CSSProperties = { padding: '2px 6px', fontSize: 11, textAlign: 'right', whiteSpace: 'nowrap' };
const th: React.CSSProperties = { ...td, color: DIM, fontWeight: 400, borderBottom: `1px solid ${DIM}`, cursor: 'help' };

// ---------- payoff chart (generic over a P/L function) ----------
function PayoffChart({ pl, spot, be, x0, x1 }: { pl: (s: number) => number; spot: number; be: number; x0: number; x1: number }) {
  const W = 460, H = 170, pad = 26, N = 90;
  const pts: [number, number][] = [];
  for (let i = 0; i <= N; i++) { const S = x0 + (x1 - x0) * (i / N); pts.push([S, pl(S)]); }
  const ys = pts.map((p) => p[1]); const ymin = Math.min(...ys, -1), ymax = Math.max(...ys, 1);
  const sx = (x: number) => pad + ((x - x0) / (x1 - x0)) * (W - 2 * pad);
  const sy = (y: number) => H - pad - ((y - ymin) / (ymax - ymin)) * (H - 2 * pad);
  const path = pts.map((p, i) => `${i ? 'L' : 'M'}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join(' ');
  return (
    <svg width={W} height={H} style={{ border: `1px solid ${DIM}`, borderRadius: 4, background: '#001000' }}>
      <line x1={pad} y1={sy(0)} x2={W - pad} y2={sy(0)} stroke={DIM} strokeDasharray="3 3" />
      <line x1={sx(spot)} y1={pad} x2={sx(spot)} y2={H - pad} stroke="#7fdfff" strokeDasharray="2 4" />
      <line x1={sx(be)} y1={pad} x2={sx(be)} y2={H - pad} stroke="#ffcc00" strokeDasharray="2 4" />
      <path d={path} fill="none" stroke={GREEN} strokeWidth={2} />
      <text x={sx(spot)} y={H - 6} fill="#7fdfff" fontSize={9} textAnchor="middle">spot {spot.toFixed(0)}</text>
      <text x={sx(be)} y={pad - 3} fill="#ffcc00" fontSize={9} textAnchor="middle">B/E {be.toFixed(1)}</text>
      <text x={pad + 2} y={sy(ymax) + 9} fill={GREEN} fontSize={9}>+{ymax.toFixed(0)}</text>
      <text x={pad + 2} y={sy(ymin) - 2} fill={RED} fontSize={9}>{ymin.toFixed(0)}</text>
    </svg>
  );
}

function GreeksGlossary() {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ border: `1px solid ${DIM}`, borderRadius: 4, marginBottom: 14 }}>
      <div onClick={() => setOpen((v) => !v)} style={{ cursor: 'pointer', padding: '8px 12px', fontSize: 13 }}>
        📖 {open ? '▾' : '▸'} Greeks 101 — what they mean & how a <i>seller</i> uses them
      </div>
      {open && (
        <div style={{ padding: '0 12px 12px' }}>
          {GREEKS.map((g) => (
            <div key={g.sym} style={{ marginBottom: 10, fontSize: 12, lineHeight: 1.5 }}>
              <span style={{ color: GREEN, fontWeight: 700 }}>{g.sym} {g.name}</span> — {g.plain}
              <div style={{ color: '#7fdfff', marginTop: 2 }}>↳ selling: {g.seller}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function OptionsEngine() {
  const [symbol, setSymbol] = useState('NOW');
  const [chain, setChain] = useState<Chain | null>(null);
  const [mode, setMode] = useState<Mode>('cash_secured_put');
  const [kind, setKind] = useState<'call' | 'put'>('call');
  const [dir, setDir] = useState<'bull' | 'bear'>('bull');
  const [verticals, setVerticals] = useState<Vertical[]>([]);
  const [income, setIncome] = useState<Income[]>([]);
  const [multileg, setMultileg] = useState<MultiLeg[]>([]);
  const [side, setSide] = useState<'short' | 'long'>('short');
  const [wheel, setWheel] = useState<Wheel | null>(null);
  const [selV, setSelV] = useState<Vertical | null>(null);
  const [selI, setSelI] = useState<Income | null>(null);
  const [selM, setSelM] = useState<MultiLeg | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  const chainSide: 'call' | 'put' = mode === 'cash_secured_put' ? 'put' : mode === 'spreads' ? kind : 'call';
  const isML = mode === 'iron_condor' || mode === 'strangle' || mode === 'straddle';
  const hasSide = mode === 'strangle' || mode === 'straddle';

  const clearResults = () => { setVerticals([]); setIncome([]); setMultileg([]); setWheel(null); setSelV(null); setSelI(null); setSelM(null); };

  const loadChain = useCallback(async (sym: string, exp?: string) => {
    setLoading(true); setErr(''); clearResults();
    try {
      const r = await fetch(`/api/options/${sym}/chain${exp ? `?exp=${exp}` : ''}`);
      if (!r.ok) { setErr(`No options for ${sym}.`); setChain(null); return; }
      setChain(await r.json());
    } catch { setErr('Could not load chain.'); } finally { setLoading(false); }
  }, []);

  const formulate = useCallback(async () => {
    if (!chain) return;
    clearResults();
    if (mode === 'spreads') {
      const r = await fetch(`/api/options/${chain.symbol}/strategies?kind=${kind}&direction=${dir}&exp=${chain.expiration}&top=12`);
      if (r.ok) { const d = await r.json(); setVerticals(d.strategies || []); setSelV((d.strategies || [])[0] || null); }
    } else if (mode === 'cash_secured_put' || mode === 'covered_call') {
      const ik = mode === 'cash_secured_put' ? 'put' : 'call';
      const r = await fetch(`/api/options/${chain.symbol}/income?kind=${ik}&exp=${chain.expiration}&top=12`);
      if (r.ok) { const d = await r.json(); setIncome(d.income || []); setSelI((d.income || [])[0] || null); }
    } else if (mode === 'wheel') {
      const r = await fetch(`/api/options/${chain.symbol}/wheel`);
      if (r.ok) setWheel(await r.json());
    } else {
      const r = await fetch(`/api/options/${chain.symbol}/multileg?type=${mode}&side=${side}&exp=${chain.expiration}&top=8`);
      if (r.ok) { const d = await r.json(); setMultileg(d.strategies || []); setSelM((d.strategies || [])[0] || null); }
    }
  }, [chain, mode, kind, dir, side]);

  // generic payoff from legs: long=+intrinsic & -premium, short=-intrinsic & +premium
  const mlPL = (m: MultiLeg) => (S: number) => m.legs.reduce((acc, l) => {
    const intr = Math.max(l.kind === 'call' ? S - l.strike : l.strike - S, 0);
    const sign = l.action === 'long' ? 1 : -1;
    return acc + sign * intr + (l.action === 'short' ? l.premium : -l.premium);
  }, 0) * 100;

  // payoff functions
  const intr = (S: number, K: number, call: boolean) => Math.max(call ? S - K : K - S, 0);
  const vPL = (v: Vertical) => (S: number) => (intr(S, v.long_strike, v.kind === 'call') - intr(S, v.short_strike, v.kind === 'call') - v.net) * 100;
  const iPL = (t: Income, spot: number) => (S: number) =>
    t.type === 'cash_secured_put' ? (t.premium - intr(S, t.strike, false)) * 100
      : ((S - spot) + t.premium - intr(S, t.strike, true)) * 100;

  const MODES: { id: Mode; label: string }[] = [
    { id: 'cash_secured_put', label: '💵 Cash-Secured Puts' },
    { id: 'covered_call', label: '📈 Covered Calls' },
    { id: 'spreads', label: '↔ Spreads' },
    { id: 'iron_condor', label: '🦅 Iron Condor' },
    { id: 'strangle', label: '🤏 Strangle' },
    { id: 'straddle', label: '🎯 Straddle' },
    { id: 'wheel', label: '🎡 The Wheel' },
  ];

  return (
    <div style={{ minHeight: '100vh', background: '#000', color: GREEN, fontFamily: 'monospace', padding: '16px 16px 24px', maxWidth: 1040, margin: '0 auto' }}>
      <PageHeader title="📐 Options Engine">
        <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === 'Enter' && loadChain(symbol)} placeholder="ticker" style={{ ...box, width: 90 }} />
        <button onClick={() => loadChain(symbol)} style={{ ...box, cursor: 'pointer' }}>Load</button>
        {chain && (
          <select value={chain.expiration} onChange={(e) => loadChain(chain.symbol, e.target.value)} style={box}>
            {chain.expirations.map((e) => <option key={e} value={e}>{e}</option>)}
          </select>
        )}
        {chain && <span style={{ fontSize: 12, opacity: 0.8 }}>spot ${chain.spot.toFixed(2)} · r {(chain.rate * 100).toFixed(2)}%</span>}
      </PageHeader>

      <GreeksGlossary />

      {loading && <div style={{ opacity: 0.7 }}>loading…</div>}
      {err && <div style={{ opacity: 0.7 }}>{err}</div>}

      {chain && !loading && (
        <>
          <div style={{ display: 'flex', gap: 6, marginBottom: 6, flexWrap: 'wrap' }}>
            {MODES.map((m) => (
              <button key={m.id} onClick={() => { setMode(m.id); clearResults(); }}
                style={{ ...box, cursor: 'pointer', background: mode === m.id ? 'rgba(0,255,65,0.18)' : '#000' }}>{m.label}</button>
            ))}
          </div>

          <div style={{ fontSize: 12, lineHeight: 1.5, padding: '8px 10px', border: `1px solid ${DIM}`, borderRadius: 4, marginBottom: 12, background: 'rgba(0,255,65,0.03)' }}>
            <b style={{ color: GREEN }}>{STRATEGIES[mode].title}</b> — {STRATEGIES[mode].what}
          </div>

          <TVWidget title={`${chain.symbol} — technicals`} script="technical-analysis" height={300}
            config={{ symbol: chain.symbol, interval: '1D', showIntervalTabs: true, isTransparent: true }} />

          {mode === 'wheel' && (
            <div>
              <button onClick={formulate} style={{ ...box, cursor: 'pointer', marginBottom: 12 }}>🎡 Check the Wheel for {chain.symbol}</button>
              {wheel && (
                <div>
                  {/* phase banner */}
                  <div style={{ padding: '10px 12px', border: `1px solid ${wheel.phase === 'covered_call' ? GREEN : DIM}`, borderRadius: 4, marginBottom: 12, background: 'rgba(0,255,65,0.05)' }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: GREEN }}>
                      {wheel.phase === 'covered_call'
                        ? `You hold ${wheel.shares_held.toFixed(0)} shares of ${wheel.symbol} → COVERED-CALL phase`
                        : `No shares of ${wheel.symbol} → CASH-SECURED-PUT phase`}
                    </div>
                    <div style={{ fontSize: 12, marginTop: 4, opacity: 0.9 }}>→ {wheel.next_move}</div>
                  </div>

                  {/* the loop diagram */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 14 }}>
                    {wheel.steps.map((s, i) => {
                      const active = s.id === wheel.current_step;
                      return (
                        <div key={s.id} style={{ display: 'flex', gap: 8, padding: '8px 10px', borderRadius: 4, border: `1px solid ${active ? GREEN : DIM}`, background: active ? 'rgba(0,255,65,0.12)' : 'transparent', opacity: active ? 1 : 0.6 }}>
                          <span style={{ fontWeight: 700, color: active ? GREEN : DIM }}>{i + 1}</span>
                          <span style={{ fontSize: 12 }}>{s.text}</span>
                          {active && <span style={{ marginLeft: 'auto', fontSize: 11, color: GREEN, fontWeight: 700 }}>◀ YOU ARE HERE</span>}
                        </div>
                      );
                    })}
                  </div>

                  {/* suggestions */}
                  <div style={{ fontSize: 12, marginBottom: 6, opacity: 0.8 }}>
                    Suggested {wheel.phase === 'covered_call' ? 'covered calls' : 'cash-secured puts'} — exp {wheel.expiration}
                  </div>
                  {wheel.suggestions.length > 0 ? (
                    <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                      <thead><tr><th style={{ ...th, textAlign: 'left' }}>strike</th><th style={th}>prem</th><th style={th} title={METRICS.breakeven}>B/E</th><th style={th} title={METRICS.POP}>POP</th><th style={th} title={METRICS['annual yield']}>ann.yld</th><th style={th} title={METRICS.cushion}>cushion</th></tr></thead>
                      <tbody>{wheel.suggestions.map((s) => (
                        <tr key={s.strike}>
                          <td style={{ ...td, textAlign: 'left', fontWeight: 700 }}>{s.strike}</td>
                          <td style={{ ...td, color: GREEN }}>${s.premium.toFixed(2)}</td>
                          <td style={td}>{s.breakeven.toFixed(1)}</td>
                          <td style={td}>{(s.pop * 100).toFixed(0)}%</td>
                          <td style={td}>{(s.annual_yield * 100).toFixed(0)}%</td>
                          <td style={td}>{(s.cushion * 100).toFixed(1)}%</td>
                        </tr>))}</tbody>
                    </table>
                  ) : <div style={{ fontSize: 12, opacity: 0.6 }}>No liquid sells in the sellable range right now.</div>}
                </div>
              )}
            </div>
          )}

          {mode !== 'wheel' && (
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
            {/* chain */}
            <div style={{ flex: '1 1 330px', maxHeight: 440, overflowY: 'auto', border: `1px solid ${DIM}`, borderRadius: 4 }}>
              <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                <thead><tr>
                  <th style={th} title={GREEKS[0].plain}>Δ</th>
                  <th style={th} title={GREEKS[1].plain}>Θ</th>
                  <th style={th} title={GREEKS[4].plain}>IV</th>
                  <th style={th}>OI</th><th style={th}>Bid</th><th style={th}>Ask</th>
                  <th style={th}>{chainSide === 'call' ? 'CALLS' : 'PUTS'}</th>
                </tr></thead>
                <tbody>
                  {(chainSide === 'call' ? chain.calls : chain.puts).map((c) => {
                    const itm = chainSide === 'call' ? c.strike < chain.spot : c.strike > chain.spot;
                    return (
                      <tr key={c.strike} style={{ background: itm ? 'rgba(0,255,65,0.07)' : 'transparent' }}>
                        <td style={td}>{c.delta.toFixed(2)}</td><td style={td}>{c.theta.toFixed(2)}</td>
                        <td style={td}>{(c.iv * 100).toFixed(0)}%</td><td style={td}>{c.open_interest}</td>
                        <td style={{ ...td, color: GREEN }}>{c.bid.toFixed(2)}</td>
                        <td style={{ ...td, color: GREEN }}>{c.ask.toFixed(2)}</td>
                        <td style={{ ...td, fontWeight: 700, borderLeft: `1px solid ${DIM}` }}>{c.strike}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* strategy panel */}
            <div style={{ flex: '1 1 480px' }}>
              <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                {mode === 'spreads' && <>
                  {(['call', 'put'] as const).map((k) => <button key={k} onClick={() => setKind(k)} style={{ ...box, cursor: 'pointer', background: kind === k ? 'rgba(0,255,65,0.18)' : '#000' }}>{k}</button>)}
                  {(['bull', 'bear'] as const).map((d) => <button key={d} onClick={() => setDir(d)} style={{ ...box, cursor: 'pointer', background: dir === d ? 'rgba(0,255,65,0.18)' : '#000' }}>{d}</button>)}
                </>}
                {hasSide && (['short', 'long'] as const).map((s) => <button key={s} onClick={() => setSide(s)} style={{ ...box, cursor: 'pointer', background: side === s ? 'rgba(0,255,65,0.18)' : '#000' }}>{s}</button>)}
                <button onClick={formulate} style={{ ...box, cursor: 'pointer' }}>⚙ Formulate</button>
              </div>

              {selV && <div style={{ marginBottom: 10 }}><PayoffChart pl={vPL(selV)} spot={chain.spot} be={selV.breakeven} x0={Math.min(selV.long_strike, selV.short_strike) * 0.9} x1={Math.max(selV.long_strike, selV.short_strike) * 1.1} /></div>}
              {selI && <div style={{ marginBottom: 10 }}><PayoffChart pl={iPL(selI, chain.spot)} spot={chain.spot} be={selI.breakeven} x0={selI.strike * 0.8} x1={selI.strike * 1.2} /></div>}
              {selM && <div style={{ marginBottom: 10 }}><PayoffChart pl={mlPL(selM)} spot={chain.spot} be={selM.breakevens[0]} x0={Math.min(...selM.legs.map((l) => l.strike), chain.spot) * 0.88} x1={Math.max(...selM.legs.map((l) => l.strike), chain.spot) * 1.12} /></div>}

              {verticals.length > 0 && (
                <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                  <thead><tr><th style={{ ...th, textAlign: 'left' }}>spread</th><th style={th}>net</th><th style={th}>maxP</th><th style={th}>maxL</th><th style={th} title={METRICS.breakeven}>B/E</th><th style={th} title={METRICS['R:R']}>R:R</th><th style={th} title={METRICS.POP}>POP</th></tr></thead>
                  <tbody>{verticals.map((s) => (
                    <tr key={s.label} onClick={() => setSelV(s)} style={{ cursor: 'pointer', background: selV?.label === s.label ? 'rgba(0,255,65,0.12)' : 'transparent' }}>
                      <td style={{ ...td, textAlign: 'left' }}>{s.label}</td>
                      <td style={td}>{s.debit_credit === 'debit' ? `+${s.net.toFixed(2)}` : `-${(-s.net).toFixed(2)}`}</td>
                      <td style={{ ...td, color: GREEN }}>{s.max_profit.toFixed(2)}</td><td style={{ ...td, color: RED }}>{s.max_loss.toFixed(2)}</td>
                      <td style={td}>{s.breakeven.toFixed(1)}</td><td style={td}>{s.rr.toFixed(2)}</td><td style={td}>{(s.pop * 100).toFixed(0)}%</td>
                    </tr>))}</tbody>
                </table>
              )}

              {income.length > 0 && (
                <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                  <thead><tr><th style={{ ...th, textAlign: 'left' }}>strike</th><th style={th}>prem</th><th style={th} title={METRICS.breakeven}>B/E</th><th style={th} title={METRICS.POP}>POP</th><th style={th} title={METRICS['annual yield']}>ann.yld</th><th style={th} title={METRICS.cushion}>cushion</th><th style={th} title={GREEKS[1].plain}>Θ/day</th></tr></thead>
                  <tbody>{income.map((t) => (
                    <tr key={t.label} onClick={() => setSelI(t)} style={{ cursor: 'pointer', background: selI?.label === t.label ? 'rgba(0,255,65,0.12)' : 'transparent' }}>
                      <td style={{ ...td, textAlign: 'left' }}>{t.strike}</td>
                      <td style={{ ...td, color: GREEN }}>${t.premium.toFixed(2)}</td><td style={td}>{t.breakeven.toFixed(1)}</td>
                      <td style={td}>{(t.pop * 100).toFixed(0)}%</td><td style={td}>{(t.annual_yield * 100).toFixed(0)}%</td>
                      <td style={td}>{(t.cushion * 100).toFixed(1)}%</td><td style={{ ...td, color: GREEN }}>+{t.theta.toFixed(2)}</td>
                    </tr>))}</tbody>
                </table>
              )}

              {multileg.length > 0 && (
                <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                  <thead><tr><th style={{ ...th, textAlign: 'left' }}>structure</th><th style={th}>{multileg[0].side === 'credit' ? 'credit' : 'debit'}</th><th style={th}>maxP</th><th style={th}>maxL</th><th style={th} title={METRICS.breakeven}>breakevens</th><th style={th} title={METRICS.POP}>POP</th></tr></thead>
                  <tbody>{multileg.map((m) => (
                    <tr key={m.label} onClick={() => setSelM(m)} style={{ cursor: 'pointer', background: selM?.label === m.label ? 'rgba(0,255,65,0.12)' : 'transparent' }}>
                      <td style={{ ...td, textAlign: 'left' }}>{m.label}</td>
                      <td style={{ ...td, color: GREEN }}>{m.side === 'credit' ? `$${m.net.toFixed(2)}` : `$${(-m.net).toFixed(2)}`}</td>
                      <td style={{ ...td, color: GREEN }}>{m.max_profit.toFixed(2)}</td>
                      <td style={{ ...td, color: RED }}>{m.undefined_risk ? '∞*' : m.max_loss.toFixed(2)}</td>
                      <td style={td}>{m.breakevens.map((b) => b.toFixed(1)).join(' / ')}</td>
                      <td style={td}>{(m.pop * 100).toFixed(0)}%</td>
                    </tr>))}</tbody>
                </table>
              )}
              {isML && multileg.some((m) => m.undefined_risk) && <div style={{ fontSize: 10, opacity: 0.6, marginTop: 4 }}>∞* = undefined/large risk (naked short) — manage carefully</div>}
            </div>
          </div>
          )}
        </>
      )}
    </div>
  );
}
