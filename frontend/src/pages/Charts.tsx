/**
 * Charts — the full-width charting tab, rebuilt on KLineChart (Apache-2.0).
 *
 * Phase 2 of the Charts rebuild: the old Lightweight-Charts ChartWorkspace is
 * swapped out for KLineChart (candles + volume, built-in MA/BOLL/MACD/RSI/VOL
 * indicators, and interactive drawing tools). It's fed by the EXISTING backend
 * OHLCV feed (the UDF datafeed in backend/udf_routes.py) via lib/klineApi — no
 * backend change. ChartWorkspace lives on for PortfolioScan.
 *
 * Convention kept: a centered <PageHeader> (title "📉 Charts") carries the page
 * controls (symbol input + timeframe selector); the App shell reserves the fixed
 * chrome clearance, so this page adds no top/bottom padding to dodge it.
 */

import { useState } from 'react';

import KLineChartView from '../components/charts/KLineChartView';
import PageHeader from '../components/PageHeader';
import { TIMEFRAMES, type Resolution } from '../lib/klineApi';

const GREEN = '#00ff41';
const GREEN_DIM = 'rgba(0,255,65,0.3)';

const inputStyle: React.CSSProperties = {
  background: '#000',
  color: GREEN,
  border: `1px solid ${GREEN_DIM}`,
  fontFamily: 'monospace',
  fontSize: 13,
  padding: '5px 10px',
  borderRadius: 4,
  width: 110,
  textTransform: 'uppercase',
};

function tfBtnStyle(active: boolean): React.CSSProperties {
  return {
    background: active ? 'rgba(0,255,65,0.18)' : '#000',
    color: GREEN,
    border: `1px solid ${active ? GREEN : GREEN_DIM}`,
    fontFamily: 'monospace',
    fontSize: 12,
    padding: '5px 12px',
    cursor: 'pointer',
    borderRadius: 4,
  };
}

const Charts: React.FC = () => {
  const [symbol, setSymbol] = useState('SPY');
  const [resolution, setResolution] = useState<Resolution>('D');
  const [draft, setDraft] = useState('SPY');

  const submitSymbol = (e: React.FormEvent) => {
    e.preventDefault();
    const next = draft.trim().toUpperCase();
    if (next) setSymbol(next);
  };

  return (
    <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 pt-2 pb-8">
      <PageHeader title="📉 Charts" subtitle={`${symbol} · KLineChart`}>
        <form onSubmit={submitSymbol} style={{ display: 'flex', gap: 6 }}>
          <input
            aria-label="Symbol"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="SYMBOL"
            style={inputStyle}
          />
          <button type="submit" style={tfBtnStyle(false)}>
            Load
          </button>
        </form>

        <div style={{ display: 'flex', gap: 4 }}>
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf.value}
              type="button"
              onClick={() => setResolution(tf.value)}
              style={tfBtnStyle(resolution === tf.value)}
            >
              {tf.label}
            </button>
          ))}
        </div>
      </PageHeader>

      <KLineChartView symbol={symbol} resolution={resolution} />
    </div>
  );
};

export default Charts;
