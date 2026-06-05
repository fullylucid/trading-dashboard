/**
 * AlertsPanel — create + manage chart-condition price alerts for a symbol.
 *
 * v1 covers price-level alerts (close >/< value, or crossing it); the backend
 * supports arbitrary indicator specs, so richer alerts can be added later. Saved
 * alerts are evaluated server-side on a schedule and delivered via Telegram.
 */

import { useCallback, useEffect, useState } from 'react';

import {
  createAlert,
  deleteAlert,
  listAlerts,
  priceSpec,
  type AlertOp,
  type ChartAlert,
} from '../../lib/alertApi';

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

const AlertsPanel: React.FC<{ symbol: string }> = ({ symbol }) => {
  const [alerts, setAlerts] = useState<ChartAlert[]>([]);
  const [op, setOp] = useState<AlertOp>('gt');
  const [value, setValue] = useState('');
  const [msg, setMsg] = useState('');

  const refresh = useCallback(() => {
    listAlerts()
      .then((all) => setAlerts(all.filter((a) => a.symbol === symbol.toUpperCase())))
      .catch(() => undefined);
  }, [symbol]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const add = (e: React.FormEvent) => {
    e.preventDefault();
    const v = Number(value);
    if (!Number.isFinite(v)) {
      setMsg('Enter a numeric price');
      return;
    }
    createAlert({ symbol: symbol.toUpperCase(), spec: priceSpec(symbol), plot_step: 'c', op, value: v })
      .then(() => {
        setMsg(`Alert added: ${symbol} ${op} ${v}`);
        setValue('');
        refresh();
      })
      .catch((err) => setMsg(err?.response?.data?.detail || err?.message || 'Failed to add alert'));
  };

  const remove = (id: string) => {
    deleteAlert(id).then(() => refresh()).catch(() => undefined);
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
      <form onSubmit={add} style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ color: GREEN_DIM, fontFamily: 'monospace', fontSize: 11 }}>alert {symbol}</span>
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
        <button type="submit" style={{ ...ctl, cursor: 'pointer' }}>
          ＋ Add
        </button>
        <span style={{ color: GREEN_DIM, fontFamily: 'monospace', fontSize: 11 }}>→ Telegram</span>
      </form>

      {msg && <div style={{ color: GREEN_DIM, fontFamily: 'monospace', fontSize: 11 }}>{msg}</div>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {alerts.length === 0 ? (
          <div style={{ color: GREEN_DIM, fontFamily: 'monospace', fontSize: 11 }}>no alerts for {symbol}</div>
        ) : (
          alerts.map((a) => (
            <div
              key={a.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                fontFamily: 'monospace',
                fontSize: 12,
                color: GREEN,
              }}
            >
              <span>
                {OPS.find((o) => o.value === a.op)?.label ?? a.op} {a.value}
              </span>
              {a.last_fired_at && <span style={{ color: GREEN_DIM, fontSize: 11 }}>fired</span>}
              <button
                type="button"
                aria-label={`Delete alert ${a.id}`}
                onClick={() => remove(a.id)}
                style={{ background: 'transparent', color: RED, border: 'none', cursor: 'pointer', fontSize: 13 }}
              >
                ×
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default AlertsPanel;
