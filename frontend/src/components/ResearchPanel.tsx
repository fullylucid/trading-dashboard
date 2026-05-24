/**
 * ResearchPanel Component
 * Displays AI-generated research summaries, analyst sentiment, and insights
 */

import React, { useState, useEffect } from 'react';
import './ResearchPanel.css';

interface ResearchSummary {
  symbol: string;
  title: string;
  summary: string;
  key_points: string[];
  sentiment: 'bullish' | 'bearish' | 'neutral';
  confidence: number;
  generated_at: string;
  source_url?: string;
}

interface ResearchPanelProps {
  symbol: string;
  reportContent?: string;
}

const ResearchPanel: React.FC<ResearchPanelProps> = ({ symbol, reportContent }) => {
  const [research, setResearch] = useState<ResearchSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [earnings, setEarnings] = useState<any>(null);
  const [sentiment, setSentiment] = useState<any>(null);
  const [activeTab, setActiveTab] = useState<'summary' | 'earnings' | 'sentiment'>(
    'summary'
  );

  useEffect(() => {
    if (reportContent) {
      generateSummary();
    }
  }, [symbol, reportContent]);

  const generateSummary = async () => {
    if (!reportContent) return;

    setLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/research/summarize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol,
          content: reportContent,
          title: `Research Report - ${symbol}`,
        }),
      });

      if (!response.ok) throw new Error('Failed to generate summary');
      const data = await response.json();
      setResearch(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const analyzeEarnings = async () => {
    if (!reportContent) return;

    try {
      const response = await fetch('/api/research/earnings-analysis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol,
          content: reportContent,
        }),
      });

      if (!response.ok) throw new Error('Failed to analyze earnings');
      const data = await response.json();
      setEarnings(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const analyzeSentiment = async () => {
    if (!reportContent) return;

    try {
      const response = await fetch('/api/research/sentiment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: reportContent,
          symbols: [symbol],
        }),
      });

      if (!response.ok) throw new Error('Failed to analyze sentiment');
      const data = await response.json();
      setSentiment(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const getSentimentColor = (sentiment: string): string => {
    switch (sentiment) {
      case 'bullish':
        return 'bullish';
      case 'bearish':
        return 'bearish';
      default:
        return 'neutral';
    }
  };

  const getSentimentIcon = (sentiment: string): string => {
    switch (sentiment) {
      case 'bullish':
        return '📈';
      case 'bearish':
        return '📉';
      default:
        return '➡️';
    }
  };

  return (
    <div className="research-panel">
      <div className="research-header">
        <h2>Research & Analysis</h2>
        <p className="research-symbol">{symbol}</p>
      </div>

      {error && <div className="research-error">Error: {error}</div>}

      <div className="research-tabs">
        <button
          className={`tab ${activeTab === 'summary' ? 'active' : ''}`}
          onClick={() => {
            setActiveTab('summary');
            if (!research) generateSummary();
          }}
        >
          Summary
        </button>
        <button
          className={`tab ${activeTab === 'earnings' ? 'active' : ''}`}
          onClick={() => {
            setActiveTab('earnings');
            if (!earnings) analyzeEarnings();
          }}
        >
          Earnings
        </button>
        <button
          className={`tab ${activeTab === 'sentiment' ? 'active' : ''}`}
          onClick={() => {
            setActiveTab('sentiment');
            if (!sentiment) analyzeSentiment();
          }}
        >
          Sentiment
        </button>
      </div>

      <div className="research-content">
        {activeTab === 'summary' && (
          <div className="research-summary-view">
            {loading && <div className="research-loading">Generating summary...</div>}

            {research && (
              <div className="summary-container">
                <div className={`sentiment-badge ${getSentimentColor(research.sentiment)}`}>
                  <span className="sentiment-icon">{getSentimentIcon(research.sentiment)}</span>
                  <span className="sentiment-text">{research.sentiment.toUpperCase()}</span>
                  <span className="confidence">
                    {(research.confidence * 100).toFixed(0)}%
                  </span>
                </div>

                <h3>{research.title}</h3>

                <div className="summary-text">{research.summary}</div>

                <div className="key-points">
                  <h4>Key Points</h4>
                  <ul>
                    {research.key_points.map((point, idx) => (
                      <li key={idx}>{point}</li>
                    ))}
                  </ul>
                </div>

                <div className="generated-info">
                  Generated: {new Date(research.generated_at).toLocaleString()}
                </div>
              </div>
            )}

            {!loading && !research && (
              <div className="research-empty">
                No summary available. Upload a report to analyze.
              </div>
            )}
          </div>
        )}

        {activeTab === 'earnings' && (
          <div className="research-earnings-view">
            {earnings && (
              <div className="earnings-analysis">
                <div className="analysis-section">
                  <h4>Revenue Outlook</h4>
                  <p>{earnings.revenue_outlook}</p>
                </div>

                <div className="analysis-section">
                  <h4>Margin Analysis</h4>
                  <p>{earnings.margin_analysis}</p>
                </div>

                <div className="analysis-section">
                  <h4>Management Guidance</h4>
                  <p>{earnings.guidance}</p>
                </div>

                <div className="analysis-lists">
                  <div>
                    <h4>Risks</h4>
                    <ul>
                      {earnings.risks?.map((risk: string, idx: number) => (
                        <li key={idx}>{risk}</li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <h4>Opportunities</h4>
                    <ul>
                      {earnings.opportunities?.map((opp: string, idx: number) => (
                        <li key={idx}>{opp}</li>
                      ))}
                    </ul>
                  </div>
                </div>

                <div className={`overall-sentiment ${getSentimentColor(earnings.overall_sentiment)}`}>
                  Overall: {earnings.overall_sentiment}
                </div>
              </div>
            )}

            {!earnings && (
              <div className="research-empty">No earnings analysis available</div>
            )}
          </div>
        )}

        {activeTab === 'sentiment' && (
          <div className="research-sentiment-view">
            {sentiment && (
              <div className="sentiment-analysis">
                <div className={`sentiment-result ${getSentimentColor(sentiment[symbol])}`}>
                  <div className="sentiment-value">
                    {getSentimentIcon(sentiment[symbol])}
                  </div>
                  <div className="sentiment-label">
                    {sentiment[symbol]?.toUpperCase()}
                  </div>
                </div>

                <div className="sentiment-explanation">
                  The analysis indicates a {sentiment[symbol]} outlook based on the provided
                  content.
                </div>
              </div>
            )}

            {!sentiment && (
              <div className="research-empty">No sentiment analysis available</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default ResearchPanel;
