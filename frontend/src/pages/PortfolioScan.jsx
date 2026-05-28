import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';

const verdictColor = (verdict) => {
  const v = (verdict || '').toUpperCase();
  if (v.includes('STRONG BUY')) return 'bg-green-700 text-green-100';
  if (v.includes('BUY')) return 'bg-green-900 text-green-200';
  if (v.includes('STRONG SELL')) return 'bg-red-700 text-red-100';
  if (v.includes('SELL')) return 'bg-red-900 text-red-200';
  if (v.includes('HOLD')) return 'bg-yellow-900 text-yellow-200';
  return 'bg-gray-700 text-gray-200';
};

const fmtMoney = (n) => {
  if (n === null || n === undefined || isNaN(n)) return '—';
  return n.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
};

const fmtPct = (n) => {
  if (n === null || n === undefined || isNaN(n)) return '—';
  return `${(n * (Math.abs(n) < 1 ? 100 : 1)).toFixed(2)}%`;
};

// Minimal markdown renderer (headings, bold, italic, lists, line breaks)
const renderMarkdown = (md) => {
  if (!md) return null;
  const lines = md.split('\n');
  const out = [];
  let listBuf = [];
  const flushList = () => {
    if (listBuf.length) {
      out.push(
        <ul key={`ul-${out.length}`} className="list-disc list-inside my-2 text-gray-300 space-y-1">
          {listBuf.map((li, i) => (
            <li key={i} dangerouslySetInnerHTML={{ __html: inlineFmt(li) }} />
          ))}
        </ul>
      );
      listBuf = [];
    }
  };
  const inlineFmt = (s) =>
    s
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/`(.+?)`/g, '<code class="bg-gray-900 px-1 rounded text-green-300">$1</code>');

  lines.forEach((raw, idx) => {
    const line = raw.trimEnd();
    if (/^###\s+/.test(line)) {
      flushList();
      out.push(
        <h3 key={idx} className="text-base font-semibold text-green-300 mt-3 mb-1">
          {line.replace(/^###\s+/, '')}
        </h3>
      );
    } else if (/^##\s+/.test(line)) {
      flushList();
      out.push(
        <h2 key={idx} className="text-lg font-bold text-green-200 mt-4 mb-2">
          {line.replace(/^##\s+/, '')}
        </h2>
      );
    } else if (/^#\s+/.test(line)) {
      flushList();
      out.push(
        <h1 key={idx} className="text-xl font-bold text-white mt-4 mb-2">
          {line.replace(/^#\s+/, '')}
        </h1>
      );
    } else if (/^\s*[-*]\s+/.test(line)) {
      listBuf.push(line.replace(/^\s*[-*]\s+/, ''));
    } else if (line.trim() === '') {
      flushList();
    } else {
      flushList();
      out.push(
        <p
          key={idx}
          className="text-gray-300 text-sm leading-relaxed my-1"
          dangerouslySetInnerHTML={{ __html: inlineFmt(line) }}
        />
      );
    }
  });
  flushList();
  return out;
};

function ResultCard({ item, expandable }) {
  const [open, setOpen] = useState(false);
  const hasThesis = expandable && item.thesis_markdown;
  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 hover:border-gray-600 transition">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold text-white">{item.symbol}</span>
          <span className={`px-2 py-0.5 rounded text-xs font-semibold ${verdictColor(item.verdict)}`}>
            {item.verdict || '—'}
          </span>
        </div>
        <div className="text-right">
          <div className="text-sm text-gray-400">Score</div>
          <div className="text-lg font-mono text-green-300">
            {item.composite_score != null ? Number(item.composite_score).toFixed(2) : '—'}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-3 text-sm">
        <div>
          <div className="text-xs text-gray-500">Market Value</div>
          <div className="text-gray-200">{fmtMoney(item.market_value)}</div>
        </div>
        <div>
          <div className="text-xs text-gray-500">% Portfolio</div>
          <div className="text-gray-200">
            {item.pct_of_portfolio != null ? `${Number(item.pct_of_portfolio).toFixed(2)}%` : '—'}
          </div>
        </div>
        <div>
          <div className="text-xs text-gray-500">Units</div>
          <div className="text-gray-200">{item.units != null ? Number(item.units).toFixed(4) : '—'}</div>
        </div>
      </div>
      {hasThesis && (
        <div className="mt-3 border-t border-gray-700 pt-3">
          <button
            onClick={() => setOpen(!open)}
            className="text-sm text-green-400 hover:text-green-300 font-medium"
          >
            {open ? '▼ Hide Thesis' : '▶ Show Thesis'}
          </button>
          {open && (
            <div className="mt-2 bg-gray-900/50 rounded p-3 max-h-96 overflow-y-auto">
              {renderMarkdown(item.thesis_markdown)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Section({ title, items, expandable }) {
  if (!items || items.length === 0) {
    return (
      <div>
        <h2 className="text-xl font-bold text-white mb-3">{title}</h2>
        <div className="text-gray-500 text-sm bg-gray-800 rounded-lg p-4">No items.</div>
      </div>
    );
  }
  return (
    <div>
      <h2 className="text-xl font-bold text-white mb-3">
        {title} <span className="text-gray-500 text-sm font-normal">({items.length})</span>
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {items.map((it, i) => (
          <ResultCard key={`${it.symbol}-${i}`} item={it} expandable={expandable} />
        ))}
      </div>
    </div>
  );
}

function PortfolioScan() {
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState(null); // pending|running|complete|failed
  const [progress, setProgress] = useState({ scanned: 0, total: 0 });
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [topN, setTopN] = useState(15);
  const [includeThesis, setIncludeThesis] = useState(true);
  const pollRef = useRef(null);

  const isRunning = status === 'pending' || status === 'running';

  const clearPoll = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  useEffect(() => () => clearPoll(), []);

  const startScan = async () => {
    setError(null);
    setResult(null);
    setProgress({ scanned: 0, total: 0 });
    try {
      const res = await axios.post(
        `/api/portfolio/scan?top_n=${topN}&include_thesis=${includeThesis}`
      );
      const id = res.data.job_id;
      setJobId(id);
      setStatus(res.data.status || 'pending');
      clearPoll();
      pollRef.current = setInterval(() => pollStatus(id), 4000);
      // also poll immediately
      pollStatus(id);
    } catch (err) {
      console.error('Scan start failed:', err);
      setError(err?.response?.data?.detail || err.message || 'Failed to start scan');
      setStatus('failed');
    }
  };

  const pollStatus = async (id) => {
    try {
      const res = await axios.get(`/api/portfolio/scan/${id}`);
      const data = res.data;
      setStatus(data.status);
      if (data.progress) setProgress(data.progress);
      if (data.status === 'complete') {
        setResult(data.result || null);
        clearPoll();
      } else if (data.status === 'failed') {
        setError(data.error || 'Scan failed');
        clearPoll();
      }
    } catch (err) {
      console.error('Poll failed:', err);
      setError(err?.response?.data?.detail || err.message || 'Polling error');
      setStatus('failed');
      clearPoll();
    }
  };

  const progressPct =
    progress.total > 0 ? Math.min(100, Math.round((progress.scanned / progress.total) * 100)) : 0;

  const allResults = result?.all_results || [];
  const sortedAll = [...allResults].sort(
    (a, b) => (b.composite_score ?? -Infinity) - (a.composite_score ?? -Infinity)
  );

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-8">
      <div className="mb-6">
        <h1 className="text-2xl sm:text-3xl font-bold text-white mb-1">📊 Portfolio Scan</h1>
        <p className="text-gray-400 text-sm">
          Run a composite quant scan across your portfolio and surface top buys, sells, and holds.
        </p>
      </div>

      {/* Controls */}
      <div className="bg-gray-800 rounded-lg p-4 mb-6 border border-gray-700">
        <div className="flex flex-col sm:flex-row sm:items-end gap-4">
          <div className="flex-1 grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Top N</label>
              <input
                type="number"
                min="1"
                max="50"
                value={topN}
                onChange={(e) => setTopN(parseInt(e.target.value || '15', 10))}
                disabled={isRunning}
                className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-white disabled:opacity-50"
              />
            </div>
            <div className="flex items-end">
              <label className="flex items-center gap-2 text-sm text-gray-300">
                <input
                  type="checkbox"
                  checked={includeThesis}
                  onChange={(e) => setIncludeThesis(e.target.checked)}
                  disabled={isRunning}
                  className="rounded"
                />
                Include AI thesis
              </label>
            </div>
          </div>
          <button
            onClick={startScan}
            disabled={isRunning}
            className={`px-6 py-2 rounded font-semibold transition ${
              isRunning
                ? 'bg-gray-700 text-gray-400 cursor-not-allowed'
                : 'bg-green-600 hover:bg-green-500 text-white'
            }`}
          >
            {isRunning ? 'Scanning...' : '▶ Run Scan'}
          </button>
        </div>
      </div>

      {/* Progress */}
      {isRunning && (
        <div className="bg-gray-800 rounded-lg p-4 mb-6 border border-gray-700">
          <div className="flex justify-between text-sm mb-2">
            <span className="text-gray-300">
              Scanning {progress.scanned} / {progress.total || '?'} tickers...
            </span>
            <span className="text-green-300 font-mono">{progressPct}%</span>
          </div>
          <div className="w-full bg-gray-900 rounded-full h-2 overflow-hidden">
            <div
              className="bg-green-500 h-full transition-all duration-500"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <div className="text-xs text-gray-500 mt-2">Status: {status}</div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-900/40 border border-red-700 rounded-lg p-4 mb-6">
          <p className="text-red-200 text-sm font-semibold">⚠️ {error}</p>
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="space-y-6">
          {/* Header card */}
          <div className="bg-gray-800 rounded-lg p-4 sm:p-6 border border-gray-700">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <div className="text-xs text-gray-400">Portfolio Value</div>
                <div className="text-xl sm:text-2xl font-bold text-green-300">
                  {fmtMoney(result.portfolio_value)}
                </div>
              </div>
              <div>
                <div className="text-xs text-gray-400">Tickers Scanned</div>
                <div className="text-xl sm:text-2xl font-bold text-white">
                  {result.tickers_scanned ?? '—'}
                </div>
              </div>
              <div>
                <div className="text-xs text-gray-400">Tickers Failed</div>
                <div className="text-xl sm:text-2xl font-bold text-red-300">
                  {result.tickers_failed ?? 0}
                </div>
              </div>
              <div>
                <div className="text-xs text-gray-400">Scanned At</div>
                <div className="text-sm text-gray-200 mt-1">
                  {result.scanned_at ? new Date(result.scanned_at).toLocaleString() : '—'}
                </div>
              </div>
            </div>
            {result.skipped_symbols && result.skipped_symbols.length > 0 && (
              <div className="mt-4 text-xs text-gray-500">
                Skipped: {result.skipped_symbols.join(', ')}
              </div>
            )}
          </div>

          <Section title="🟢 Top Buys" items={result.top_buys} expandable />
          <Section title="🔴 Top Sells" items={result.top_sells} expandable={false} />
          <Section title="🟡 Top Holds" items={result.top_holds} expandable={false} />

          {/* Full ranked table */}
          {sortedAll.length > 0 && (
            <div>
              <h2 className="text-xl font-bold text-white mb-3">All Ranked Tickers</h2>
              <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
                <div className="max-h-96 overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-900 sticky top-0 z-10">
                      <tr className="text-gray-400 text-xs uppercase">
                        <th className="text-left px-3 py-2">#</th>
                        <th className="text-left px-3 py-2">Symbol</th>
                        <th className="text-right px-3 py-2">Score</th>
                        <th className="text-left px-3 py-2">Verdict</th>
                        <th className="text-right px-3 py-2">Price</th>
                        <th className="text-right px-3 py-2">Change %</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedAll.map((row, i) => {
                        const price = row.quote?.price ?? row.quote?.last ?? row.price;
                        const chg = row.quote?.change_pct ?? row.change_pct;
                        return (
                          <tr
                            key={`${row.symbol}-${i}`}
                            className="border-t border-gray-700 hover:bg-gray-700/30"
                          >
                            <td className="px-3 py-2 text-gray-500">{i + 1}</td>
                            <td className="px-3 py-2 font-semibold text-white">{row.symbol}</td>
                            <td className="px-3 py-2 text-right font-mono text-green-300">
                              {row.composite_score != null
                                ? Number(row.composite_score).toFixed(2)
                                : '—'}
                            </td>
                            <td className="px-3 py-2">
                              <span
                                className={`px-2 py-0.5 rounded text-xs ${verdictColor(row.verdict)}`}
                              >
                                {row.verdict || '—'}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-right text-gray-200">
                              {price != null ? fmtMoney(price) : '—'}
                            </td>
                            <td
                              className={`px-3 py-2 text-right font-mono ${
                                chg > 0 ? 'text-green-400' : chg < 0 ? 'text-red-400' : 'text-gray-400'
                              }`}
                            >
                              {chg != null ? `${Number(chg).toFixed(2)}%` : '—'}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {!result && !isRunning && !error && (
        <div className="bg-gray-800/50 rounded-lg p-8 text-center text-gray-400 border border-dashed border-gray-700">
          Click <span className="text-green-400 font-semibold">Run Scan</span> to begin.
        </div>
      )}
    </div>
  );
}

export default PortfolioScan;
