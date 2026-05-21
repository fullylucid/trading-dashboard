import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import useStore from '../store/useStore';

function Watchlist() {
  const { watchlist } = useStore();

  const getPriceColor = (change) => {
    if (change > 0) return 'text-green-400';
    if (change < 0) return 'text-red-400';
    return 'text-gray-400';
  };

  const getAlertBadge = (status) => {
    switch (status) {
      case 'triggered':
        return <span className="inline-block px-2 py-1 text-xs font-bold bg-red-900 text-red-200 rounded">⚠️ Triggered</span>;
      case 'watchful':
        return <span className="inline-block px-2 py-1 text-xs font-bold bg-blue-900 text-blue-200 rounded">👁️ Watching</span>;
      default:
        return <span className="inline-block px-2 py-1 text-xs font-bold bg-gray-700 text-gray-300 rounded">⊘ Disabled</span>;
    }
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-gray-700 bg-gray-800">
            <th className="text-left px-4 py-3 font-semibold">Symbol</th>
            <th className="text-right px-4 py-3 font-semibold">Price</th>
            <th className="text-right px-4 py-3 font-semibold">Change %</th>
            <th className="text-right px-4 py-3 font-semibold">Volume</th>
            <th className="text-right px-4 py-3 font-semibold">Bid/Ask</th>
            <th className="text-left px-4 py-3 font-semibold">Status</th>
            <th className="text-left px-4 py-3 font-semibold">Action</th>
          </tr>
        </thead>
        <tbody>
          {watchlist.length === 0 ? (
            <tr>
              <td colSpan="7" className="text-center py-8 text-gray-400">
                No watchlist items. Loading...
              </td>
            </tr>
          ) : (
            watchlist.map((item) => (
              <tr
                key={item.symbol}
                className="border-b border-gray-700 hover:bg-gray-800/50 transition"
              >
                <td className="px-4 py-3 font-bold text-white">
                  {item.symbol}
                </td>
                <td className="text-right px-4 py-3 font-mono">
                  ${item.price?.toFixed(2) || 'N/A'}
                </td>
                <td className={`text-right px-4 py-3 font-semibold ${getPriceColor(item.change_percent)}`}>
                  {item.change_percent > 0 ? '+' : ''}{item.change_percent?.toFixed(2) || '0.00'}%
                </td>
                <td className="text-right px-4 py-3 font-mono text-gray-400">
                  {item.volume?.toLocaleString() || 'N/A'}
                </td>
                <td className="text-right px-4 py-3 font-mono text-gray-400">
                  {item.bid?.toFixed(2) || 'N/A'} / {item.ask?.toFixed(2) || 'N/A'}
                </td>
                <td className="px-4 py-3">
                  {getAlertBadge(item.alert_status)}
                </td>
                <td className="px-4 py-3">
                  <Link
                    to={`/chart/${item.symbol}`}
                    className="inline-block px-3 py-1 bg-green-600 text-white rounded hover:bg-green-500 transition text-sm"
                  >
                    Chart →
                  </Link>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export default Watchlist;
