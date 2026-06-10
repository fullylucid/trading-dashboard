import './App.css';
import { useState, useEffect, useRef } from 'react';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import HomeDashboard from './pages/HomeDashboard';
import PortfolioScan from './pages/PortfolioScan';
import SectorRotation from './pages/SectorRotation';
import Charts from './pages/Charts';
import ChartingScout from './pages/ChartingScout';
import CrackADawn from './pages/CrackADawn';
import OptionsEngine from './pages/OptionsEngine';
import FinTube from './pages/FinTube';
import HydraHQ from './pages/HydraHQ';
import RoomDetail from './pages/hq/RoomDetail';
import HeadDetail from './pages/hq/HeadDetail';
import ConsoleView from './pages/hq/ConsoleView';
import ConsoleDeck from './pages/hq/ConsoleDeck';
import MemoryBrowser from './pages/hq/MemoryBrowser';
import Markets from './pages/Markets';
import SystemBanner from './pages/SystemMonitor';
import TVWidget from './components/TVWidget';
import MessengerWidget from './components/MessengerWidget/MessengerWidget';
import { CHROME_TOP, CHROME_BOTTOM } from './layout';

const ROUTES: { to: string; label: string; end?: boolean }[] = [
  { to: '/', label: '📈 Dashboard', end: true },
  { to: '/hq', label: '🛰️ Hydra HQ' },
  { to: '/crack-a-dawn', label: '🌅 Crack-a-Dawn' },
  { to: '/options', label: '📐 Options Engine' },
  { to: '/fintube', label: '📺 FinTube' },
  { to: '/charts', label: '📉 Charts' },
  { to: '/charting-scout', label: '🔬 Chart Lab' },
  { to: '/markets', label: '🌐 Markets' },
  { to: '/portfolio-scan', label: '📊 Portfolio Scan' },
  { to: '/sector-rotation', label: '🔄 Sector Rotation' },
];

function NavMenu() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const btnStyle: React.CSSProperties = {
    background: '#000',
    color: '#00ff41',
    border: '1px solid #00ff41',
    fontFamily: 'monospace',
    fontSize: 18,
    lineHeight: 1,
    padding: '6px 12px',
    cursor: 'pointer',
    boxShadow: '0 0 10px rgba(0, 255, 65, 0.4)',
    borderRadius: 4,
  };

  const menuStyle: React.CSSProperties = {
    marginTop: 6,
    background: '#000',
    border: '1px solid #00ff41',
    borderRadius: 4,
    minWidth: 200,
    boxShadow: '0 0 12px rgba(0, 255, 65, 0.5)',
    padding: 4,
    fontFamily: 'monospace',
  };

  const itemBase: React.CSSProperties = {
    display: 'block',
    padding: '8px 12px',
    color: '#00ff41',
    textDecoration: 'none',
    fontSize: 14,
    borderRadius: 2,
  };

  return (
    <div
      ref={ref}
      style={{
        position: 'fixed',
        top: 12,
        left: 12,
        zIndex: 2000,
        fontFamily: 'monospace',
      }}
    >
      <button
        type="button"
        aria-label="Open navigation menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        style={btnStyle}
      >
        ☰
      </button>
      {open && (
        <div role="menu" style={menuStyle}>
          <div
            style={{
              padding: '6px 10px',
              color: '#00ff41',
              fontSize: 12,
              opacity: 0.7,
              borderBottom: '1px solid rgba(0,255,65,0.3)',
              marginBottom: 4,
            }}
          >
            🕷️ Tradeskeebot
          </div>
          {ROUTES.map((r) => (
            <NavLink
              key={r.to}
              to={r.to}
              end={r.end}
              onClick={() => setOpen(false)}
              style={({ isActive }) => ({
                ...itemBase,
                background: isActive ? 'rgba(0,255,65,0.15)' : 'transparent',
                fontWeight: isActive ? 700 : 400,
              })}
            >
              {r.label}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
}

const TICKER_SYMBOLS = ['AMEX:SPY', 'NASDAQ:QQQ', 'NASDAQ:AMD', 'NASDAQ:NVDA', 'NASDAQ:AAPL', 'NASDAQ:TSLA', 'NASDAQ:COIN', 'NYSE:SOFI', 'BITSTAMP:BTCUSD'];

function GlobalTicker() {
  return (
    <div style={{ position: 'fixed', left: 0, right: 0, bottom: 0, zIndex: 1400, background: '#000', borderTop: '1px solid rgba(0,255,65,0.3)' }}>
      <TVWidget
        bare
        script="ticker-tape"
        height={42}
        config={{
          symbols: TICKER_SYMBOLS.map((s) => ({ proName: s, title: s.split(':')[1] })),
          showSymbolLogo: true, isTransparent: true, displayMode: 'compact',
        }}
      />
    </div>
  );
}

// When served from the dedicated HQ subdomain (hq.shmaptech.com), the root lands on the
// fleet command center instead of the trading home — every other route stays reachable, and
// /hq still works on trade.shmaptech.com. Same-origin nginx serves the identical SPA under
// both hostnames; the host is fixed for the session, so we read it once.
const IS_HQ_HOST =
  typeof window !== 'undefined' && window.location.hostname.startsWith('hq.');

function App() {
  return (
    <BrowserRouter>
      <div className="app min-h-screen bg-gray-900 text-white">
        <SystemBanner />
        <NavMenu />
        {/* Reserve clearance for the fixed chrome (top banner / ☰ button, bottom ticker)
            so no routed page slides under it. Single-sourced in ./layout. */}
        <main style={{ paddingTop: CHROME_TOP, paddingBottom: CHROME_BOTTOM }}>
          <Routes>
            <Route path="/" element={IS_HQ_HOST ? <HydraHQ /> : <HomeDashboard />} />
            <Route path="/hq" element={<HydraHQ />} />
            <Route path="/hq/room/:id" element={<RoomDetail />} />
            <Route path="/hq/head/:name" element={<HeadDetail />} />
            <Route path="/hq/console" element={<ConsoleDeck />} />
            <Route path="/hq/console/:name" element={<ConsoleView />} />
            <Route path="/hq/memory" element={<MemoryBrowser />} />
            <Route path="/hq/memory/:name" element={<MemoryBrowser />} />
            <Route path="/crack-a-dawn" element={<CrackADawn />} />
            <Route path="/options" element={<OptionsEngine />} />
            <Route path="/fintube" element={<FinTube />} />
            <Route path="/markets" element={<Markets />} />
            <Route path="/charts" element={<Charts />} />
            <Route path="/charting-scout" element={<ChartingScout />} />
            <Route path="/portfolio-scan" element={<PortfolioScan />} />
            <Route path="/sector-rotation" element={<SectorRotation />} />
          </Routes>
        </main>
        <MessengerWidget />
        <GlobalTicker />
      </div>
    </BrowserRouter>
  );
}

export default App;
