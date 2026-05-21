import React, { useEffect, useState } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import axios from 'axios';
import './App.css';

// Components
import Navigation from './components/Navigation';
import Dashboard from './pages/Dashboard';
import ChartView from './pages/ChartView';
import SignalHistory from './pages/SignalHistory';

// Store
import useStore from './store/useStore';

function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const { setWatchlist, setRegime, setHealth } = useStore();

  useEffect(() => {
    // Check API health
    const checkHealth = async () => {
      try {
        const res = await axios.get('/api/health');
        setHealth(res.data);
        setIsConnected(true);
      } catch (err) {
        console.error('API health check failed:', err);
        setIsConnected(false);
      } finally {
        setIsLoading(false);
      }
    };

    // Load initial data
    const loadData = async () => {
      try {
        const [watchlistRes, regimeRes] = await Promise.all([
          axios.get('/api/watchlist'),
          axios.get('/api/regime')
        ]);
        
        setWatchlist(watchlistRes.data);
        setRegime(regimeRes.data);
      } catch (err) {
        console.error('Failed to load initial data:', err);
      }
    };

    checkHealth();
    loadData();

    // Periodic refresh
    const interval = setInterval(() => {
      checkHealth();
      loadData();
    }, 30000); // Every 30 seconds

    return () => clearInterval(interval);
  }, [setWatchlist, setRegime, setHealth]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900">
        <div className="text-white">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-green-500 mx-auto mb-4"></div>
          <p className="text-center">Loading dashboard...</p>
        </div>
      </div>
    );
  }

  return (
    <Router>
      <div className="min-h-screen bg-gray-900 text-white">
        {!isConnected && (
          <div className="bg-red-900 border-l-4 border-red-700 p-4 mb-4">
            <p className="font-bold">⚠️ API Connection Error</p>
            <p className="text-sm">Backend is not responding. Some features may be unavailable.</p>
          </div>
        )}
        
        <Navigation isConnected={isConnected} />
        
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/chart/:symbol" element={<ChartView />} />
          <Route path="/signals" element={<SignalHistory />} />
        </Routes>
      </div>
    </Router>
  );
}

export default App;
