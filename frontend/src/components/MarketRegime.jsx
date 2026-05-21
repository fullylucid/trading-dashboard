import React, { useEffect } from 'react';
import useStore from '../store/useStore';

function MarketRegime() {
  const { regime } = useStore();

  const getHMMPhaseLabel = (phase) => {
    const phases = {
      0: { name: 'Calm', emoji: '😌', color: 'blue' },
      1: { name: 'Trending Up', emoji: '📈', color: 'green' },
      2: { name: 'Trending Down', emoji: '📉', color: 'red' },
      3: { name: 'High Volatility', emoji: '⚡', color: 'orange' },
    };
    return phases[phase] || { name: 'Unknown', emoji: '❓', color: 'gray' };
  };

  const getVolatilityColor = (regime) => {
    if (regime === 'low') return 'text-green-400';
    if (regime === 'high') return 'text-red-400';
    return 'text-yellow-400';
  };

  if (!regime) {
    return (
      <div className="bg-gray-800 rounded-lg p-6">
        <h2 className="text-lg font-bold mb-4">Market Regime</h2>
        <p className="text-gray-400">Loading regime data...</p>
      </div>
    );
  }

  const hmmPhase = getHMMPhaseLabel(regime.hmm_phase);
  const marketHeat = regime.market_heat || 0.5;

  return (
    <div className="bg-gray-800 rounded-lg p-6">
      <h2 className="text-lg font-bold mb-6">Market Regime Analysis</h2>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* HMM Phase */}
        <div className="bg-gray-700/50 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-300 mb-3">HMM Phase</h3>
          <div className={`text-3xl font-bold mb-2 text-${hmmPhase.color}-400`}>
            {hmmPhase.emoji} {hmmPhase.name}
          </div>
          <p className="text-xs text-gray-400">
            Phase {regime.hmm_phase} - {(regime.estimated_probability * 100).toFixed(1)}% confidence
          </p>
        </div>

        {/* Volatility Regime */}
        <div className="bg-gray-700/50 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-300 mb-3">Volatility Regime</h3>
          <div className={`text-3xl font-bold mb-2 ${getVolatilityColor(regime.volatility_regime)}`}>
            {regime.volatility_regime === 'low' ? '📊' : '⚡'} {regime.volatility_regime.toUpperCase()}
          </div>
          <p className="text-xs text-gray-400">
            {regime.volatility_regime === 'low' 
              ? 'Use momentum strategies' 
              : 'Use mean-reversion strategies'}
          </p>
        </div>

        {/* Trend Direction */}
        <div className="bg-gray-700/50 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-300 mb-3">Trend Direction</h3>
          <div className="text-3xl font-bold mb-2">
            {regime.trend_direction === 'up' ? '📈 UP' : 
             regime.trend_direction === 'down' ? '📉 DOWN' : 
             '→ NEUTRAL'}
          </div>
          <p className="text-xs text-gray-400">
            Primary market direction
          </p>
        </div>

        {/* Market Heat */}
        <div className="bg-gray-700/50 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-300 mb-3">Market Heat</h3>
          <div className="flex items-center gap-3 mb-2">
            <div className="text-2xl">
              {marketHeat > 0.7 ? '🔥' : marketHeat > 0.4 ? '🌡️' : '❄️'}
            </div>
            <div className="text-3xl font-bold">
              {(marketHeat * 100).toFixed(0)}%
            </div>
          </div>
          <div className="w-full h-2 bg-gray-600 rounded">
            <div
              className="h-full rounded bg-gradient-to-r from-blue-500 via-yellow-500 to-red-500 transition-all"
              style={{ width: `${marketHeat * 100}%` }}
            ></div>
          </div>
        </div>
      </div>

      {/* Regime-Specific Recommendation */}
      <div className="bg-gradient-to-r from-blue-900/50 to-purple-900/50 rounded-lg p-4 mt-6">
        <h3 className="font-semibold mb-2">📌 Strategy Recommendation</h3>
        <p className="text-sm text-gray-300">
          {regime.volatility_regime === 'low' 
            ? '✅ Low volatility detected. Momentum and trend-following strategies recommended.'
            : '✅ High volatility detected. Mean-reversion and range-bound strategies recommended.'}
          {' '}
          Current trend: <strong>{regime.trend_direction.toUpperCase()}</strong>
        </p>
      </div>
    </div>
  );
}

export default MarketRegime;
