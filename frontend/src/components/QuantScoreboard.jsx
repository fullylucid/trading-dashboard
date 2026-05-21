import React, { useEffect, useState } from 'react';
import axios from 'axios';
import useStore from '../store/useStore';

function QuantScoreboard() {
  const { signals } = useStore();
  const [selectedSymbol, setSelectedSymbol] = useState(null);

  // Get current signal or use empty
  const currentSignal = selectedSymbol ? signals[selectedSymbol] : null;

  const StrategyScore = ({ label, score, confidence, color = 'blue' }) => {
    const normalizedScore = Math.min(Math.max((score + 1) / 2 * 100, 0), 100);
    const bgColor = score > 0.3 ? 'bg-green-900' : score < -0.3 ? 'bg-red-900' : 'bg-gray-700';
    
    return (
      <div className="bg-gray-800 rounded-lg p-4">
        <div className="flex justify-between items-center mb-2">
          <h3 className="font-semibold text-sm">{label}</h3>
          <span className={`text-xs font-bold px-2 py-1 rounded ${
            confidence > 0.75 ? 'bg-green-900 text-green-200' :
            confidence > 0.5 ? 'bg-yellow-900 text-yellow-200' :
            'bg-gray-700 text-gray-300'
          }`}>
            {(confidence * 100).toFixed(0)}%
          </span>
        </div>
        
        <div className={`w-full h-2 rounded ${bgColor}`}>
          <div
            className="h-full rounded bg-gradient-to-r from-red-500 to-green-500 transition-all duration-300"
            style={{ width: `${normalizedScore}%` }}
          ></div>
        </div>
        
        <div className="text-xs text-gray-400 mt-1">
          {score > 0 ? '↑ ' : score < 0 ? '↓ ' : '→ '}
          {score.toFixed(3)}
        </div>
      </div>
    );
  };

  if (!currentSignal) {
    return (
      <div className="bg-gray-800 rounded-lg p-6">
        <h2 className="text-lg font-bold mb-4">7-Strategy Quant Scoreboard</h2>
        <p className="text-gray-400">Select a symbol from the watchlist to view signals</p>
      </div>
    );
  }

  return (
    <div className="bg-gray-800 rounded-lg p-6">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-lg font-bold">{currentSignal.symbol} - Quant Analysis</h2>
          <p className="text-xs text-gray-400">
            {new Date(currentSignal.timestamp).toLocaleString()}
          </p>
        </div>
        
        <div className={`text-2xl font-bold px-4 py-2 rounded ${
          currentSignal.signal_type === 'buy' ? 'bg-green-900 text-green-200' :
          currentSignal.signal_type === 'sell' ? 'bg-red-900 text-red-200' :
          'bg-gray-700 text-gray-300'
        }`}>
          {currentSignal.signal_type.toUpperCase()}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <StrategyScore
          label="1. Momentum"
          score={currentSignal.momentum_score}
          confidence={currentSignal.momentum_confidence}
        />
        <StrategyScore
          label="2. Mean Reversion"
          score={currentSignal.reversion_score}
          confidence={currentSignal.reversion_confidence}
        />
        <StrategyScore
          label="3. Volatility"
          score={currentSignal.volatility_score}
          confidence={0.7}
        />
        <StrategyScore
          label="4. Patterns"
          score={currentSignal.pattern_score}
          confidence={0.6}
        />
        <StrategyScore
          label="5. Regime"
          score={currentSignal.regime_score}
          confidence={0.65}
        />
        <StrategyScore
          label="6. Correlation"
          score={currentSignal.correlation_score}
          confidence={0.55}
        />
        <StrategyScore
          label="7. Leading Indicators"
          score={currentSignal.leading_indicator_score}
          confidence={0.6}
        />
      </div>

      {/* Aggregate Confidence */}
      <div className="bg-gradient-to-r from-gray-700 to-gray-800 rounded-lg p-4">
        <div className="flex justify-between items-center">
          <h3 className="font-semibold">Aggregate Confidence</h3>
          <span className={`text-3xl font-bold ${
            currentSignal.aggregate_confidence > 0.75 ? 'text-green-400' :
            currentSignal.aggregate_confidence > 0.5 ? 'text-yellow-400' :
            'text-gray-400'
          }`}>
            {(currentSignal.aggregate_confidence * 100).toFixed(1)}%
          </span>
        </div>
        <div className="w-full h-3 rounded bg-gray-600 mt-2">
          <div
            className="h-full rounded bg-gradient-to-r from-yellow-500 to-green-500"
            style={{ width: `${currentSignal.aggregate_confidence * 100}%` }}
          ></div>
        </div>
      </div>
    </div>
  );
}

export default QuantScoreboard;
