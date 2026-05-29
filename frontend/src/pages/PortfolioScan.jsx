import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';

const PortfolioScan = () => {
  const [status, setStatus] = useState('idle'); // idle, queued, running, complete, error
  const [progress, setProgress] = useState({ scanned: 0, total: 0 });
  const [result, setResult] = useState(null);
  const [savedAtPt, setSavedAtPt] = useState(null);
  const [ageMinutes, setAgeMinutes] = useState(null);
  const [snapshotMissing, setSnapshotMissing] = useState(false);
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

  const loadSnapshot = useCallback(async () => {
    try {
      const resp = await axios.get('/api/portfolio/scan/latest');
      setResult(resp.data.result);
      setSavedAtPt(resp.data.saved_at_pt || resp.data.saved_at || null);
      setAgeMinutes(resp.data.age_minutes ?? null);
      setSnapshotMissing(false);
    } catch (err) {
      if (err.response?.status === 404) {
        setSnapshotMissing(true);
        setResult(null);
      } else {
        setError(err.response?.data?.error || err.message || 'Failed to load snapshot');
      }
    }
  }, []);

  useEffect(() => {
    loadSnapshot();
    return () => clearPoll();
  }, [loadSnapshot]);

  const runScan = async () => {
    try {
      setStatus('queued');
      setProgress({ scanned: 0, total: 0 });
      setError(null);
      clearPoll();

      const response = await axios.post('/api/portfolio/scan?top_n=15&include_thesis=true');
      const id = response.data.job_id;

      pollInterval.current = setInterval(() => {
        checkStatus(id);
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
        clearPoll();
        // Refresh from persisted snapshot so dashboard stays in sync
        await loadSnapshot();
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

  const toggleCard = (symbol) => {
    setExpandedCards(prev => ({ ...prev, [symbol]: !prev[symbol] }));
  };

  const toggleRow = (symbol) => {
    setExpandedRows(prev => ({ ...prev, [symbol]: !prev[symbol] }));
  };

  const verdictColor = (verdict) => {
    switch (verdict) {
      case 'Strong Buy': return 'bg-green-700 text-green-100';
      case 'Buy': return 'bg-green-900 text-green-200';
      case 'Hold': return 'bg-yellow-900 text-yellow-200';
      case 'Sell': return 'bg-red-900 text-red-200';
      case 'Strong Sell': return 'bg-red-700 text-red-100';
      default: return 'bg-gray-700 text-gray-200';
    }
  };

  const formatCurrency = (value) => {
    if (value === null || value === undefined) return '—';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(value);
  };

  const formatScore = (score) => {
    if (score === null || score === undefined) return '—';
    return score.toFixed(1);
  };

  const formatPercent = (value, signed = false) => {
    if (value === null || value === undefined) return '—';
    const percent = (value * 100).toFixed(1);
    if (signed) {
      return value >= 0 ? `+${percent}%` : `${percent}%`;
    }
    return `${percent}%`;
  };

  const formatBigNumber = (value) => {
    if (value === null || value === undefined) return '—';
    return new Intl.NumberFormat('en-US').format(value);
  };

  const formatPrettyPt = (iso) => {
    if (!iso) return null;
    try {
      const d = new Date(iso);
      return d.toLocaleString('en-US', {
        timeZone: 'America/Los_Angeles',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      });
    } catch {
      return iso;
    }
  };

  const formatAge = (mins) => {
    if (mins === null || mins === undefined) return '';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
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

  const renderEnrichedPanel = (item) => {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
        <div className="bg-gray-800/50 rounded p-3 border border-gray-700">
          <div className="text-sm font-semibold text-green-300 mb-2">Thesis</div>
          {(item.thesis || item.thesis_markdown) ? (
            renderMarkdown(item.thesis || item.thesis_markdown)
          ) : (
            <div className="text-gray-500 text-sm">No thesis available</div>
          )}
        </div>

        <div className="bg-gray-800/50 rounded p-3 border border-gray-700">
          <div className="text-sm font-semibold text-green-300 mb-2">Quote</div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <div className="text-gray-400 text-xs uppercase">Price</div>
              <div className="text-white font-mono">{formatCurrency(item.quote?.price)}</div>
            </div>
            <div>
              <div className="text-gray-400 text-xs uppercase">Change</div>
              <div className={`font-mono ${item.quote?.change_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {formatPercent(item.quote?.change_pct, true)}
              </div>
            </div>
            <div>
              <div className="text-gray-400 text-xs uppercase">Volume</div>
              <div className="text-white font-mono">{formatBigNumber(item.quote?.volume)}</div>
            </div>
          </div>
        </div>

        <div className="bg-gray-800/50 rounded p-3 border border-gray-700">
          <div className="text-sm font-semibold text-green-300 mb-2">Projection</div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <div className="text-gray-400 text-xs uppercase">Bear</div>
              <div className="text-white font-mono">{formatCurrency(item.projection?.bear)}</div>
            </div>
            <div>
              <div className="text-gray-400 text-xs uppercase">Base</div>
              <div className="text-white font-mono">{formatCurrency(item.projection?.base)}</div>
            </div>
            <div>
              <div className="text-gray-400 text-xs uppercase">Bull</div>
              <div className="text-white font-mono">{formatCurrency(item.projection?.bull)}</div>
            </div>
            <div className="col-span-3">
              <div className="text-gray-400 text-xs uppercase">Upside</div>
              <div className={`font-mono ${item.projection?.upside >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {formatPercent(item.projection?.upside, true)}
              </div>
            </div>
          </div>
        </div>

        <div className="bg-gray-800/50 rounded p-3 border border-gray-700">
          <div className="text-sm font-semibold text-green-300 mb-2">Narrative</div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <div className="text-gray-400 text-xs uppercase">Sector</div>
              <div className="text-white font-mono">{item.narrative?.sector || '—'}</div>
            </div>
            <div>
              <div className="text-gray-400 text-xs uppercase">X-Bagger Base</div>
              <div className="text-white font-mono">
                {item.narrative?.x_bagger_base ? `${item.narrative.x_bagger_base.toFixed(1)}x` : '—'}
              </div>
            </div>
            <div>
              <div className="text-gray-400 text-xs uppercase">X-Bagger Bull</div>
              <div className="text-white font-mono">
                {item.narrative?.x_bagger_bull ? `${item.narrative.x_bagger_bull.toFixed(1)}x` : '—'}
              </div>
            </div>
            <div>
              <div className="text-gray-400 text-xs uppercase">TAM</div>
              <div className="text-white font-mono">
                {item.narrative?.tam_today_b && item.narrative?.tam_future_b
                  ? `$${item.narrative.tam_today_b.toFixed(0)}b → $${item.narrative.tam_future_b.toFixed(0)}b`
                  : '—'}
              </div>
            </div>
          </div>
        </div>

        <div className="bg-gray-800/50 rounded p-3 border border-gray-700">
          <div className="text-sm font-semibold text-green-300 mb-2">Signals</div>
          <div className="space-y-2">
            <div className="grid grid-cols-3 gap-2">
              <div className="text-gray-400 text-xs uppercase">Technical</div>
              <div className="text-gray-400 text-xs uppercase">Projection</div>
              <div className="text-gray-400 text-xs uppercase">Narrative</div>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div>
                <div className="text-white font-mono">{formatScore(item.signals_summary?.technical?.score)}</div>
                <div className="text-gray-400 text-xs">{item.signals_summary?.technical?.reason || '—'}</div>
              </div>
              <div>
                <div className="text-white font-mono">{formatScore(item.signals_summary?.projection?.score)}</div>
                <div className="text-gray-400 text-xs">{item.signals_summary?.projection?.reason || '—'}</div>
              </div>
              <div>
                <div className="text-white font-mono">{formatScore(item.signals_summary?.narrative?.score)}</div>
                <div className="text-gray-400 text-xs">{item.signals_summary?.narrative?.reason || '—'}</div>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-gray-800/50 rounded p-3 border border-gray-700">
          <div className="text-sm font-semibold text-green-300 mb-2">Position</div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <div className="text-gray-400 text-xs uppercase">Market Value</div>
              <div className="text-white font-mono">{formatCurrency(item.market_value)}</div>
            </div>
            <div>
              <div className="text-gray-400 text-xs uppercase">Units</div>
              <div className="text-white font-mono">
                {item.units !== undefined && item.units !== null ? Math.round(item.units) : '—'}
              </div>
            </div>
            <div>
              <div className="text-gray-400 text-xs uppercase">% of Portfolio</div>
              <div className="text-white font-mono">{formatPercent(item.pct_of_portfolio)}</div>
            </div>
          </div>
        </div>
      </div>
    );
  };

  const renderCard = (item, index) => (
    <div key={`${item.symbol}-${index}`} className="bg-gray-700 rounded-lg p-4 border border-gray-600">
      <div className="flex justify-between items-start">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xl font-bold">{item.symbol}</span>
            <span className={`px-2 py-1 rounded text-xs font-medium ${verdictColor(item.verdict)}`}>
              {item.verdict}
            </span>
          </div>
          <div className="text-3xl font-mono text-green-300 mb-3">
            {formatScore(item.composite_score || item.scores?.combined)}
          </div>
          <div className="grid grid-cols-3 gap-2 text-sm">
            <div>
              <div className="text-gray-400">Technical</div>
              <div className="font-mono">{formatScore(item.scores?.technical)}</div>
            </div>
            <div>
              <div className="text-gray-400">Projection</div>
              <div className="font-mono">{formatScore(item.scores?.projection)}</div>
            </div>
            <div>
              <div className="text-gray-400">Narrative</div>
              <div className="font-mono">{formatScore(item.scores?.narrative)}</div>
            </div>
          </div>
        </div>
      </div>

      <button
        onClick={() => toggleCard(item.symbol)}
        className="mt-3 text-green-400 hover:text-green-300 text-sm flex items-center"
      >
        {expandedCards[item.symbol] ? '▼ Hide Details' : '▶ Show Details'}
      </button>

      {expandedCards[item.symbol] && (
        <div className="mt-3 pt-3 border-t border-gray-600">
          {renderEnrichedPanel(item)}
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

  const scanning = status === 'queued' || status === 'running';
  const stale = ageMinutes !== null && ageMinutes > 24 * 60;
  const badgeColor = stale
    ? 'bg-yellow-900/60 border-yellow-700 text-yellow-200'
    : 'bg-gray-700/60 border-gray-600 text-gray-300';

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-8">
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
          <h1 className="text-2xl font-bold text-white">Portfolio Scan</h1>
          <button
            onClick={runScan}
            disabled={scanning}
            className={`py-2 px-4 rounded-lg font-medium text-white ${
              scanning ? 'bg-green-700 cursor-not-allowed' : 'bg-green-600 hover:bg-green-500'
            }`}
          >
            {scanning ? 'Scanning…' : '▶ Run Fresh Scan'}
          </button>
        </div>

        {savedAtPt && (
          <div className={`inline-block text-sm border rounded px-3 py-1 mb-4 ${badgeColor}`}>
            Last scan: {formatPrettyPt(savedAtPt)} PT
            {ageMinutes !== null && <> &nbsp;·&nbsp; {formatAge(ageMinutes)}</>}
            {stale && <> &nbsp;·&nbsp; <span className="font-semibold">stale</span></>}
          </div>
        )}

        {error && (
          <div className="bg-red-900/50 border border-red-700 rounded-lg p-4 mb-6">
            <div className="text-red-200">{error}</div>
          </div>
        )}

        {renderProgressBar()}

        {!result && snapshotMissing && !scanning && (
          <div className="border-2 border-dashed border-gray-600 rounded-lg p-8 text-center text-gray-400">
            No scan yet — click "Run Fresh Scan" to build the first one.
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
                  {(result.top_buys || []).map((item, index) => renderCard(item, index))}
                </div>
              </div>

              <div>
                <h2 className="text-xl font-bold text-red-300 mb-4 flex items-center">
                  <span className="mr-2">🔴</span> Top Sells
                </h2>
                <div className="space-y-4">
                  {(result.top_sells || []).map((item, index) => renderCard(item, index))}
                </div>
              </div>

              <div>
                <h2 className="text-xl font-bold text-yellow-300 mb-4 flex items-center">
                  <span className="mr-2">🟡</span> Top Holds
                </h2>
                <div className="space-y-4">
                  {(result.top_holds || []).map((item, index) => renderCard(item, index))}
                </div>
              </div>
            </div>

            <div>
              <h2 className="text-xl font-bold text-white mb-4">
                All Ranked Tickers ({result.ranked?.length || 0})
              </h2>
              <div className="bg-gray-700 rounded-lg border border-gray-600 overflow-hidden">
                <table className="w-full">
                  <thead className="bg-gray-600 text-gray-300 text-sm">
                    <tr>
                      <th className="py-3 px-4 text-left">#</th>
                      <th className="py-3 px-4 text-left">Ticker</th>
                      <th className="py-3 px-4 text-left">Verdict</th>
                      <th className="py-3 px-4 text-left">Composite</th>
                      <th className="py-3 px-4 text-left">Technical</th>
                      <th className="py-3 px-4 text-left">Projection</th>
                      <th className="py-3 px-4 text-left">Narrative</th>
                      <th className="py-3 px-4 text-left"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-600">
                    {result.ranked
                      ?.slice()
                      .sort((a, b) => (b.composite_score || b.scores?.combined || 0) - (a.composite_score || a.scores?.combined || 0))
                      .map((item, index) => (
                        <React.Fragment key={item.symbol}>
                          <tr className="hover:bg-gray-600/50">
                            <td className="py-3 px-4 text-gray-300">{index + 1}</td>
                            <td className="py-3 px-4 font-medium">{item.symbol}</td>
                            <td className="py-3 px-4">
                              <span className={`px-2 py-1 rounded text-xs font-medium ${verdictColor(item.verdict)}`}>
                                {item.verdict}
                              </span>
                            </td>
                            <td className="py-3 px-4 font-mono text-green-300">
                              {formatScore(item.composite_score || item.scores?.combined)}
                            </td>
                            <td className="py-3 px-4 font-mono">{formatScore(item.scores?.technical)}</td>
                            <td className="py-3 px-4 font-mono">{formatScore(item.scores?.projection)}</td>
                            <td className="py-3 px-4 font-mono">{formatScore(item.scores?.narrative)}</td>
                            <td className="py-3 px-4">
                              <button
                                onClick={() => toggleRow(item.symbol)}
                                className="text-gray-400 hover:text-white"
                              >
                                {expandedRows[item.symbol] ? '▼' : '▶'}
                              </button>
                            </td>
                          </tr>
                          {expandedRows[item.symbol] && (
                            <tr>
                              <td colSpan="8" className="px-4 pb-4">
                                <div className="pl-8 pr-4 pt-2 border-t border-gray-600">
                                  {renderEnrichedPanel(item)}
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
