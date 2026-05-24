/**
 * EnhancedDashboard.tsx - Unified trading dashboard with signals + research
 * 
 * Layout:
 * - Top: Market overview (indices, VIX)
 * - Left: Signals feed + news
 * - Right: Research panels (earnings, sectors, market data)
 * - Bottom: Detailed analysis views
 */

import React, { useState, useEffect } from 'react';
import './EnhancedDashboard.css';

// Types
interface Signal {
    id: string;
    symbol: string;
    score: number;
    catalyst: string;
    entry: number;
    stop: number;
    target: number;
    risk_reward: string;
    scanners: { [key: string]: number };
    timestamp: string;
    news_count: number;
}

interface NewsArticle {
    title: string;
    summary: string;
    source: string;
    sentiment: 'positive' | 'negative' | 'neutral';
    url: string;
    timestamp: string;
}

interface EarningsEvent {
    symbol: string;
    date: string;
    eps_estimate: number;
    eps_actual?: number;
    revenue_estimate: number;
    sector: string;
    surprise_pct?: number;
}

interface Sector {
    name: string;
    change_percent: number;
    performance: 'outperform' | 'underperform';
}

interface MarketOverview {
    indices: { [key: string]: { price: number; change_percent: number } };
    market_time: 'open' | 'closed';
}

// Main Dashboard Component
export const EnhancedDashboard: React.FC = () => {
    const [signals, setSignals] = useState<Signal[]>([]);
    const [news, setNews] = useState<NewsArticle[]>([]);
    const [earnings, setEarnings] = useState<EarningsEvent[]>([]);
    const [sectors, setSectors] = useState<Sector[]>([]);
    const [marketOverview, setMarketOverview] = useState<MarketOverview | null>(null);
    const [selectedSignal, setSelectedSignal] = useState<Signal | null>(null);
    const [loading, setLoading] = useState(true);

    // Fetch all data on mount
    useEffect(() => {
        const fetchData = async () => {
            try {
                setLoading(true);
                
                // Fetch signals
                const signalsRes = await fetch('/api/signals');
                const signalsData = await signalsRes.json();
                setSignals(signalsData.signals || []);
                
                // Fetch market overview
                const overviewRes = await fetch('/api/research/market/overview');
                const overviewData = await overviewRes.json();
                setMarketOverview(overviewData);
                
                // Fetch sector performance
                const sectorsRes = await fetch('/api/research/market/sectors');
                const sectorsData = await sectorsRes.json();
                setSectors(Object.entries(sectorsData.sectors || {}).map(([name, data]: any) => ({
                    name,
                    change_percent: data.change_percent,
                    performance: data.change_percent >= 0 ? 'outperform' : 'underperform'
                })));
                
                // Fetch earnings calendar
                const earningsRes = await fetch('/api/research/earnings/calendar?days=30&limit=20');
                const earningsData = await earningsRes.json();
                setEarnings(earningsData.earnings || []);
                
                setLoading(false);
            } catch (error) {
                console.error('Error fetching dashboard data:', error);
                setLoading(false);
            }
        };

        fetchData();
        
        // Refresh every 60 seconds
        const interval = setInterval(fetchData, 60000);
        return () => clearInterval(interval);
    }, []);

    // Fetch symbol-specific news when signal is selected
    useEffect(() => {
        if (selectedSignal) {
            const fetchNews = async () => {
                try {
                    const res = await fetch(`/api/research/news/${selectedSignal.symbol}?limit=5`);
                    const data = await res.json();
                    setNews(data.articles || []);
                } catch (error) {
                    console.error('Error fetching news:', error);
                }
            };
            fetchNews();
        }
    }, [selectedSignal]);

    if (loading) {
        return <div className="dashboard-loading">Loading dashboard...</div>;
    }

    return (
        <div className="enhanced-dashboard">
            {/* Header: Market Overview */}
            <MarketOverviewPanel data={marketOverview} />
            
            <div className="dashboard-content">
                {/* Left Column: Signals & Related News */}
                <div className="left-column">
                    <SignalFeed 
                        signals={signals} 
                        selectedSignal={selectedSignal}
                        onSelectSignal={setSelectedSignal}
                    />
                    
                    {selectedSignal && (
                        <NewsPanel symbol={selectedSignal.symbol} articles={news} />
                    )}
                </div>
                
                {/* Right Column: Research Panels */}
                <div className="right-column">
                    <SectorPerformancePanel sectors={sectors} />
                    <EarningsCalendarPanel earnings={earnings} />
                </div>
            </div>
            
            {/* Detail Panel */}
            {selectedSignal && (
                <SignalDetailPanel signal={selectedSignal} />
            )}
        </div>
    );
};

