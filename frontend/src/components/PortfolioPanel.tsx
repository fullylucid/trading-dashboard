import React, { useState, useEffect } from 'react';
import '../styles/PortfolioPanel.css';

interface Position {
  symbol: string;
  quantity: number;
  current_price: number;
  average_buy_price: number;
  current_value: number;
  cost_basis: number;
  gain_loss: number;
  gain_loss_pct: number;
  bid_price: number;
  ask_price: number;
  pe_ratio?: number;
  market_cap?: string;
}

interface PortfolioData {
  account_value: number;
  buying_power: number;
  cash: number;
  positions: Position[];
  summary: {
    total_positions: number;
    portfolio_value: number;
    total_gain_loss: number;
    total_gain_loss_pct: number;
    top_position: {
      symbol: string;
      value: number;
      pct_of_portfolio: number;
    };
  };
  timestamp: string;
}

interface PortfolioPanelProps {
  onRefresh?: () => void;
}

const PortfolioPanel: React.FC<PortfolioPanelProps> = ({ onRefresh }) => {
  const [portfolio, setPortfolio] = useState<PortfolioData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<'value' | 'gain_loss' | 'gain_loss_pct' | 'symbol'>('value');
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null);

  const fetchPortfolio = async (forceRefresh = false) => {
    try {
      setLoading(true);
      const url = forceRefresh 
        ? '/api/portfolio/?refresh=true' 
        : '/api/portfolio/';
      
      const response = await fetch(url);
      if (!response.ok) throw new Error('Failed to fetch portfolio');
      
      const data = await response.json();
      if (data.success) {
        setPortfolio(data.data);
        setError(null);
      } else {
        setError('Portfolio service unavailable');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error fetching portfolio');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPortfolio();
    const interval = setInterval(() => fetchPortfolio(), 60000); // Refresh every minute
    return () => clearInterval(interval);
  }, []);

  const handleRefresh = () => {
    fetchPortfolio(true);
    onRefresh?.();
  };

  if (loading) {
    return (
      <div className="portfolio-panel">
        <div className="portfolio-header">
          <h2>📊 Portfolio</h2>
        </div>
        <div className="loading">Loading portfolio...</div>
      </div>
    );
  }

  if (error || !portfolio) {
    return (
      <div className="portfolio-panel error">
        <div className="portfolio-header">
          <h2>📊 Portfolio</h2>
        </div>
        <div className="error-message">
          ⚠️ {error || 'No portfolio data available'}
        </div>
      </div>
    );
  }

  const summary = portfolio.summary;
  const positions = portfolio.positions.sort((a, b) => {
    switch (sortBy) {
      case 'value':
        return b.current_value - a.current_value;
      case 'gain_loss':
        return b.gain_loss - a.gain_loss;
      case 'gain_loss_pct':
        return b.gain_loss_pct - a.gain_loss_pct;
      case 'symbol':
        return a.symbol.localeCompare(b.symbol);
      default:
        return 0;
    }
  });

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    }).format(value);
  };

  const formatPercent = (value: number) => `${(value * 100).toFixed(2)}%`;

  const getGainLossColor = (value: number) => value >= 0 ? '#00ff88' : '#ff3333';

  return (
    <div className="portfolio-panel">
      {/* Header */}
      <div className="portfolio-header">
        <h2>📊 Portfolio</h2>
        <button 
          className="refresh-btn"
          onClick={handleRefresh}
          title="Refresh portfolio data"
        >
          🔄
        </button>
      </div>

      {/* Summary Stats */}
      <div className="portfolio-summary">
        <div className="stat-card">
          <span className="stat-label">Account Value</span>
          <span className="stat-value">{formatCurrency(portfolio.account_value)}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Buying Power</span>
          <span className="stat-value">{formatCurrency(portfolio.buying_power)}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Cash</span>
          <span className="stat-value">{formatCurrency(portfolio.cash)}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Total Gain/Loss</span>
          <span 
            className="stat-value"
            style={{ color: getGainLossColor(summary.total_gain_loss) }}
          >
            {formatCurrency(summary.total_gain_loss)} ({summary.total_gain_loss_pct.toFixed(2)}%)
          </span>
        </div>
      </div>

      {/* Portfolio Stats */}
      <div className="portfolio-stats">
        <div className="stat-item">
          <span>Positions:</span>
          <strong>{summary.total_positions}</strong>
        </div>
        <div className="stat-item">
          <span>Top Position:</span>
          <strong>{summary.top_position?.symbol}</strong>
          <span className="stat-subtext">
            {formatCurrency(summary.top_position?.value || 0)} 
            ({(summary.top_position?.pct_of_portfolio || 0).toFixed(1)}%)
          </span>
        </div>
      </div>

      {/* Positions Table */}
      <div className="positions-container">
        <div className="positions-header">
          <h3>Positions ({positions.length})</h3>
          <div className="sort-controls">
            <label>Sort: </label>
            <select value={sortBy} onChange={(e) => setSortBy(e.target.value as any)}>
              <option value="value">Value</option>
              <option value="gain_loss">Gain/Loss $</option>
              <option value="gain_loss_pct">Gain/Loss %</option>
              <option value="symbol">Symbol</option>
            </select>
          </div>
        </div>

        {positions.length === 0 ? (
          <div className="no-positions">No open positions</div>
        ) : (
          <div className="positions-list">
            {positions.map((pos) => (
              <div key={pos.symbol} className="position-card">
                <div 
                  className="position-header"
                  onClick={() => setExpandedSymbol(expandedSymbol === pos.symbol ? null : pos.symbol)}
                  style={{ cursor: 'pointer' }}
                >
                  <div className="symbol-info">
                    <h4>{pos.symbol}</h4>
                    <span className="qty">Qty: {pos.quantity.toFixed(4)}</span>
                  </div>
                  <div className="value-info">
                    <div className="current-value">{formatCurrency(pos.current_value)}</div>
                    <div 
                      className="gain-loss"
                      style={{ color: getGainLossColor(pos.gain_loss) }}
                    >
                      {pos.gain_loss >= 0 ? '+' : ''}{formatCurrency(pos.gain_loss)}
                      {' '}
                      ({pos.gain_loss_pct >= 0 ? '+' : ''}{pos.gain_loss_pct.toFixed(2)}%)
                    </div>
                  </div>
                  <span className="expand-indicator">
                    {expandedSymbol === pos.symbol ? '▼' : '▶'}
                  </span>
                </div>

                {/* Expanded Details */}
                {expandedSymbol === pos.symbol && (
                  <div className="position-details">
                    <div className="detail-row">
                      <span className="label">Current Price:</span>
                      <span className="value">{formatCurrency(pos.current_price)}</span>
                    </div>
                    <div className="detail-row">
                      <span className="label">Avg Buy Price:</span>
                      <span className="value">{formatCurrency(pos.average_buy_price)}</span>
                    </div>
                    <div className="detail-row">
                      <span className="label">Cost Basis:</span>
                      <span className="value">{formatCurrency(pos.cost_basis)}</span>
                    </div>
                    <div className="detail-row">
                      <span className="label">Bid/Ask:</span>
                      <span className="value">
                        {formatCurrency(pos.bid_price)} / {formatCurrency(pos.ask_price)}
                      </span>
                    </div>
                    {pos.pe_ratio && (
                      <div className="detail-row">
                        <span className="label">P/E Ratio:</span>
                        <span className="value">{pos.pe_ratio}</span>
                      </div>
                    )}
                    {pos.market_cap && (
                      <div className="detail-row">
                        <span className="label">Market Cap:</span>
                        <span className="value">{pos.market_cap}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Last Updated */}
      <div className="last-updated">
        Last updated: {new Date(portfolio.timestamp).toLocaleTimeString()}
      </div>
    </div>
  );
};

export default PortfolioPanel;
