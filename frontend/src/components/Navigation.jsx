import React from 'react';
import { Link } from 'react-router-dom';
import useStore from '../store/useStore';

function Navigation({ isConnected }) {
  const { priceWsConnected, signalWsConnected } = useStore();

  return (
    <nav className="bg-gray-800 border-b border-gray-700 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between h-16">
          <div className="flex items-center gap-8">
            <Link to="/" className="flex items-center gap-2 text-xl font-bold text-green-400 hover:text-green-300">
              📈 Trading Dashboard
            </Link>
            
            <div className="hidden sm:flex items-center gap-6">
              <Link to="/" className="text-gray-300 hover:text-white transition">
                Watchlist
              </Link>
              <Link to="/signals" className="text-gray-300 hover:text-white transition">
                Signals
              </Link>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {/* Connection Status */}
            <div className="flex gap-3 text-xs">
              <div className={`flex items-center gap-1 px-2 py-1 rounded ${
                isConnected ? 'bg-green-900 text-green-200' : 'bg-red-900 text-red-200'
              }`}>
                <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-400' : 'bg-red-400'}`}></span>
                API
              </div>
              
              <div className={`flex items-center gap-1 px-2 py-1 rounded ${
                priceWsConnected ? 'bg-green-900 text-green-200' : 'bg-gray-700 text-gray-400'
              }`}>
                <span className={`w-2 h-2 rounded-full ${priceWsConnected ? 'bg-green-400' : 'bg-gray-500'}`}></span>
                Price
              </div>
              
              <div className={`flex items-center gap-1 px-2 py-1 rounded ${
                signalWsConnected ? 'bg-green-900 text-green-200' : 'bg-gray-700 text-gray-400'
              }`}>
                <span className={`w-2 h-2 rounded-full ${signalWsConnected ? 'bg-green-400' : 'bg-gray-500'}`}></span>
                Signals
              </div>
            </div>

            {/* Time */}
            <div className="text-sm text-gray-400">
              {new Date().toLocaleTimeString()}
            </div>
          </div>
        </div>
      </div>
    </nav>
  );
}

export default Navigation;