// Market Overview Panel - Header
interface MarketOverviewPanelProps {
    data: MarketOverview | null;
}

const MarketOverviewPanel: React.FC<MarketOverviewPanelProps> = ({ data }) => {
    if (!data) return null;

    const indices = ['SPY', 'QQQ', 'IWM', 'VIX'].map(symbol => ({
        symbol,
        ...(data.indices[symbol] || { price: 0, change_percent: 0 })
    }));

    return (
        <div className="market-overview-panel">
            <div className="market-status">
                <span className={`status-badge ${data.market_time}`}>
                    Market {data.market_time === 'open' ? '🟢 OPEN' : '⚫ CLOSED'}
                </span>
            </div>
            
            <div className="indices-grid">
                {indices.map(index => (
                    <div key={index.symbol} className="index-card">
                        <div className="symbol">{index.symbol}</div>
                        <div className="price">${index.price?.toFixed(2) || 'N/A'}</div>
                        <div className={`change ${index.change_percent >= 0 ? 'positive' : 'negative'}`}>
                            {index.change_percent >= 0 ? '↑' : '↓'} {Math.abs(index.change_percent).toFixed(2)}%
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

// Signal Feed Component
interface SignalFeedProps {
    signals: Signal[];
    selectedSignal: Signal | null;
    onSelectSignal: (signal: Signal) => void;
}

const SignalFeed: React.FC<SignalFeedProps> = ({ signals, selectedSignal, onSelectSignal }) => {
    return (
        <div className="signal-feed">
            <h2>🔍 Signal Feed</h2>
            <div className="signals-list">
                {signals.slice(0, 10).map(signal => (
                    <div 
                        key={signal.id}
                        className={`signal-card ${selectedSignal?.id === signal.id ? 'selected' : ''}`}
                        onClick={() => onSelectSignal(signal)}
                    >
                        <div className="signal-header">
                            <span className="ticker">{signal.symbol}</span>
                            <span className="score-badge">{signal.score}/100</span>
                        </div>
                        
                        <div className="signal-body">
                            <div className="catalyst">{signal.catalyst}</div>
                            
                            <div className="price-levels">
                                <div className="level">
                                    <span className="label">Entry:</span>
                                    <span className="value">${signal.entry?.toFixed(2)}</span>
                                </div>
                                <div className="level">
                                    <span className="label">Stop:</span>
                                    <span className="value stop">${signal.stop?.toFixed(2)}</span>
                                </div>
                                <div className="level">
                                    <span className="label">Target:</span>
                                    <span className="value target">${signal.target?.toFixed(2)}</span>
                                </div>
                            </div>
                            
                            <div className="risk-reward">
                                Risk/Reward: {signal.risk_reward}
                            </div>
                            
                            <div className="score-bar">
                                <div className="bar-fill" style={{ width: `${signal.score}%` }}></div>
                            </div>
                        </div>
                        
                        <div className="signal-footer">
                            <span className="news-indicator">📰 {signal.news_count} articles</span>
                            <span className="timestamp">{new Date(signal.timestamp).toLocaleTimeString()}</span>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

// News Panel Component
interface NewsPanelProps {
    symbol: string;
    articles: NewsArticle[];
}

const NewsPanel: React.FC<NewsPanelProps> = ({ symbol, articles }) => {
    return (
        <div className="news-panel">
            <h3>📰 News: {symbol}</h3>
            <div className="news-list">
                {articles.map((article, i) => (
                    <div key={i} className={`news-item sentiment-${article.sentiment}`}>
                        <div className="news-header">
                            <span className="source">{article.source}</span>
                            <span className={`sentiment-badge ${article.sentiment}`}>
                                {article.sentiment === 'positive' ? '📈' : article.sentiment === 'negative' ? '📉' : '➡️'}
                            </span>
                        </div>
                        <h4>{article.title}</h4>
                        <p>{article.summary}</p>
                        <a href={article.url} target="_blank" rel="noopener noreferrer">Read more →</a>
                    </div>
                ))}
            </div>
        </div>
    );
};

// Sector Performance Component
interface SectorPerformancePanelProps {
    sectors: Sector[];
}

const SectorPerformancePanel: React.FC<SectorPerformancePanelProps> = ({ sectors }) => {
    return (
        <div className="sector-performance-panel">
            <h3>📊 Sector Performance</h3>
            <div className="sectors-grid">
                {sectors.slice(0, 5).map((sector, i) => (
                    <div key={i} className={`sector-card ${sector.performance}`}>
                        <div className="sector-name">{sector.name}</div>
                        <div className={`sector-change ${sector.performance}`}>
                            {sector.change_percent >= 0 ? '+' : ''}{sector.change_percent.toFixed(2)}%
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

// Earnings Calendar Component
interface EarningsCalendarPanelProps {
    earnings: EarningsEvent[];
}

const EarningsCalendarPanel: React.FC<EarningsCalendarPanelProps> = ({ earnings }) => {
    return (
        <div className="earnings-calendar-panel">
            <h3>📅 Upcoming Earnings</h3>
            <div className="earnings-table">
                {earnings.slice(0, 8).map((earning, i) => (
                    <div key={i} className="earnings-row">
                        <div className="symbol">{earning.symbol}</div>
                        <div className="date">{new Date(earning.date).toLocaleDateString()}</div>
                        <div className="estimates">
                            <span>EPS: ${earning.eps_estimate?.toFixed(2)}</span>
                            <span>Rev: ${earning.revenue_estimate?.toFixed(1)}B</span>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

// Signal Detail Panel (Bottom/Modal)
interface SignalDetailPanelProps {
    signal: Signal;
}

const SignalDetailPanel: React.FC<SignalDetailPanelProps> = ({ signal }) => {
    return (
        <div className="signal-detail-panel">
            <h2>📊 {signal.symbol} - Detailed Analysis</h2>
            
            <div className="detail-sections">
                <div className="section scanner-breakdown">
                    <h3>Scanner Breakdown</h3>
                    <div className="scanners-grid">
                        {Object.entries(signal.scanners).map(([name, weight]) => (
                            <div key={name} className="scanner-item">
                                <div className="scanner-name">{name}</div>
                                <div className="scanner-weight" style={{ height: `${weight * 100}%` }}></div>
                                <div className="scanner-value">{weight.toFixed(2)}</div>
                            </div>
                        ))}
                    </div>
                </div>
                
                <div className="section trading-levels">
                    <h3>Trading Levels</h3>
                    <table>
                        <tbody>
                            <tr>
                                <td>Entry</td>
                                <td className="value">${signal.entry?.toFixed(2)}</td>
                            </tr>
                            <tr>
                                <td>Stop Loss</td>
                                <td className="value stop">${signal.stop?.toFixed(2)}</td>
                            </tr>
                            <tr>
                                <td>Target</td>
                                <td className="value target">${signal.target?.toFixed(2)}</td>
                            </tr>
                            <tr>
                                <td>Risk/Reward</td>
                                <td className="value">{signal.risk_reward}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
};

export default EnhancedDashboard;
