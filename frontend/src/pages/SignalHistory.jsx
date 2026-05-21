import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from 'recharts';

function SignalHistory() {
  const [history, setHistory] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const res = await axios.get('/api/signals-history');
        setHistory(res.data);
      } catch (err) {
        console.error('Failed to load signal history:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchHistory();
    const interval = setInterval(fetchHistory, 60000); // Refresh every minute
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 text-center text-gray-400">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-green-500 mx-auto mb-4"></div>
        Loading signal history...
      </div>
    );
  }

  if (!history) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <p className="text-gray-400">No signal data available</p>
      </div>
    );
  }

  const signalDistribution = [
    { name: 'Buy', value: history.buy_signals, fill: '#10b981' },
    { name: 'Sell', value: history.sell_signals, fill: '#ef4444' },
    { name: 'Neutral', value: history.total_signals_24h - history.buy_signals - history.sell_signals, fill: '#6b7280' }
  ];

  const confidenceData = [
    { name: 'High (>75%)', value: history.confidence_distribution.high || 0, fill: '#10b981' },
    { name: 'Medium (50-75%)', value: history.confidence_distribution.medium || 0, fill: '#f59e0b' },
    { name: 'Low (<50%)', value: history.confidence_distribution.low || 0, fill: '#ef4444' }
  ];

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">Signal History (Last 24h)</h1>
        <p className="text-gray-400">Track signal generation, conversions, and confidence distribution</p>
      </div>

      {/* Key Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        <div className="bg-gray-800 rounded-lg p-6">
          <p className="text-sm text-gray-400 mb-2">Total Signals</p>
          <p className="text-3xl font-bold text-white">{history.total_signals_24h}</p>
          <p className="text-xs text-gray-500 mt-2">Signals in last 24 hours</p>
        </div>
        
        <div className="bg-gray-800 rounded-lg p-6">
          <p className="text-sm text-gray-400 mb-2">Buy Signals</p>
          <p className="text-3xl font-bold text-green-400">{history.buy_signals}</p>
          <p className="text-xs text-gray-500 mt-2">Bullish signals</p>
        </div>
        
        <div className="bg-gray-800 rounded-lg p-6">
          <p className="text-sm text-gray-400 mb-2">Sell Signals</p>
          <p className="text-3xl font-bold text-red-400">{history.sell_signals}</p>
          <p className="text-xs text-gray-500 mt-2">Bearish signals</p>
        </div>
        
        <div className="bg-gray-800 rounded-lg p-6">
          <p className="text-sm text-gray-400 mb-2">Avg Confidence</p>
          <p className="text-3xl font-bold text-blue-400">{(history.avg_confidence * 100).toFixed(1)}%</p>
          <p className="text-xs text-gray-500 mt-2">Average signal confidence</p>
        </div>
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* Signal Distribution */}
        <div className="bg-gray-800 rounded-lg p-6">
          <h2 className="text-lg font-bold mb-4">Signal Distribution</h2>
          {signalDistribution.some(d => d.value > 0) ? (
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={signalDistribution}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, value }) => `${name}: ${value}`}
                  outerRadius={80}
                  fill="#8884d8"
                  dataKey="value"
                >
                  {signalDistribution.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.fill} />
                  ))}
                </Pie>
                <Tooltip formatter={(value) => value} />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-gray-400 text-center py-12">No signals yet</p>
          )}
        </div>

        {/* Confidence Distribution */}
        <div className="bg-gray-800 rounded-lg p-6">
          <h2 className="text-lg font-bold mb-4">Confidence Distribution</h2>
          {confidenceData.some(d => d.value > 0) ? (
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={confidenceData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, value }) => `${name}: ${value}`}
                  outerRadius={80}
                  fill="#8884d8"
                  dataKey="value"
                >
                  {confidenceData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.fill} />
                  ))}
                </Pie>
                <Tooltip formatter={(value) => value} />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-gray-400 text-center py-12">No signals yet</p>
          )}
        </div>
      </div>

      {/* Recent Signals */}
      {history.top_signals && history.top_signals.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-6">
          <h2 className="text-lg font-bold mb-4">Recent Signals</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700 text-gray-400">
                  <th className="text-left px-4 py-2">Symbol</th>
                  <th className="text-left px-4 py-2">Signal</th>
                  <th className="text-right px-4 py-2">Confidence</th>
                  <th className="text-left px-4 py-2">Momentum</th>
                  <th className="text-left px-4 py-2">Time</th>
                </tr>
              </thead>
              <tbody>
                {history.top_signals.map((signal, idx) => (
                  <tr key={idx} className="border-b border-gray-700/50 hover:bg-gray-700/20 transition">
                    <td className="px-4 py-2 font-bold text-white">{signal.symbol}</td>
                    <td className="px-4 py-2">
                      <span className={`px-2 py-1 rounded text-xs font-bold ${
                        signal.signal_type === 'buy' ? 'bg-green-900 text-green-200' :
                        signal.signal_type === 'sell' ? 'bg-red-900 text-red-200' :
                        'bg-gray-700 text-gray-300'
                      }`}>
                        {signal.signal_type.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right font-mono">
                      {(signal.aggregate_confidence * 100).toFixed(1)}%
                    </td>
                    <td className="px-4 py-2">
                      <span className={signal.momentum_score > 0 ? 'text-green-400' : 'text-red-400'}>
                        {signal.momentum_score > 0 ? '↑' : '↓'} {Math.abs(signal.momentum_score).toFixed(3)}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-gray-500 text-xs">
                      {new Date(signal.timestamp).toLocaleTimeString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

export default SignalHistory;
