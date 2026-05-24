/**
 * MarketStats Component
 * Displays key market statistics, sector performance, and breadth indicators
 */

import React, { useState, useEffect } from 'react';
import './MarketStats.css';

interface IndexData {
  symbol: string;
  price: number;
  change: number;
  change_pct: number;
}

interface SectorData {
  name: string;
  value: number;
  change_pct: number;
  change: number;
}

interface BreadthData {
  advances: number;
  declines: number;
  unchanged: number;
  advance_decline_ratio: number;
  up_volume: number;
  down_volume: number;
}

const MarketStats: React.FC = () => {
  const [indices, setIndices] = useState<Record<string, IndexData>>({});
  const [sectors, setSectors] = useState<SectorData[]>([]);
  const [breadth, setBreadth] = useState<BreadthData | null>(null);
  const [vix, setVix] = useState<IndexData | null>(null);
  const [treasuries, setTreasuries] = useState<Record<string, any>>({});
  const [commodities, setCommodities] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMarketData();
    const interval = setInterval(fetchMarketData, 60000); // Refresh every minute
    return () => clearInterval(interval);
  }, []);

  const fetchMarketData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [indicesRes, sectorsRes, breadthRes, vixRes, treasRes, commRes] =
        await Promise.all([
          fetch('/api/market/overview'),
          fetch('/api/market/sectors'),
          fetch('/api/market/breadth'),
          fetch('/api/market/vix'),
          fetch('/api/market/treasuries'),
          fetch('/api/market/commodities'),
        ]);

      if (indicesRes.ok) setIndices(await indicesRes.json());
      if (sectorsRes.ok) setSectors(await sectorsRes.json());
      if (breadthRes.ok) setBreadth(await breadthRes.json());
      if (vixRes.ok) setVix(await vixRes.json());
      if (treasRes.ok) setTreasuries(await treasRes.json());
      if (commRes.ok) setCommodities(await commRes.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const getChangeClass = (change: number): string => {
    if (change > 0) return 'positive';
    if (change < 0) return 'negative';
    return 'neutral';
  };

  const formatPercent = (value: number): string => {
    const sign = value > 0 ? '+' : '';
    return `${sign}${value.toFixed(2)}%`;
  };

  const formatPrice = (value: number): string => {
    return value.toFixed(2);
  };

  return (
    <div className="market-stats">
      {error && <div className="market-error">Error: {error}</div>}

      {/* Major Indices */}
      <section className="stats-section">
        <h3>Market Indices</h3>
        <div className="indices-grid">
          {['SPY', 'QQQ', 'DIA', 'IWM'].map((symbol) => {
            const data = indices[symbol];
            if (!data) return null;
            return (
              <div key={symbol} className={`index-card ${getChangeClass(data.change)}`}>
                <div className="index-symbol">{symbol}</div>
                <div className="index-price">{formatPrice(data.price)}</div>
                <div className="index-change">
                  {formatPercent(data.change_pct)}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* VIX Volatility Index */}
      {vix && (
        <section className="stats-section">
          <h3>Volatility</h3>
          <div className={`vix-card ${vix.change > 0 ? 'rising' : 'falling'}`}>
            <div className="vix-label">VIX</div>
            <div className="vix-value">{formatPrice(vix.price)}</div>
            <div className="vix-status">
              {vix.price > 20 && 'High Volatility'}
              {vix.price >= 12 && vix.price <= 20 && 'Normal Volatility'}
              {vix.price < 12 && 'Low Volatility'}
            </div>
          </div>
        </section>
      )}

      {/* Sector Performance */}
      <section className="stats-section">
        <h3>Sector Performance</h3>
        <div className="sectors-list">
          {sectors.length === 0 && !loading && (
            <div className="no-data">Loading sector data...</div>
          )}
          {sectors.map((sector) => (
            <div
              key={sector.name}
              className={`sector-item ${getChangeClass(sector.change)}`}
            >
              <div className="sector-name">{sector.name}</div>
              <div className="sector-metrics">
                <span className="sector-value">{formatPrice(sector.value)}</span>
                <span className="sector-change">
                  {formatPercent(sector.change_pct)}
                </span>
              </div>
              <div
                className="sector-bar"
                style={{
                  width: `${Math.min(Math.abs(sector.change_pct) * 10, 100)}%`,
                }}
              ></div>
            </div>
          ))}
        </div>
      </section>

      {/* Market Breadth */}
      {breadth && (
        <section className="stats-section">
          <h3>Market Breadth</h3>
          <div className="breadth-grid">
            <div className="breadth-item">
              <div className="breadth-label">Advances</div>
              <div className="breadth-value positive">{breadth.advances}</div>
            </div>
            <div className="breadth-item">
              <div className="breadth-label">Declines</div>
              <div className="breadth-value negative">{breadth.declines}</div>
            </div>
            <div className="breadth-item">
              <div className="breadth-label">Ratio</div>
              <div className="breadth-value">
                {breadth.advance_decline_ratio.toFixed(2)}
              </div>
            </div>
            <div className="breadth-item">
              <div className="breadth-label">Up Volume</div>
              <div className="breadth-value">
                {(breadth.up_volume / 1e9).toFixed(2)}B
              </div>
            </div>
          </div>

          <div className="breadth-visualization">
            <div className="breadth-bar">
              <div
                className="breadth-segment positive"
                style={{
                  width: `${(breadth.advances / (breadth.advances + breadth.declines)) * 100}%`,
                }}
                title={`Advances: ${breadth.advances}`}
              ></div>
              <div
                className="breadth-segment negative"
                style={{
                  width: `${(breadth.declines / (breadth.advances + breadth.declines)) * 100}%`,
                }}
                title={`Declines: ${breadth.declines}`}
              ></div>
            </div>
            <div className="breadth-labels">
              <span className="label-item">
                <span className="color-box positive"></span>
                {breadth.advances}
              </span>
              <span className="label-item">
                <span className="color-box negative"></span>
                {breadth.declines}
              </span>
            </div>
          </div>
        </section>
      )}

      {/* Treasuries */}
      {Object.keys(treasuries).length > 0 && (
        <section className="stats-section">
          <h3>Treasury Yields</h3>
          <div className="treasuries-grid">
            {Object.entries(treasuries).map(([period, data]: any) => (
              <div key={period} className="treasury-item">
                <div className="treasury-period">{period}</div>
                <div className="treasury-yield">
                  {data.yield.toFixed(2)}%
                </div>
                {data.change && (
                  <div className={`treasury-change ${getChangeClass(data.change)}`}>
                    {formatPercent(data.change)}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Commodities */}
      {Object.keys(commodities).length > 0 && (
        <section className="stats-section">
          <h3>Commodities</h3>
          <div className="commodities-grid">
            {Object.entries(commodities).map(([name, data]: any) => (
              <div key={name} className={`commodity-item ${getChangeClass(data.change || 0)}`}>
                <div className="commodity-name">{name}</div>
                <div className="commodity-price">${data.price.toFixed(2)}</div>
                {data.change_pct && (
                  <div className="commodity-change">
                    {formatPercent(data.change_pct)}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="last-update">
        Last updated: {new Date().toLocaleTimeString()}
      </div>
    </div>
  );
};

export default MarketStats;
