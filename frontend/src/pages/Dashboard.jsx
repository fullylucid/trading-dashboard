import React, { useEffect } from 'react';
import Watchlist from '../components/Watchlist';
import QuantScoreboard from '../components/QuantScoreboard';
import MarketRegime from '../components/MarketRegime';
import useStore from '../store/useStore';

function Dashboard() {
  const { selectedSymbol, setSelectedSymbol, watchlist } = useStore();

  // Auto-select first symbol if none selected
  useEffect(() => {
    if (!selectedSymbol && watchlist.length > 0) {
      setSelectedSymbol(watchlist[0].symbol);
    }
  }, [watchlist, selectedSymbol, setSelectedSymbol]);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">Trading Dashboard</h1>
        <p className="text-gray-400">Real-time price monitoring, quant signals, and market analysis</p>
      </div>

      {/* Main Grid */}
      <div className="space-y-8">
        {/* Watchlist Section */}
        <div className="bg-gray-800 rounded-lg overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-700">
            <h2 className="text-xl font-bold">Live Watchlist</h2>
          </div>
          <div className="overflow-x-auto">
            <Watchlist />
          </div>
        </div>

        {/* Two-column layout for scoreboard and regime */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Quant Scoreboard - wider */}
          <div className="lg:col-span-2">
            <QuantScoreboard />
          </div>

          {/* Market Regime */}
          <div>
            <MarketRegime />
          </div>
        </div>

        {/* P&L Summary */}
        <div className="bg-gray-800 rounded-lg p-6">
          <h2 className="text-lg font-bold mb-4">P&L Summary</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-gray-700/50 rounded p-4">
              <p className="text-xs text-gray-400 mb-1">Realized P&L</p>
              <p className="text-2xl font-bold text-gray-300">$0.00</p>
            </div>
            <div className="bg-gray-700/50 rounded p-4">
              <p className="text-xs text-gray-400 mb-1">Unrealized P&L</p>
              <p className="text-2xl font-bold text-gray-300">$0.00</p>
            </div>
            <div className="bg-gray-700/50 rounded p-4">
              <p className="text-xs text-gray-400 mb-1">Win Rate</p>
              <p className="text-2xl font-bold text-gray-300">0%</p>
            </div>
            <div className="bg-gray-700/50 rounded p-4">
              <p className="text-xs text-gray-400 mb-1">Sharpe Ratio</p>
              <p className="text-2xl font-bold text-gray-300">—</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Dashboard;
