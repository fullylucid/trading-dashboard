import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';

const PortfolioScan = () => {
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState('idle'); // idle, queued, running, complete, error
  const [progress, setProgress] = useState({ scanned: 0, total: 0 });
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [expandedCards, setExpandedCards] = useState({});
  const [expandedRows, setExpandedRows] = useState({});
  const pollInterval = useRef(null);

  const clearPoll = () => {
    if (pollInterval.current) {
      clearInterval(pollInterval.current);
      pollInterval.current = null;
    }
  };

  useEffect(() => {
    return () => clearPoll();
  }, []);

  const runScan = async () => {
    try {
      setStatus('queued');
      setProgress({ scanned: 0, total: 0 });
      setResult(null);
      setError(null);
      clearPoll();

      const response = await axios.post('/api/portfolio/scan?top_n=15&include_thesis=true');
      setJobId(response.data.job_id);

      pollInterval.current = setInterval(() => {
        checkStatus(response.data.job_id);
      }, 4000);
    } catch (err) {
      setStatus('error');
      setError(err.response?.data?.error || err.message || 'Failed to start scan');
      clearPoll();
    }
  };

  const checkStatus = async (id) => {
    try {
      const response = await axios.get(`/api/portfolio/scan/${id}`);
      const data = response.data;

      setStatus(data.status);

      if (data.status === 'running' || data.status === 'queued') {
        if (data.progress) {
          setProgress(data.progress);
        }
      }

      if (data.status === 'complete') {
        setResult(data.result);
        clearPoll();
      } else if (data.status === 'error') {
        setError(data.error || 'Scan failed');
        clearPoll();
      }
    } catch (err) {
      setStatus('error');
      setError(err.message || 'Failed to check status');
      clearPoll();
    }
  };

  const toggleCard = (ticker) => {
    setExpandedCards(prev => ({
      ...prev,
      [ticker]: !prev[ticker]
    }));
  };

  const toggleRow = (ticker) => {
    setExpandedRows(prev => ({
      ...prev,
      [ticker]: !prev[ticker]
    }));
  };

  const actionColor = (action) => {
    switch (action) {
      case 'Strong Buy': return 'bg-green-700 text-green-100';
      case 'Buy': return 'bg-green-900 text-green-200';
      case 'Hold': return 'bg-yellow-900 text-yellow-200';
      case 'Sell': return 'bg-red-900 text-red-200';
      case 'Strong Sell': return 'bg-red-700 text-red-100';
      default: return 'bg-gray-700 text-gray-200';
    }
  };

  const renderMarkdown = (markdown) => {
    if (!markdown) return null;
    return (
      <div 
        className="prose prose-invert max-w-none"
        dangerouslySetInnerHTML={{ 
          __html: markdown
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/\n/g, '<br />')
        }} 
      />
    );
  };

  const formatCurrency = (value) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(value);
  };

  const formatScore = (score) => {
    return score !== undefined && score !== null ? score.toFixed(1) : 'N/A';
  };

  const getThesisText = (row) => {
    if (row.thesis) return row.thesis;
    if (result?.theses?.[row.ticker]) return result.theses[row.ticker];
    return null;
  };

  const renderCard = (item, index) => (
    <div 
      key={`${item.ticker}-${index}`} 
      className="bg-gray-700 rounded-lg p-4 border border-gray-600"
    >
      <div className="flex justify-between items-start">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xl font-bold">{item.ticker}</span>
            <span className={`px-2 py-1 rounded text-xs font-medium ${actionColor(item.action)}`}>
              {item.action}
            </span>
          </div>
          <div className="text-3xl font-mono text-green-300 mb-3">
            {formatScore(item.composite_score)}
          </div>
          <div className="grid grid-cols-3 gap-2 text-sm">
            <div>
              <div className="text-gray-400">Technical</div>
              <div className="font-mono">{formatScore(item.technical_score)}</div>
            </div>
            <div>
              <div className="text-gray-400">Projection</div>
              <div className="font-mono">{formatScore(item.projection_score)}</div>
            </div>
            <div>
              <div className="text-gray-400">Narrative</div>
              <div className="font-mono">{formatScore(item.narrative_score)}</div>
            </div>
          </div>
        </div>
      </div>
      
      <button 
        onClick={() => toggleCard(`${item.ticker}-${index}`)}
        className="mt-3 text-green-400 hover:text-green-300 text-sm flex items-center"
      >
        {expandedCards[`${item.ticker}-${index}`] ? '▼ Hide Thesis' : '▶ Show Thesis'}
      </button>
      
      {expandedCards[`${item.ticker}-${index}`] && (
        <div className="mt-3 pt-3 border-t border-gray-600">
          {renderMarkdown(getThesisText(item))}
        </div>
      )}
    </div>
  );

  const renderProgressBar = () => {
    if (status !== 'queued' && status !== 'running') return null;

    const hasProgress = progress.total > 0;
    
    if (hasProgress) {
      const percentage = Math.round((progress.scanned / progress.total) * 100);
      return (
        <div className="mb-6">
          <div className="flex justify-between text-sm text-gray-300 mb-1">
            <span>Scanning {progress.scanned} / {progress.total} tickers</span>
            <span>{percentage}%</span>
          </div>
          <div className="w-full bg-gray-700 rounded-full h-2.5">
            <div 
              className="bg-green-600 h-2.5 rounded-full transition-all duration-300" 
              style={{ width: `${percentage}%` }}
            ></div>
          </div>
        </div>
      );
    }

    return (
      <div className="mb-6">
        <div className="text-sm text-gray-300 mb-1">Working...</div>
        <div className="w-full bg-gray-700 rounded-full h-2.5">
          <div className="bg-green-600 h-2.5 rounded-full animate-pulse w-full"></div>
        </div>
      </div>
    );
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-8">
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-6">
        <h1 className="text-2xl font-bold text-white mb-6">Portfolio Scan</h1>
        
        {error && (
          <div className="bg-red-900/50 border border-red-700 rounded-lg p-4 mb-6">
            <div className="text-red-200">{error}</div>
          </div>
        )}

        <button
          onClick={runScan}
          disabled={status === 'queued' || status === 'running'}
          className={`w-full py-3 px-4 rounded-lg font-medium text-white mb-6 ${
            status === 'queued' || status === 'running'
              ? 'bg-green-700 cursor-not-allowed'
              : 'bg-green-600 hover:bg-green-500'
          }`}
        >
          {status === 'queued' || status === 'running' ? 'Scanning…' : '▶ Run Full Portfolio Scan'}
        </button>

        {renderProgressBar()}

        {status === 'idle' && !result && (
          <div className="border-2 border-dashed border-gray-600 rounded-lg p-8 text-center text-gray-400">
            Click Run Full Portfolio Scan to begin.
          </div>
        )}

        {result && (
          <div className="space-y-8">
            <div className="text-center py-4">
              <div className="text-gray-400 text-sm">Portfolio Value</div>
              <div className="text-3xl font-bold text-white">
                {formatCurrency(result.portfolio_value)}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div>
                <h2 className="text-xl font-bold text-green-300 mb-4 flex items-center">
                  <span className="mr-2">🟢</span> Top Buys
                </h2>
                <div className="space-y-4">
                  {result.top_buys.map((item, index) => renderCard(item, index))}
                </div>
              </div>

              <div>
                <h2 className="text-xl font-bold text-red-300 mb-4 flex items-center">
                  <span className="mr-2">🔴</span> Top Sells
                </h2>
                <div className="space-y-4">
                  {result.top_sells.map((item, index) => renderCard(item, index))}
                </div>
              </div>

              <div>
                <h2 className="text-xl font-bold text-yellow-300 mb-4 flex items-center">
                  <span className="mr-2">🟡</span> Top Holds
                </h2>
                <div className="space-y-4">
                  {result.top_holds.map((item, index) => renderCard(item, index))}
                </div>
              </div>
            </div>

            <div>
              <h2 className="text-xl font-bold text-white mb-4">
                All Ranked Tickers ({result.all_results.length})
              </h2>
              <div className="bg-gray-700 rounded-lg border border-gray-600 overflow-hidden">
                <table className="w-full">
                  <thead className="bg-gray-600 text-gray-300 text-sm">
                    <tr>
                      <th className="py-3 px-4 text-left">#</th>
                      <th className="py-3 px-4 text-left">Ticker</th>
                      <th className="py-3 px-4 text-left">Action</th>
                      <th className="py-3 px-4 text-left">Composite</th>
                      <th className="py-3 px-4 text-left">Technical</th>
                      <th className="py-3 px-4 text-left">Projection</th>
                      <th className="py-3 px-4 text-left">Narrative</th>
                      <th className="py-3 px-4 text-left"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-600">
                    {result.all_results
                      .sort((a, b) => b.composite_score - a.composite_score)
                      .map((item, index) => (
                        <React.Fragment key={item.ticker}>
                          <tr className="hover:bg-gray-600/50">
                            <td className="py-3 px-4 text-gray-300">{index + 1}</td>
                            <td className="py-3 px-4 font-medium">{item.ticker}</td>
                            <td className="py-3 px-4">
                              <span className={`px-2 py-1 rounded text-xs font-medium ${actionColor(item.action)}`}>
                                {item.action}
                              </span>
                            </td>
                            <td className="py-3 px-4 font-mono text-green-300">{formatScore(item.composite_score)}</td>
                            <td className="py-3 px-4 font-mono">{formatScore(item.technical_score)}</td>
                            <td className="py-3 px-4 font-mono">{formatScore(item.projection_score)}</td>
                            <td className="py-3 px-4 font-mono">{formatScore(item.narrative_score)}</td>
                            <td className="py-3 px-4">
                              <button 
                                onClick={() => toggleRow(item.ticker)}
                                className="text-gray-400 hover:text-white"
                              >
                                {expandedRows[item.ticker] ? '▼' : '▶'}
                              </button>
                            </td>
                          </tr>
                          {expandedRows[item.ticker] && (
                            <tr>
                              <td colSpan="8" className="px-4 pb-4">
                                <div className="pl-8 pr-4 pt-2 border-t border-gray-600">
                                  {renderMarkdown(getThesisText(item))}
                                </div>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default PortfolioScan;