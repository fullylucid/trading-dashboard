/**
 * ComprehensiveDashboard Component
 * Main dashboard layout integrating all research, news, and market components
 */

import React, { useState, useEffect } from 'react';
import NewsPanel from './NewsPanel';
import EarningsCalendar from './EarningsCalendar';
import ResearchPanel from './ResearchPanel';
import MarketStats from './MarketStats';
import './ComprehensiveDashboard.css';

interface DashboardConfig {
  symbol?: string;
  sector?: string;
  showAllPanels?: boolean;
}

const ComprehensiveDashboard: React.FC<DashboardConfig> = ({
  symbol,
  sector,
  showAllPanels = true,
}) => {
  const [selectedSymbol, setSelectedSymbol] = useState<string>(symbol || '');
  const [activePanel, setActivePanel] = useState<
    'overview' | 'symbol' | 'earnings' | 'research'
  >('overview');
  const [reportContent, setReportContent] = useState<string>('');
  const [layout, setLayout] = useState<'grid' | 'list'>('grid');

  const handleSymbolSearch = (sym: string) => {
    setSelectedSymbol(sym.toUpperCase());
    setActivePanel('symbol');
  };

  const handleReportUpload = (content: string) => {
    setReportContent(content);
  };

  return (
    <div className="comprehensive-dashboard">
      {/* Header */}
      <header className="dashboard-header">
        <div className="header-content">
          <h1>📊 Trading Research Dashboard</h1>
          <p className="tagline">Market Intelligence • Research • News • Earnings</p>
        </div>

        <div className="header-controls">
          <div className="search-bar">
            <input
              type="text"
              placeholder="Search symbol (e.g., AAPL)"
              value={selectedSymbol}
              onChange={(e) => setSelectedSymbol(e.target.value.toUpperCase())}
              onKeyPress={(e) => {
                if (e.key === 'Enter') {
                  handleSymbolSearch(selectedSymbol);
                }
              }}
              className="search-input"
            />
            <button
              onClick={() => handleSymbolSearch(selectedSymbol)}
              className="search-button"
            >
              Search
            </button>
          </div>

          <div className="layout-controls">
            <button
              className={`layout-btn ${layout === 'grid' ? 'active' : ''}`}
              onClick={() => setLayout('grid')}
              title="Grid Layout"
            >
              ⊞
            </button>
            <button
              className={`layout-btn ${layout === 'list' ? 'active' : ''}`}
              onClick={() => setLayout('list')}
              title="List Layout"
            >
              ≡
            </button>
          </div>
        </div>
      </header>

      {/* Navigation */}
      <nav className="dashboard-nav">
        <button
          className={`nav-item ${activePanel === 'overview' ? 'active' : ''}`}
          onClick={() => setActivePanel('overview')}
        >
          📈 Overview
        </button>
        <button
          className={`nav-item ${activePanel === 'symbol' ? 'active' : ''}`}
          onClick={() => setActivePanel('symbol')}
          disabled={!selectedSymbol}
        >
          🔍 {selectedSymbol || 'Symbol'}
        </button>
        <button
          className={`nav-item ${activePanel === 'earnings' ? 'active' : ''}`}
          onClick={() => setActivePanel('earnings')}
        >
          📅 Earnings
        </button>
        <button
          className={`nav-item ${activePanel === 'research' ? 'active' : ''}`}
          onClick={() => setActivePanel('research')}
          disabled={!selectedSymbol || !reportContent}
        >
          🔬 Research
        </button>
      </nav>

      {/* Main Content Area */}
      <main className="dashboard-main">
        {/* Overview Panel - Shows all market data */}
        {activePanel === 'overview' && (
          <div className={`panel market-overview-panel ${layout}`}>
            <MarketStats />
            <div className="dashboard-grid">
              <div className="grid-item news-item">
                <NewsPanel limit={10} category="market" />
              </div>
              <div className="grid-item earnings-item">
                <EarningsCalendar daysAhead={30} limit={15} showHistory={false} />
              </div>
            </div>
          </div>
        )}

        {/* Symbol-Specific Panel */}
        {activePanel === 'symbol' && selectedSymbol && (
          <div className={`panel symbol-panel ${layout}`}>
            <div className="symbol-header">
              <h2>{selectedSymbol}</h2>
              <p>Company Research & Analysis</p>
            </div>

            <div className="symbol-grid">
              <div className="grid-item news-item">
                <NewsPanel symbol={selectedSymbol} limit={15} />
              </div>

              <div className="grid-item earnings-item">
                <EarningsCalendar
                  symbol={selectedSymbol}
                  showHistory={true}
                  limit={8}
                />
              </div>

              <div className="grid-item research-item">
                <div className="report-upload">
                  <h3>Upload Research Report</h3>
                  <textarea
                    placeholder="Paste research report, earnings transcript, or company analysis here..."
                    value={reportContent}
                    onChange={(e) => handleReportUpload(e.target.value)}
                    rows={6}
                    className="report-textarea"
                  />
                  <div className="upload-hint">
                    Paste report content to get AI-powered analysis with Kimi K
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Earnings Calendar Panel */}
        {activePanel === 'earnings' && (
          <div className={`panel earnings-calendar-panel ${layout}`}>
            <EarningsCalendar daysAhead={90} limit={200} showHistory={false} />
          </div>
        )}

        {/* Research Panel - Shows AI analysis */}
        {activePanel === 'research' && selectedSymbol && reportContent && (
          <div className={`panel research-analysis-panel ${layout}`}>
            <ResearchPanel symbol={selectedSymbol} reportContent={reportContent} />
          </div>
        )}

        {/* Empty State */}
        {activePanel === 'research' && (!selectedSymbol || !reportContent) && (
          <div className="panel empty-state">
            <div className="empty-content">
              <h3>Research & Analysis</h3>
              <p>
                {!selectedSymbol
                  ? 'Please select a symbol first'
                  : 'Please upload a research report to analyze'}
              </p>
            </div>
          </div>
        )}
      </main>

      {/* Sidebar - Quick Stats */}
      <aside className="dashboard-sidebar">
        <div className="sidebar-section">
          <h3>Quick Links</h3>
          <ul>
            <li>
              <a href="#market-news">Market News</a>
            </li>
            <li>
              <a href="#earnings">Earnings Calendar</a>
            </li>
            <li>
              <a href="#research">Research</a>
            </li>
            <li>
              <a href="#analysis">Analysis Tools</a>
            </li>
          </ul>
        </div>

        <div className="sidebar-section">
          <h3>Market Status</h3>
          <div className="status-widget">
            <div className="status-item">
              <span>Market Hours</span>
              <span>9:30 AM - 4:00 PM EST</span>
            </div>
            <div className="status-item">
              <span>Pre-market</span>
              <span>4:00 AM - 9:30 AM EST</span>
            </div>
            <div className="status-item">
              <span>After-hours</span>
              <span>4:00 PM - 8:00 PM EST</span>
            </div>
          </div>
        </div>

        <div className="sidebar-section">
          <h3>Features</h3>
          <div className="features-list">
            <div className="feature">✓ Real-time News</div>
            <div className="feature">✓ Earnings Calendar</div>
            <div className="feature">✓ AI Research (Kimi K)</div>
            <div className="feature">✓ Sentiment Analysis</div>
            <div className="feature">✓ Market Breadth</div>
            <div className="feature">✓ Sector Performance</div>
          </div>
        </div>
      </aside>

      {/* Footer */}
      <footer className="dashboard-footer">
        <div className="footer-content">
          <p>
            Trading Research Dashboard • Powered by FastAPI & React
          </p>
          <p className="footer-note">
            Data delayed 15 minutes. Not financial advice. Use at your own risk.
          </p>
        </div>
      </footer>
    </div>
  );
};

export default ComprehensiveDashboard;
