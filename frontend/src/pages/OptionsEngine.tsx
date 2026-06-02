import { useState, useCallback } from 'react';

const GREEN = '#00ff41';
const RED = '#ff5555';
const DIM = 'rgba(0,255,65,0.55)';

type Contract = {
  strike: number; kind: string; bid: number; ask: number; mid: number;
  volume: number; open_interest: number; iv: number; delta: number; prob_itm: number;
};
type Chain = {
  symbol: string; spot: number; rate: number; expiration: string;
  expirations: string[]; calls: Contract[]; puts: Contract[];
};
type Strategy = {
  label: string; kind: string; direction: string; debit_credit: string; net: number;
  long_strike: number; short_strike: number; width: number; max_profit: number;
  max_loss: number; breakeven: number; rr: number; pop: number; score: number;
};

const box: React.CSSProperties = {
  background: '#000', color: GREEN, border: `1px solid ${DIM}`, borderRadius: 4,
  fontFamily: 'monospace', padding: '4px 8px',
};

// ---- payoff diagram: generic vertical P/L = intrinsic(long)-intrinsic(short)-net ----
function Payoff({ s, spot }: { s: Strategy; spot: number }) {
  const iv = (S: number, K: number, call: boolean) => Math.max(call ? S - K : K - S, 0);
  const call = s.kind === 'call';
  const lo = Math.min(s.long_strike, s.short_strike), hi = Math.max(s.long_strike, s.short_strike);
  const x0 = Math.max(0, lo - (hi - lo) * 1.5), x1 = hi + (hi - lo) * 1.5;
  const pts: [number, number][] = [];
  const N = 80;
  for (let i = 0; i <= N; i++) {
    const S = x0 + (x1 - x0) * (i / N);
    const pl = (iv(S, s.long_strike, call) - iv(S, s.short_strike, call) - s.net) * 100;
    pts.push([S, pl]);
  }
  const W = 460, H = 180, pad = 28;
  const ys = pts.map((p) => p[1]);
  const ymin = Math.min(...ys, -1), ymax = Math.max(...ys, 1);
  const sx = (x: number) => pad + ((x - x0) / (x1 - x0)) * (W - 2 * pad);
  const sy = (y: number) => H - pad - ((y - ymin) / (ymax - ymin)) * (H - 2 * pad);
  const path = pts.map((p, i) => `${i ? 'L' : 'M'}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join(' ');
  return (
    <svg width={W} height={H} style={{ border: `1px solid ${DIM}`, borderRadius: 4, background: '#001000' }}>
      <line x1={pad} y1={sy(0)} x2={W - pad} y2={sy(0)} stroke={DIM} strokeDasharray="3 3" />
      <line x1={sx(spot)} y1={pad} x2={sx(spot)} y2={H - pad} stroke="#7fdfff" strokeDasharray="2 4" />
      <line x1={sx(s.breakeven)} y1={pad} x2={sx(s.breakeven)} y2={H - pad} stroke="#ffcc00" strokeDasharray="2 4" />
      <path d={path} fill="none" stroke={GREEN} strokeWidth={2} />
      <text x={sx(spot)} y={H - 8} fill="#7fdfff" fontSize={9} textAnchor="middle">spot {spot.toFixed(0)}</text>
      <text x={sx(s.breakeven)} y={pad - 4} fill="#ffcc00" fontSize={9} textAnchor="middle">B/E {s.breakeven.toFixed(1)}</text>
      <text x={pad} y={sy(ymax) + 9} fill={GREEN} fontSize={9}>+{(ymax).toFixed(0)}</text>
      <text x={pad} y={sy(ymin) - 2} fill={RED} fontSize={9}>{(ymin).toFixed(0)}</text>
    </svg>
  );
}

function ChainSide({ rows, spot, side }: { rows: Contract[]; spot: number; side: 'call' | 'put' }) {
  const itm = (c: Contract) => (side === 'call' ? c.strike < spot : c.strike > spot);
  return (
    <>
      {rows.map((c) => (
        <tr key={side + c.strike} style={{ background: itm(c) ? 'rgba(0,255,65,0.07)' : 'transparent' }}>
          <td style={td}>{c.delta.toFixed(2)}</td>
          <td style={td}>{(c.iv * 100).toFixed(0)}%</td>
          <td style={td}>{c.open_interest}</td>
          <td style={{ ...td, color: GREEN }}>{c.bid.toFixed(2)}</td>
          <td style={{ ...td, color: GREEN }}>{c.ask.toFixed(2)}</td>
          <td style={{ ...td, fontWeight: 700, borderLeft: `1px solid ${DIM}`, borderRight: `1px solid ${DIM}` }}>{c.strike}</td>
        </tr>
      ))}
    </>
  );
}
const td: React.CSSProperties = { padding: '2px 6px', fontSize: 11, textAlign: 'right', whiteSpace: 'nowrap' };
const th: React.CSSProperties = { ...td, color: DIM, fontWeight: 400, borderBottom: `1px solid ${DIM}` };

export default function OptionsEngine() {
  const [symbol, setSymbol] = useState('NOW');
  const [chain, setChain] = useState<Chain | null>(null);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [sel, setSel] = useState<Strategy | null>(null);
  const [kind, setKind] = useState<'call' | 'put'>('call');
  const [dir, setDir] = useState<'bull' | 'bear'>('bull');
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  const loadChain = useCallback(async (sym: string, exp?: string) => {
    setLoading(true); setErr(''); setSel(null);
    try {
      const r = await fetch(`/api/options/${sym}/chain${exp ? `?exp=${exp}` : ''}`);
      if (!r.ok) { setErr(`No options for ${sym}.`); setChain(null); return; }
      setChain(await r.json());
    } catch { setErr('Could not load chain.'); }
    finally { setLoading(false); }
  }, []);

  const loadStrategies = useCallback(async () => {
    if (!chain) return;
    const r = await fetch(`/api/options/${chain.symbol}/strategies?kind=${kind}&direction=${dir}&exp=${chain.expiration}&top=12`);
    if (r.ok) { const d = await r.json(); setStrategies(d.strategies || []); setSel((d.strategies || [])[0] || null); }
  }, [chain, kind, dir]);

  return (
    <div style={{ minHeight: '100vh', background: '#000', color: GREEN, fontFamily: 'monospace', padding: '60px 16px 40px', maxWidth: 1040, margin: '0 auto' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 14 }}>
        <h1 style={{ fontSize: 20, margin: 0, textShadow: `0 0 8px ${GREEN}` }}>📐 Options Engine</h1>
        <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === 'Enter' && loadChain(symbol)} placeholder="ticker" style={{ ...box, width: 90 }} />
        <button onClick={() => loadChain(symbol)} style={{ ...box, cursor: 'pointer' }}>Load</button>
        {chain && (
          <select value={chain.expiration} onChange={(e) => loadChain(chain.symbol, e.target.value)} style={box}>
            {chain.expirations.map((e) => <option key={e} value={e}>{e}</option>)}
          </select>
        )}
        {chain && <span style={{ fontSize: 12, opacity: 0.8 }}>spot ${chain.spot.toFixed(2)} · r {(chain.rate * 100).toFixed(2)}%</span>}
      </div>

      {loading && <div style={{ opacity: 0.7 }}>loading…</div>}
      {err && <div style={{ opacity: 0.7 }}>{err}</div>}

      {chain && !loading && (
        <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 360px', maxHeight: 460, overflowY: 'auto', border: `1px solid ${DIM}`, borderRadius: 4 }}>
            <table style={{ borderCollapse: 'collapse', width: '100%' }}>
              <thead><tr><th style={th}>Δ</th><th style={th}>IV</th><th style={th}>OI</th><th style={th}>Bid</th><th style={th}>Ask</th><th style={th}>{kind === 'call' ? 'CALLS ▾' : 'PUTS ▾'}</th></tr></thead>
              <tbody><ChainSide rows={kind === 'call' ? chain.calls : chain.puts} spot={chain.spot} side={kind} /></tbody>
            </table>
          </div>

          <div style={{ flex: '1 1 480px' }}>
            <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
              {(['call', 'put'] as const).map((k) => <button key={k} onClick={() => setKind(k)} style={{ ...box, cursor: 'pointer', background: kind === k ? 'rgba(0,255,65,0.18)' : '#000' }}>{k}</button>)}
              {(['bull', 'bear'] as const).map((d) => <button key={d} onClick={() => setDir(d)} style={{ ...box, cursor: 'pointer', background: dir === d ? 'rgba(0,255,65,0.18)' : '#000' }}>{d}</button>)}
              <button onClick={loadStrategies} style={{ ...box, cursor: 'pointer' }}>⚙ Formulate spreads</button>
            </div>

            {sel && <div style={{ marginBottom: 10 }}><Payoff s={sel} spot={chain.spot} /></div>}

            {strategies.length > 0 && (
              <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                <thead><tr><th style={{ ...th, textAlign: 'left' }}>spread</th><th style={th}>net</th><th style={th}>maxP</th><th style={th}>maxL</th><th style={th}>B/E</th><th style={th}>R:R</th><th style={th}>POP</th></tr></thead>
                <tbody>
                  {strategies.map((s) => (
                    <tr key={s.label} onClick={() => setSel(s)} style={{ cursor: 'pointer', background: sel?.label === s.label ? 'rgba(0,255,65,0.12)' : 'transparent' }}>
                      <td style={{ ...td, textAlign: 'left' }}>{s.label}</td>
                      <td style={td}>{s.debit_credit === 'debit' ? `+${s.net.toFixed(2)}` : `-${(-s.net).toFixed(2)}`}</td>
                      <td style={{ ...td, color: GREEN }}>{s.max_profit.toFixed(2)}</td>
                      <td style={{ ...td, color: RED }}>{s.max_loss.toFixed(2)}</td>
                      <td style={td}>{s.breakeven.toFixed(1)}</td>
                      <td style={td}>{s.rr.toFixed(2)}</td>
                      <td style={td}>{(s.pop * 100).toFixed(0)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
