/**
 * ScreenerPanel — run a price condition across a watchlist from the chart tab.
 *
 * v1 screens on close price (close >/< value, or crossing it); the backend accepts
 * any indicator spec, so spec-driven screens can be added later. Reuses the indicator
 * engine over each symbol's bars; results come back matches-first.
 */

import { useState } from 'react';

import { screenIndicator, type ScreenRow } from '../../lib/indicatorApi';
import { priceSpec, type AlertOp } from '../../lib/alertApi';

const GREEN = '#00ff41';
const RED = '#ff3b3b';
const GREEN_DIM = 'rgba(0,255,65,0.3)';

const OPS: { value: AlertOp; label: string }[] = [
  { value: 'gt', label: 'price >' },
  { value: 'lt', label: 'price <' },
  { value: 'cross_up', label: 'crosses ↑' },
  { value: 'cross_down', label: 'crosses ↓' },
];

const ctl: React.CSSProperties = {
  background: '#000',
  color: GREEN,
  border: `1px solid ${GREEN_DIM}`,
  fontFamily: 'monospace',
  fontSize: 12,
  padding: '4px 8px',
  borderRadius: 4,
};

const ScreenerPanel: React.FC<{ symbol: string }> = ({ symbol }) => {
  const [symbols, setSymbols] = useState(
    `${symbol.toUpperCase()}, SPY, QQQ, NVDA, AAPL, MSFT, TSLA, AMD`,
  );
  const [op, setOp] = useState<AlertOp>('gt');
  const [value, setValue] = useState('');
  const [rows, setRows] = useState<ScreenRow[]>([]);
  const [status, setStatus] = useState<'idle' | 'running' | 'done' | 'err'>('idle');

  const run = (e: React.FormEvent) => {
    e.preventDefault();
    const v = Number(value);
    if (!Number.isFinite(v)) {
      setStatus('err');
      return;
    }
    const list = symbols.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean);
    if (!list.length) return;
    setStatus('running');
    screenIndicator(list, priceSpec('screen'), 'c', op, v)
      .then((res) => {
        setRows(res);
        setStatus('done');
      })
      .catch(() => setStatus('err'));
  };

  return (
    <div
      style={{
        border: `1px solid ${GREEN_DIM}`,
        borderRadius: 4,
        padding: 8,
        background: 'rgba(0,255,65,0.03)',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <form onSubmit={run} style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ color: GREEN_DIM, fontFamily: 'monospace', fontSize: 11 }}>screen</span>
        <input
          aria-label="Watchlist"
          value={symbols}
          onChange={(e) => setSymbols(e.target.value)}
          placeholder="AAPL, MSFT, …"
          style={{ ...ctl, flex: 1, minWidth: 220, textTransform: 'uppercase' }}
        />
        <select aria-label="Condition" value={op} onChange={(e) => setOp(e.target.value as AlertOp)} style={ctl}>
          {OPS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <input
          aria-label="Price"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="price"
          inputMode="decimal"
          style={{ ...ctl, width: 90 }}
        />
        <button type="submit" style={{ ...ctl, cursor: 'pointer' }} disabled={status === 'running'}>
          {status === 'running' ? 'Scanning…' : 'Run'}
        </button>
      </form>

      {status === 'err' && (
        <div style={{ color: RED, fontFamily: 'monospace', fontSize: 11 }}>Enter a numeric price + symbols.</div>
      )}

      {rows.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr auto', gap: '2px 12px', fontFamily: 'monospace', fontSize: 12 }}>
          {rows.map((r) => (
            <div key={r.symbol} style={{ display: 'contents' }}>
              <span style={{ color: r.matched ? GREEN : GREEN_DIM, fontWeight: r.matched ? 700 : 400 }}>
                {r.matched ? '✓' : '·'} {r.symbol}
              </span>
              <span style={{ color: GREEN_DIM }}>{r.error ? r.error : ''}</span>
              <span style={{ color: GREEN, textAlign: 'right' }}>{r.value != null ? r.value : '—'}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default ScreenerPanel;
