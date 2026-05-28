import './App.css';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import EnhancedDashboard from './components/EnhancedDashboard';
import PortfolioScan from './pages/PortfolioScan';

function TabBar() {
  const base =
    'px-4 py-2 text-sm font-medium border-b-2 transition-colors';
  const active = 'text-green-400 border-green-500';
  const idle = 'text-gray-400 border-transparent hover:text-gray-200';
  return (
    <nav className="bg-gray-900 border-b border-gray-800 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center gap-2">
        <span className="text-green-400 font-bold mr-4">🕷️ Tradeskeebot</span>
        <NavLink
          to="/"
          end
          className={({ isActive }) => `${base} ${isActive ? active : idle}`}
        >
          📈 Dashboard
        </NavLink>
        <NavLink
          to="/portfolio-scan"
          className={({ isActive }) => `${base} ${isActive ? active : idle}`}
        >
          📊 Portfolio Scan
        </NavLink>
      </div>
    </nav>
  );
}

function App() {
  return (
    <BrowserRouter>
      <div className="app min-h-screen bg-gray-900 text-white">
        <TabBar />
        <Routes>
          <Route path="/" element={<EnhancedDashboard />} />
          <Route path="/portfolio-scan" element={<PortfolioScan />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}

export default App;
