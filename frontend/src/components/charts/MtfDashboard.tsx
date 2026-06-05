/**
 * MtfDashboard — a condensed multi-timeframe read for the current symbol.
 *
 * Replaces the TradingView "4-chart layout" / higher-timeframe overlay with a
 * single compact panel: for each timeframe (15m / 1H / 1D / 1W) it shows trend
 * (price vs 20-period MA), RSI(14), and last price. TA stays server-side — for
 * each timeframe we pull the bars (klineApi) and compute via the indicator
 * engine (/api/indicator/compute), so values match the chart's own indicators.
 */

import { useEffect, useState } from 'react';

import { fetchKLineData, type Resolution } from '../../lib/klineApi';
import { computeIndicator, type IndicatorSpec } from '../../lib/indicatorApi';

const GREEN = '#00ff41';
const RED = '#ff3b3b';
const GREEN_DIM = 'rgba(0,255,65,0.3)';
const AMBER = '#ffcc00';

const TFS: { res: Resolution; label: string }[] = [
  { res: '15', label: '15m' },
  { res: '60', label: '1H' },
  { res: 'D', label: '1D' },
  { res: 'W', label: '1W' },
];

// One spec, computed per timeframe: RSI(14) + SMA(20) off close.
const MTF_SPEC: IndicatorSpec = {
  name: 'MTF',
  pane: 'separate',
  steps: [
    { id: 'c', op: 'series', ref: 'close' },
    { id: 'rsi', op: 'rsi', input: 'c', period: 14 },
    { id: 'ma', op: 'sma', input: 'c', period: 20 },
  ],
  plots: [
    { step: 'rsi', label: 'RSI' },
    { step: 'ma', label: 'MA20' },
  ],
};

interface Row {
  label: string;
  status: 'loading' | 'ok' | 'empty' | 'err';
  trend?: 'up' | 'down' | 'flat';
  rsi?: number;
  price?: number;
}

function lastValue(points: { time: number; value: number }[]): number | undefined {
  return points.length ? points[points.length - 1].value : undefined;
}

const MtfDashboard: React.FC<{ symbol: string }> = ({ symbol }) => {
  const [rows, setRows] = useState<Row[]>(TFS.map((t) => ({ label: t.label, status: 'loading' })));

  useEffect(() => {
    const controller = new AbortController();
    setRows(TFS.map((t) => ({ label: t.label, status: 'loading' })));

    TFS.forEach((tf, i) => {
      fetchKLineData(symbol, tf.res, controller.signal)
        .then(async (bars) => {
          if (controller.signal.aborted) return;
          if (!bars.length) {
            update(i, { label: tf.label, status: 'empty' });
            return;
          }
          const result = await computeIndicator(MTF_SPEC, bars, controller.signal);
          if (controller.signal.aborted) return;
          const rsiPlot = result.plots.find((p) => p.step === 'rsi');
          const maPlot = result.plots.find((p) => p.step === 'ma');
          const rsi = rsiPlot ? lastValue(rsiPlot.points) : undefined;
          const ma = maPlot ? lastValue(maPlot.points) : undefined;
          const price = bars[bars.length - 1].close;
          let trend: Row['trend'] = 'flat';
          if (ma != null) trend = price > ma ? 'up' : price < ma ? 'down' : 'flat';
          update(i, { label: tf.label, status: 'ok', trend, rsi, price });
        })
        .catch(() => {
          if (!controller.signal.aborted) update(i, { label: tf.label, status: 'err' });
        });
    });

    function update(i: number, row: Row) {
      setRows((prev) => prev.map((r, idx) => (idx === i ? row : r)));
    }

    return () => controller.abort();
  }, [symbol]);

  const cell: React.CSSProperties = {
    padding: '4px 10px',
    fontFamily: 'monospace',
    fontSize: 12,
    textAlign: 'center',
  };

  return (
    <div
      style={{
        border: `1px solid ${GREEN_DIM}`,
        borderRadius: 4,
        background: 'rgba(0,255,65,0.03)',
        display: 'grid',
        gridTemplateColumns: `repeat(${TFS.length}, 1fr)`,
        overflow: 'hidden',
      }}
    >
      {rows.map((r) => {
        const trendColor = r.trend === 'up' ? GREEN : r.trend === 'down' ? RED : GREEN_DIM;
        const trendChar = r.trend === 'up' ? '▲' : r.trend === 'down' ? '▼' : '—';
        const rsiColor =
          r.rsi == null ? GREEN_DIM : r.rsi >= 70 ? RED : r.rsi <= 30 ? GREEN : AMBER;
        return (
          <div
            key={r.label}
            style={{ borderRight: `1px solid ${GREEN_DIM}`, padding: '6px 0' }}
          >
            <div style={{ ...cell, color: GREEN, fontWeight: 700 }}>{r.label}</div>
            {r.status === 'ok' ? (
              <>
                <div style={{ ...cell, color: trendColor, fontSize: 16 }}>{trendChar}</div>
                <div style={{ ...cell, color: rsiColor }}>
                  RSI {r.rsi != null ? r.rsi.toFixed(0) : '—'}
                </div>
                <div style={{ ...cell, color: GREEN_DIM }}>
                  {r.price != null ? r.price.toFixed(2) : '—'}
                </div>
              </>
            ) : (
              <div style={{ ...cell, color: r.status === 'err' ? RED : GREEN_DIM }}>
                {r.status === 'loading' ? '…' : r.status === 'empty' ? 'no data' : '⚠'}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};

export default MtfDashboard;
