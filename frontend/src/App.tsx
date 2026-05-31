import './App.css';
import { useState, useEffect, useRef } from 'react';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import EnhancedDashboard from './components/EnhancedDashboard';
import PortfolioScan from './pages/PortfolioScan';
import SectorRotation from './pages/SectorRotation';
import Charts from './pages/Charts';
import CrackADawn from './pages/CrackADawn';
import MessengerWidget from './components/MessengerWidget/MessengerWidget';

const ROUTES: { to: string; label: string; end?: boolean }[] = [
  { to: '/', label: '📈 Dashboard', end: true },
  { to: '/crack-a-dawn', label: '🌅 Crack-a-Dawn' },
  { to: '/charts', label: '📉 Charts' },
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

function App() {
  return (
    <BrowserRouter>
      <div className="app min-h-screen bg-gray-900 text-white">
        <NavMenu />
        <Routes>
          <Route path="/" element={<EnhancedDashboard />} />
          <Route path="/crack-a-dawn" element={<CrackADawn />} />
          <Route path="/charts" element={<Charts />} />
          <Route path="/portfolio-scan" element={<PortfolioScan />} />
          <Route path="/sector-rotation" element={<SectorRotation />} />
        </Routes>
        <MessengerWidget />
      </div>
    </BrowserRouter>
  );
}

export default App;
