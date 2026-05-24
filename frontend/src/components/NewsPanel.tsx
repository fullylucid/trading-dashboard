/**
 * NewsPanel Component
 * Displays real-time market news with filtering and search
 */

import React, { useState, useEffect } from 'react';
import './NewsPanel.css';

interface NewsArticle {
  id: string;
  title: string;
  summary: string;
  source: string;
  url: string;
  published_at: string;
  category: string;
  symbols: string[];
  sentiment?: string;
  impact_score: number;
}

interface NewsPanelProps {
  symbol?: string;
  category?: 'market' | 'sector' | 'earnings' | 'ipo' | 'merger';
  limit?: number;
}

const NewsPanel: React.FC<NewsPanelProps> = ({
  symbol,
  category = 'market',
  limit = 20,
}) => {
  const [articles, setArticles] = useState<NewsArticle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterCategory, setFilterCategory] = useState(category);
  const [sortBy, setSortBy] = useState<'date' | 'impact'>('date');

  useEffect(() => {
    fetchNews();
  }, [symbol, filterCategory, limit]);

  const fetchNews = async () => {
    setLoading(true);
    setError(null);
    try {
      let endpoint = '/api/news/market';

      if (symbol) {
        endpoint = `/api/news/symbol/${symbol}`;
      } else if (filterCategory) {
        endpoint = `/api/news/category/${filterCategory}`;
      }

      const response = await fetch(`${endpoint}?limit=${limit}`);
      if (!response.ok) throw new Error('Failed to fetch news');

      const data = await response.json();
      const sorted = sortArticles(data, sortBy);
      setArticles(sorted);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const sortArticles = (
    articles: NewsArticle[],
    sortType: 'date' | 'impact'
  ): NewsArticle[] => {
    return [...articles].sort((a, b) => {
      if (sortType === 'date') {
        return new Date(b.published_at).getTime() - new Date(a.published_at).getTime();
      } else {
        return b.impact_score - a.impact_score;
      }
    });
  };

  const handleSortChange = (newSort: 'date' | 'impact') => {
    setSortBy(newSort);
    setArticles(sortArticles(articles, newSort));
  };

  const getSentimentColor = (sentiment?: string): string => {
    switch (sentiment) {
      case 'positive':
        return 'sentiment-positive';
      case 'negative':
        return 'sentiment-negative';
      default:
        return 'sentiment-neutral';
    }
  };

  const formatDate = (dateStr: string): string => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;

    return date.toLocaleDateString();
  };

  return (
    <div className="news-panel">
      <div className="news-panel-header">
        <h2>{symbol ? `${symbol} News` : 'Market News'}</h2>
        <div className="news-controls">
          {!symbol && (
            <select
              value={filterCategory}
              onChange={(e) => setFilterCategory(e.target.value as any)}
              className="category-select"
            >
              <option value="market">Market</option>
              <option value="earnings">Earnings</option>
              <option value="ipo">IPO</option>
              <option value="merger">Merger</option>
            </select>
          )}

          <select
            value={sortBy}
            onChange={(e) => handleSortChange(e.target.value as 'date' | 'impact')}
            className="sort-select"
          >
            <option value="date">Latest</option>
            <option value="impact">Most Impactful</option>
          </select>
        </div>
      </div>

      {loading && <div className="news-loading">Loading news...</div>}

      {error && <div className="news-error">Error: {error}</div>}

      {!loading && !error && articles.length === 0 && (
        <div className="news-empty">No articles found</div>
      )}

      <div className="news-list">
        {articles.map((article) => (
          <div
            key={article.id}
            className={`news-item ${getSentimentColor(article.sentiment)}`}
          >
            <div className="news-item-header">
              <h3>
                <a href={article.url} target="_blank" rel="noopener noreferrer">
                  {article.title}
                </a>
              </h3>
              <div className="news-meta">
                <span className="news-source">{article.source}</span>
                <span className="news-time">{formatDate(article.published_at)}</span>
              </div>
            </div>

            <p className="news-summary">{article.summary}</p>

            <div className="news-footer">
              <div className="news-symbols">
                {article.symbols.map((sym) => (
                  <span key={sym} className="symbol-badge">
                    {sym}
                  </span>
                ))}
              </div>
              <div className="news-impact">
                Impact: {(article.impact_score * 100).toFixed(0)}%
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default NewsPanel;
