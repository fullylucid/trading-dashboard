import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ComposedChart, Bar } from 'recharts';

function ChartView() {
  const { symbol } = useParams();
  const navigate = useNavigate();
  const [chartData, setChartData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchChartData = async () => {
      try {
        setLoading(true);
        const res = await axios.get(`/api/chart-data/${symbol}`, {
          params: { lookback_days: 30 }
        });
        
        // Transform data for Recharts
        const transformed = res.data.map(candle => ({
          date: new Date(candle.timestamp).toLocaleDateString(),
          open: candle.open,
          high: candle.high,
          low: candle.low,
          close: candle.close,
          volume: candle.volume,
          sma20: candle.sma_20,
          sma50: candle.sma_50,
          sma200: candle.sma_200
        }));
        
        setChartData(transformed);
        setError(null);
      } catch (err) {
        console.error('Failed to load chart data:', err);
        setError('Failed to load chart data');
      } finally {
        setLoading(false);
      }
    };

    if (symbol) {
      fetchChartData();
    }
  }, [symbol]);

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="text-center text-gray-400">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-green-500 mx-auto mb-4"></div>
          <p>Loading chart data...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Header */}
      <div className="mb-6 flex items-center gap-4">
        <button
          onClick={() => navigate('/')}
          className="px-4 py-2 bg-gray-700 text-white rounded hover:bg-gray-600 transition"
        >
          ← Back
        </button>
        <h1 className="text-3xl font-bold">{symbol} - 30-Day Chart</h1>
      </div>

      {error && (
        <div className="bg-red-900 border-l-4 border-red-700 p-4 mb-6">
          <p className="text-red-200">{error}</p>
        </div>
      )}

      {/* OHLC Chart */}
      <div className="bg-gray-800 rounded-lg p-6 mb-8">
        <h2 className="text-lg font-bold mb-4">OHLC with Moving Averages</h2>
        
        {chartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={400}>
            <ComposedChart data={chartData} margin={{ top: 20, right: 30, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis 
                dataKey="date" 
                tick={{ fill: '#9ca3af' }}
                angle={-45}
                textAnchor="end"
                height={80}
              />
              <YAxis yAxisId="left" tick={{ fill: '#9ca3af' }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fill: '#9ca3af' }} />
              <Tooltip 
                contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151' }}
                labelStyle={{ color: '#fff' }}
                formatter={(value) => value?.toFixed(2)}
              />
              <Legend />
              
              {/* Price lines */}
              <Line 
                yAxisId="left"
                type="monotone" 
                dataKey="close" 
                stroke="#10b981" 
                dot={false}
                isAnimationActive={false}
                name="Close"
              />
              
              {/* Moving averages */}
              {chartData.some(d => d.sma20) && (
                <Line 
                  yAxisId="left"
                  type="monotone" 
                  dataKey="sma20" 
                  stroke="#fbbf24" 
                  dot={false}
                  isAnimationActive={false}
                  name="SMA 20"
                  strokeWidth={1}
                  strokeDasharray="5 5"
                />
              )}
              
              {chartData.some(d => d.sma50) && (
                <Line 
                  yAxisId="left"
                  type="monotone" 
                  dataKey="sma50" 
                  stroke="#f97316" 
                  dot={false}
                  isAnimationActive={false}
                  name="SMA 50"
                  strokeWidth={1}
                  strokeDasharray="5 5"
                />
              )}
              
              {/* Volume bars */}
              <Bar 
                yAxisId="right"
                dataKey="volume" 
                fill="#3b82f6" 
                opacity={0.3}
                isAnimationActive={false}
                name="Volume"
              />
            </ComposedChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-gray-400">No chart data available</p>
        )}
      </div>

      {/* Statistics */}
      {chartData.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-gray-800 rounded-lg p-4">
            <p className="text-xs text-gray-400 mb-1">Open (30d)</p>
            <p className="text-xl font-bold">${chartData[0]?.open?.toFixed(2)}</p>
          </div>
          <div className="bg-gray-800 rounded-lg p-4">
            <p className="text-xs text-gray-400 mb-1">High</p>
            <p className="text-xl font-bold text-green-400">
              ${Math.max(...chartData.map(d => d.high)).toFixed(2)}
            </p>
          </div>
          <div className="bg-gray-800 rounded-lg p-4">
            <p className="text-xs text-gray-400 mb-1">Low</p>
            <p className="text-xl font-bold text-red-400">
              ${Math.min(...chartData.map(d => d.low)).toFixed(2)}
            </p>
          </div>
          <div className="bg-gray-800 rounded-lg p-4">
            <p className="text-xs text-gray-400 mb-1">Close (Latest)</p>
            <p className="text-xl font-bold">${chartData[chartData.length - 1]?.close?.toFixed(2)}</p>
          </div>
        </div>
      )}
    </div>
  );
}

export default ChartView;
