import React, { useState, useEffect } from 'react';

// Type definitions
interface Quote {
  price: number;
  change_pct: number;
  volume: number;
}

interface Scores {
  technical: number;
  projection: number;
  narrative: number;
  combined: number;
}

interface Breakdown {
  technical: {
    score: number;
    reason: string;
  };
  projection: {
    score: number;
    reason: string;
  };
  narrative: {
    score: number;
    reason: string;
  };
}

interface Projection {
  bear: number;
  base: number;
  bull: number;
  current_price: number;
  upside_base_pct: number;
}

interface Narrative {
  sector: string;
  tam_b: number;
  x_bagger_base: number;
  x_bagger_bull: number;
  story_strength: string;
}

interface NewsItem {
  headline: string;
  url: string;
  ts: string;
}

interface DeepDiveData {
  symbol: string;
  timestamp: string;
  quote: Quote | null;
  composite_score: number;
  verdict: string;
  scores: Scores;
  breakdown: Breakdown;
  projection: Projection;
  narrative: Narrative;
  news: NewsItem[];
  thesis_markdown: string;
  thesis_model: string;
  warnings: string[];
}

interface TickerDeepDiveProps {
  symbol: string;
  onClose?: () => void;
  compact?: boolean;
}

const TickerDeepDive: React.FC<TickerDeepDiveProps> = ({ symbol, onClose, compact = false }) => {
  const [data, setData] = useState<DeepDiveData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    verdict: true,
    scores: true,
    projections: true,
    narrative: true,
    thesis: true,
    news: false, // Collapsed by default
  });

  // Fetch data when symbol changes
  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        setError(null);
        const response = await fetch(`/api/research/deep/${symbol}`);
        if (!response.ok) {
          throw new Error(`Failed to fetch data: ${response.status} ${response.statusText}`);
        }
        const result = await response.json();
        setData(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An error occurred');
      } finally {
        setLoading(false);
      }
    };

    if (symbol) {
      fetchData();
    }
  }, [symbol]);

  // Toggle section expansion
  const toggleSection = (section: string) => {
    setExpandedSections(prev => ({
      ...prev,
      [section]: !prev[section]
    }));
  };

  // Render markdown-like content with simple regex
  const renderMarkdown = (markdown: string) => {
    // Convert headers
    let content = markdown.replace(/^## (.*$)/gm, '<h2 class="text-xl font-bold mt-4 mb-2">$1</h2>');
    content = content.replace(/^### (.*$)/gm, '<h3 class="text-lg font-bold mt-3 mb-1">$1</h3>');
    
    // Convert bold
    content = content.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    
    // Convert lists
    content = content.replace(/^- (.*$)/gm, '<li class="ml-4">$1</li>');
    content = content.replace(/(<li.*<\/li>)/gs, '<ul class="list-disc my-2">$1</ul>');
    
    // Convert paragraphs
    content = content.replace(/^\s*(.*?)(?=\n|$)/gm, '<p class="my-2">$1</p>');
    
    // Remove extra newlines
    content = content.replace(/\n{2,}/g, '</p><p class="my-2">');
    
    return <div dangerouslySetInnerHTML={{ __html: content }} />;
  };

  // Get verdict color
  const getVerdictColor = (verdict: string) => {
    switch (verdict) {
      case 'Strong Buy': return 'bg-emerald-900 text-emerald-100';
      case 'Buy': return 'bg-green-900 text-green-100';
      case 'Hold': return 'bg-gray-700 text-gray-100';
      case 'Trim': return 'bg-orange-900 text-orange-100';
      case 'Avoid': return 'bg-red-900 text-red-100';
      default: return 'bg-gray-700 text-gray-100';
    }
  };

  // Render progress bar
  const renderProgressBar = (value: number, max: number = 10, color: string) => {
    const percentage = Math.min(100, Math.max(0, (value / max) * 100));
    return (
      <div className="w-full bg-gray-700 rounded-full h-2.5">
        <div 
          className={`h-2.5 rounded-full ${color}`} 
          style={{ width: `${percentage}%` }}
        ></div>
      </div>
    );
  };

  // Render score card
  const renderScoreCard = (label: string, score: number, reason: string, color: string) => (
    <div className="mb-4">
      <div className="flex justify-between mb-1">
        <span className="font-medium">{label}</span>
        <span>{score.toFixed(1)}/10</span>
      </div>
      {renderProgressBar(score, 10, color)}
      <div className="text-sm text-gray-400 mt-1">{reason || 'No reason provided'}</div>
    </div>
  );

  // Render projection card
  const renderProjectionCard = (label: string, price: number, isBase: boolean = false) => {
    if (!data?.quote) return null;
    
    const currentPrice = data.quote.price;
    const change = price - currentPrice;
    const changePercent = currentPrice > 0 ? (change / currentPrice) * 100 : 0;
    
    return (
      <div className={`p-4 rounded-lg border ${isBase ? 'border-blue-500 bg-blue-900/20' : 'border-gray-700'}`}>
        <div className="text-lg font-bold">{label}</div>
        <div className="text-2xl font-mono my-2">${price.toFixed(2)}</div>
        <div className={`text-sm ${change >= 0 ? 'text-green-400' : 'text-red-400'}`}>
          {change >= 0 ? '+' : ''}{change.toFixed(2)} ({changePercent.toFixed(1)}%)
        </div>
      </div>
    );
  };

  if (loading) {
    return (
      <div className={`bg-gray-800 rounded-lg p-4 ${compact ? '' : 'border border-gray-700'}`}>
        <div className="flex justify-center items-center h-32">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={`bg-gray-800 rounded-lg p-4 ${compact ? '' : 'border border-gray-700'}`}>
        <div className="text-red-400 text-center py-4">
          Error loading data: {error}
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className={`bg-gray-800 rounded-lg p-4 ${compact ? '' : 'border border-gray-700'}`}>
        <div className="text-center py-4">
          No data available
        </div>
      </div>
    );
  }

  return (
    <div className={`bg-gray-800 rounded-lg ${compact ? '' : 'border border-gray-700'} text-gray-100`}>
      {/* Header */}
      {!compact && (
        <div className="flex justify-between items-center p-4 border-b border-gray-700">
          <h2 className="text-xl font-bold">Deep Dive: {data.symbol}</h2>
          {onClose && (
            <button 
              onClick={onClose}
              className="text-gray-400 hover:text-white"
              aria-label="Close"
            >
              ✕
            </button>
          )}
        </div>
      )}

      {/* Warnings */}
      {data.warnings.length > 0 && (
        <div className="bg-yellow-900/30 border border-yellow-700 rounded-lg p-3 m-4">
          <div className="font-bold text-yellow-300 mb-1">Warnings</div>
          <ul className="list-disc pl-5 text-sm">
            {data.warnings.map((warning, i) => (
              <li key={i}>{warning}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Verdict & Composite Score */}
      <div className="p-4 border-b border-gray-700">
        <div 
          className="flex justify-between items-center cursor-pointer"
          onClick={() => toggleSection('verdict')}
        >
          <h3 className="text-lg font-bold">Verdict & Composite Score</h3>
          <span>{expandedSections.verdict ? '▼' : '▶'}</span>
        </div>
        
        {expandedSections.verdict && (
          <div className="mt-3">
            <div className={`inline-block px-4 py-2 rounded-full font-bold ${getVerdictColor(data.verdict)}`}>
              {data.verdict}
            </div>
            <div className="mt-4">
              <div className="flex justify-between mb-1">
                <span className="font-medium">Composite Score</span>
                <span>{data.composite_score.toFixed(1)}/10</span>
              </div>
              {renderProgressBar(data.composite_score, 10, 'bg-blue-500')}
            </div>
          </div>
        )}
      </div>

      {/* Score Breakdown */}
      <div className="p-4 border-b border-gray-700">
        <div 
          className="flex justify-between items-center cursor-pointer"
          onClick={() => toggleSection('scores')}
        >
          <h3 className="text-lg font-bold">Score Breakdown</h3>
          <span>{expandedSections.scores ? '▼' : '▶'}</span>
        </div>
        
        {expandedSections.scores && (
          <div className="mt-3">
            {renderScoreCard(
              'Technical', 
              data.scores.technical, 
              data.breakdown.technical.reason, 
              'bg-green-500'
            )}
            {renderScoreCard(
              'DCF Projection', 
              data.scores.projection, 
              data.breakdown.projection.reason, 
              'bg-blue-500'
            )}
            {renderScoreCard(
              'Narrative', 
              data.scores.narrative, 
              data.breakdown.narrative.reason || 'Narrative leg unavailable', 
              'bg-purple-500'
            )}
          </div>
        )}
      </div>

      {/* DCF Projections */}
      <div className="p-4 border-b border-gray-700">
        <div 
          className="flex justify-between items-center cursor-pointer"
          onClick={() => toggleSection('projections')}
        >
          <h3 className="text-lg font-bold">DCF Projections</h3>
          <span>{expandedSections.projections ? '▼' : '▶'}</span>
        </div>
        
        {expandedSections.projections && data.projection && (
          <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-4">
            {renderProjectionCard('Bear Case', data.projection.bear)}
            {renderProjectionCard('Base Case', data.projection.base, true)}
            {renderProjectionCard('Bull Case', data.projection.bull)}
          </div>
        )}
      </div>

      {/* Narrative / X-Bagger */}
      <div className="p-4 border-b border-gray-700">
        <div 
          className="flex justify-between items-center cursor-pointer"
          onClick={() => toggleSection('narrative')}
        >
          <h3 className="text-lg font-bold">Narrative / X-Bagger</h3>
          <span>{expandedSections.narrative ? '▼' : '▶'}</span>
        </div>
        
        {expandedSections.narrative && data.narrative && (
          <div className="mt-3 grid grid-cols-2 gap-4">
            <div>
              <div className="text-gray-400">Sector</div>
              <div>{data.narrative.sector || 'N/A'}</div>
            </div>
            <div>
              <div className="text-gray-400">TAM ($B)</div>
              <div>{data.narrative.tam_b ? `$${data.narrative.tam_b.toFixed(0)}` : 'N/A'}</div>
            </div>
            <div>
              <div className="text-gray-400">Base X-Bagger</div>
              <div>{data.narrative.x_bagger_base ? `${data.narrative.x_bagger_base}x` : 'N/A'}</div>
            </div>
            <div>
              <div className="text-gray-400">Bull X-Bagger</div>
              <div>{data.narrative.x_bagger_bull ? `${data.narrative.x_bagger_bull}x` : 'N/A'}</div>
            </div>
            <div>
              <div className="text-gray-400">Story Strength</div>
              <div className="capitalize">{data.narrative.story_strength || 'N/A'}</div>
            </div>
          </div>
        )}
      </div>

      {/* AI Thesis */}
      <div className="p-4 border-b border-gray-700">
        <div 
          className="flex justify-between items-center cursor-pointer"
          onClick={() => toggleSection('thesis')}
        >
          <h3 className="text-lg font-bold">AI Thesis</h3>
          <span>{expandedSections.thesis ? '▼' : '▶'}</span>
        </div>
        
        {expandedSections.thesis && data.thesis_markdown && (
          <div className="mt-3 prose prose-invert max-w-none">
            {renderMarkdown(data.thesis_markdown)}
          </div>
        )}
      </div>

      {/* News */}
      <div className="p-4">
        <div 
          className="flex justify-between items-center cursor-pointer"
          onClick={() => toggleSection('news')}
        >
          <h3 className="text-lg font-bold">News</h3>
          <span>{expandedSections.news ? '▼' : '▶'}</span>
        </div>
        
        {expandedSections.news && data.news.length > 0 && (
          <div className="mt-3">
            <ul className="space-y-2">
              {data.news.map((item, i) => (
                <li key={i} className="border-b border-gray-700 pb-2">
                  <a 
                    href={item.url} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="text-blue-400 hover:text-blue-300"
                  >
                    {item.headline}
                  </a>
                  <div className="text-xs text-gray-400 mt-1">
                    {new Date(item.ts).toLocaleDateString()}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
};

export default TickerDeepDive;