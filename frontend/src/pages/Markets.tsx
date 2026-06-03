import { useState } from 'react';
import TVWidget from '../components/TVWidget';
import PageHeader from '../components/PageHeader';

const GREEN = '#00ff41';
const DIM = 'rgba(0,255,65,0.55)';

// A sensible default watchlist (majors + a few of Schyler's names); editable up top.
const DEFAULT_SYMBOLS = ['NASDAQ:AMD', 'NASDAQ:NVDA', 'AMEX:SPY', 'NASDAQ:QQQ', 'NASDAQ:AAPL', 'NASDAQ:TSLA', 'NASDAQ:COIN', 'NYSE:SOFI'];

export default function Markets() {
  const [symbol, setSymbol] = useState('NASDAQ:AMD');

  const wrap: React.CSSProperties = { minHeight: '100vh', background: '#000', color: GREEN, fontFamily: 'monospace', padding: '16px 16px 24px', maxWidth: 1040, margin: '0 auto' };

  return (
    <div style={wrap}>
      <PageHeader title="🌐 Markets" subtitle="Live market widgets (TradingView) — overview, heatmap, calendar, news." />

      {/* scrolling ticker */}
      <TVWidget
        script="ticker-tape"
        height={48}
        config={{
          symbols: DEFAULT_SYMBOLS.map((s) => ({ proName: s, title: s.split(':')[1] })),
          showSymbolLogo: true, isTransparent: true, displayMode: 'adaptive',
        }}
      />

      {/* symbol picker drives the per-symbol widgets below */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', margin: '4px 0 12px' }}>
        <span style={{ fontSize: 11, color: DIM }}>focus:</span>
        {DEFAULT_SYMBOLS.map((s) => (
          <button key={s} onClick={() => setSymbol(s)}
            style={{ background: symbol === s ? 'rgba(0,255,65,0.15)' : '#000', color: symbol === s ? GREEN : DIM, border: `1px solid ${DIM}`, borderRadius: 4, fontFamily: 'monospace', fontSize: 11, padding: '3px 9px', cursor: 'pointer' }}>
            {s.split(':')[1]}
          </button>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        <div style={{ flex: '2 1 460px', minWidth: 300 }}>
          <TVWidget title={`${symbol.split(':')[1]} — overview`} script="symbol-overview" height={360}
            config={{ symbols: [[symbol, `${symbol}|12M`]], chartOnly: false, isTransparent: true, autosize: true, showVolume: true, fontColor: 'rgba(0,255,65,0.7)', gridLineColor: 'rgba(0,255,65,0.06)' }} />
        </div>
        <div style={{ flex: '1 1 260px', minWidth: 240 }}>
          <TVWidget title="technicals" script="technical-analysis" height={360}
            config={{ symbol, interval: '1D', showIntervalTabs: true, isTransparent: true }} />
        </div>
      </div>

      <TVWidget title="market overview" script="market-overview" height={420}
        config={{
          showChart: true, isTransparent: true, dateRange: '12M', showSymbolLogo: true, showFloatingTooltip: true,
          tabs: [
            { title: 'Indices', symbols: [{ s: 'AMEX:SPY', d: 'S&P 500' }, { s: 'NASDAQ:QQQ', d: 'Nasdaq 100' }, { s: 'AMEX:DIA', d: 'Dow' }, { s: 'AMEX:IWM', d: 'Russell 2000' }] },
            { title: 'Tech', symbols: [{ s: 'NASDAQ:AMD' }, { s: 'NASDAQ:NVDA' }, { s: 'NASDAQ:AAPL' }, { s: 'NASDAQ:MSFT' }, { s: 'NASDAQ:TSLA' }] },
            { title: 'Crypto', symbols: [{ s: 'BITSTAMP:BTCUSD', d: 'Bitcoin' }, { s: 'BITSTAMP:ETHUSD', d: 'Ethereum' }, { s: 'NASDAQ:COIN' }] },
          ],
        }} />

      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 420px', minWidth: 300 }}>
          <TVWidget title="S&P 500 heatmap" script="stock-heatmap" height={460}
            config={{ dataSource: 'SPX500', grouping: 'sector', blockSize: 'market_cap_basic', blockColor: 'change', hasTopBar: false, isZoomEnabled: true, hasSymbolTooltip: true, isDataSetEnabled: false }} />
        </div>
        <div style={{ flex: '1 1 320px', minWidth: 280 }}>
          <TVWidget title="economic calendar" script="events" height={460}
            config={{ isTransparent: true, countryFilter: 'us', importanceFilter: '0,1' }} />
        </div>
      </div>

      <TVWidget title="top stories" script="timeline" height={420}
        config={{ feedMode: 'market', market: 'stock', isTransparent: true, displayMode: 'regular' }} />

      <TVWidget title="screener" script="screener" height={500}
        config={{ defaultColumn: 'overview', defaultScreen: 'most_capitalized', market: 'america', showToolbar: true, isTransparent: true }} />
    </div>
  );
}
