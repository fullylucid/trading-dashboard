/**
 * PortfolioScan — strict-TS supersession of the legacy PortfolioScan.jsx.
 *
 * Keeps the snapshot-driven instant-load + job-poll scan pattern, the
 * buy/sell/hold scorecards and the ranked table, and ADDS the Phase-3 cockpit:
 *
 *   - RegimeBanner       (payload.regime)
 *   - RiskGauges         (payload.portfolio_risk)
 *   - RedundancyCallout  (compact concentration/redundancy read off
 *                         payload.portfolio_risk — replaces the old N×N heatmap)
 *   - AlertTimeline      (payload.alerts)
 *   - ChartWorkspace     (the CENTERPIECE — TradingView-style workspace with
 *                         custom AI indicators, individual/compare/portfolio
 *                         modes, sourced from /api/chart endpoints)
 *   - SignalRadar        (selected ticker's analytics.signals)
 *
 * Everything analytics-side is additive + null-guarded: the page renders fully
 * even against an old snapshot that lacks the new blocks.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';

import RegimeBanner from '../components/analytics/RegimeBanner';
import RiskGauges from '../components/analytics/RiskGauges';
import RedundancyCallout from '../components/analytics/RedundancyCallout';
import AlertTimeline from '../components/analytics/AlertTimeline';
import SignalRadar from '../components/analytics/SignalRadar';
import type { SignalsBlock, RegimeBlock } from '../components/analytics/types';

import ChartWorkspace from '../components/charts/ChartWorkspace';

import type {
  PortfolioRisk,
  ScoredAlert,
  TickerAnalytics,
} from '../types/scanAnalytics';

// ---------------------------------------------------------------------------
// Scan payload types (just the fields this page reads).
// ---------------------------------------------------------------------------

interface ScoreBlock {
  technical?: number | null;
  projection?: number | null;
  narrative?: number | null;
  combined?: number | null;
}

interface Quote {
  price?: number | null;
  change_pct?: number | null;
  volume?: number | null;
}

interface Projection {
  bear?: number | null;
  base?: number | null;
  bull?: number | null;
  upside?: number | null;
}

interface Narrative {
  sector?: string | null;
  x_bagger_base?: number | null;
  x_bagger_bull?: number | null;
  tam_today_b?: number | null;
  tam_future_b?: number | null;
}

interface SignalSummaryItem {
  score?: number | null;
  reason?: string | null;
}

interface SignalsSummary {
  technical?: SignalSummaryItem;
  projection?: SignalSummaryItem;
  narrative?: SignalSummaryItem;
}

interface ScanItem {
  symbol: string;
  verdict?: string | null;
  composite_score?: number | null;
  scores?: ScoreBlock;
  quote?: Quote;
  projection?: Projection;
  narrative?: Narrative;
  signals_summary?: SignalsSummary;
  thesis?: string | null;
  thesis_markdown?: string | null;
  market_value?: number | null;
  units?: number | null;
  pct_of_portfolio?: number | null;
  analytics?: TickerAnalytics;
  sector_rotation?: { status?: string | null; tag?: string | null } | null;
}

interface ScanResult {
  portfolio_value?: number | null;
  top_buys?: ScanItem[];
  top_sells?: ScanItem[];
  top_holds?: ScanItem[];
  ranked?: ScanItem[];
  partial_failure?: boolean;
  failed_count?: number;
  portfolio_risk?: PortfolioRisk;
  regime?: RegimeBlock;
  alerts?: ScoredAlert[];
}

interface SnapshotResponse {
  result: ScanResult;
  saved_at_pt?: string | null;
  saved_at?: string | null;
  age_minutes?: number | null;
}

interface ScanProgress {
  scanned: number;
  total: number;
}

type ScanStatus = 'idle' | 'queued' | 'running' | 'complete' | 'error';

// ---------------------------------------------------------------------------
// Per-ticker signals adapter: the scan emits `analytics.signals` already in the
// analytics `SignalsBlock` shape ({macd:{macd,signal,hist}}, …). Pull it out for
// the radar, degrading to null when absent.
// ---------------------------------------------------------------------------

function signalsBlockOf(item: ScanItem | null): SignalsBlock | null {
  const raw = item?.analytics?.signals;
  if (!raw || typeof raw !== 'object') return null;
  return raw as unknown as SignalsBlock;
}

// ---------------------------------------------------------------------------
// Formatting helpers.
// ---------------------------------------------------------------------------

function formatCurrency(value: number | null | undefined): string {
  if (value == null) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

function formatScore(score: number | null | undefined): string {
  if (score == null) return '—';
  return score.toFixed(1);
}

function formatPercent(value: number | null | undefined, signed = false): string {
  if (value == null) return '—';
  const pct = (value * 100).toFixed(1);
  if (signed) return value >= 0 ? `+${pct}%` : `${pct}%`;
  return `${pct}%`;
}

function formatBigNumber(value: number | null | undefined): string {
  if (value == null) return '—';
  return new Intl.NumberFormat('en-US').format(value);
}

function formatPrettyPt(iso: string | null | undefined): string | null {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleString('en-US', {
      timeZone: 'America/Los_Angeles',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function formatAge(mins: number | null | undefined): string {
  if (mins == null) return '';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function verdictColor(verdict: string | null | undefined): string {
  switch (verdict) {
    case 'Strong Buy':
      return 'bg-green-700 text-green-100';
    case 'Buy':
      return 'bg-green-900 text-green-200';
    case 'Hold':
      return 'bg-yellow-900 text-yellow-200';
    case 'Sell':
      return 'bg-red-900 text-red-200';
    case 'Strong Sell':
      return 'bg-red-700 text-red-100';
    default:
      return 'bg-gray-700 text-gray-200';
  }
}

function renderMarkdown(markdown: string | null | undefined): React.ReactElement | null {
  if (!markdown) return null;
  const html = markdown
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/\n/g, '<br />');
  return (
    <div
      className="prose prose-invert max-w-none"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

// ---------------------------------------------------------------------------
// Component.
// ---------------------------------------------------------------------------

const PortfolioScan: React.FC = () => {
  const [status, setStatus] = useState<ScanStatus>('idle');
  const [progress, setProgress] = useState<ScanProgress>({ scanned: 0, total: 0 });
  const [result, setResult] = useState<ScanResult | null>(null);
  const [savedAtPt, setSavedAtPt] = useState<string | null>(null);
  const [ageMinutes, setAgeMinutes] = useState<number | null>(null);
  const [snapshotMissing, setSnapshotMissing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedCards, setExpandedCards] = useState<Record<string, boolean>>({});
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({});

  // Selected ticker → drives the SignalRadar + the workspace's initial symbol.
  const [selected, setSelected] = useState<string | null>(null);

  const pollInterval = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearPoll = (): void => {
    if (pollInterval.current) {
      clearInterval(pollInterval.current);
      pollInterval.current = null;
    }
  };

  const loadSnapshot = useCallback(async (): Promise<void> => {
    try {
      const resp = await axios.get<SnapshotResponse>('/api/portfolio/scan/latest');
      setResult(resp.data.result);
      setSavedAtPt(resp.data.saved_at_pt ?? resp.data.saved_at ?? null);
      setAgeMinutes(resp.data.age_minutes ?? null);
      setSnapshotMissing(false);
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 404) {
        setSnapshotMissing(true);
        setResult(null);
      } else {
        const msg = axios.isAxiosError(err)
          ? err.response?.data?.error ?? err.message
          : 'Failed to load snapshot';
        setError(msg);
      }
    }
  }, []);

  useEffect(() => {
    void loadSnapshot();
    return () => clearPoll();
  }, [loadSnapshot]);

  // Default-select the top buy (or first ranked) once a result lands.
  useEffect(() => {
    if (selected || !result) return;
    const first =
      result.top_buys?.[0]?.symbol ?? result.ranked?.[0]?.symbol ?? null;
    if (first) setSelected(first);
  }, [result, selected]);

  const checkStatus = useCallback(
    async (id: string): Promise<void> => {
      try {
        const response = await axios.get<{
          status: ScanStatus;
          progress?: ScanProgress;
          error?: string;
        }>(`/api/portfolio/scan/${id}`);
        const data = response.data;
        setStatus(data.status);

        if (data.status === 'running' || data.status === 'queued') {
          if (data.progress) setProgress(data.progress);
        }

        if (data.status === 'complete') {
          clearPoll();
          await loadSnapshot();
        } else if (data.status === 'error') {
          setError(data.error ?? 'Scan failed');
          clearPoll();
        }
      } catch (err) {
        setStatus('error');
        setError(err instanceof Error ? err.message : 'Failed to check status');
        clearPoll();
      }
    },
    [loadSnapshot],
  );

  const runScan = async (): Promise<void> => {
    try {
      setStatus('queued');
      setProgress({ scanned: 0, total: 0 });
      setError(null);
      clearPoll();

      const response = await axios.post<{ job_id: string }>(
        '/api/portfolio/scan?top_n=15&include_thesis=true',
      );
      const id = response.data.job_id;
      pollInterval.current = setInterval(() => {
        void checkStatus(id);
      }, 4000);
    } catch (err) {
      setStatus('error');
      const msg = axios.isAxiosError(err)
        ? err.response?.data?.error ?? err.message
        : 'Failed to start scan';
      setError(msg);
      clearPoll();
    }
  };

  const toggleCard = (symbol: string): void =>
    setExpandedCards((prev) => ({ ...prev, [symbol]: !prev[symbol] }));
  const toggleRow = (symbol: string): void =>
    setExpandedRows((prev) => ({ ...prev, [symbol]: !prev[symbol] }));

  const scanning = status === 'queued' || status === 'running';
  const stale = ageMinutes != null && ageMinutes > 24 * 60;
  const badgeColor = stale
    ? 'bg-yellow-900/60 border-yellow-700 text-yellow-200'
    : 'bg-gray-700/60 border-gray-600 text-gray-300';

  // Find the selected scan item (for the radar + chart overlays).
  const selectedItem = useMemo<ScanItem | null>(() => {
    if (!selected || !result) return null;
    const pools = [
      result.ranked ?? [],
      result.top_buys ?? [],
      result.top_sells ?? [],
      result.top_holds ?? [],
    ];
    for (const pool of pools) {
      const found = pool.find((i) => i.symbol === selected);
      if (found) return found;
    }
    return null;
  }, [selected, result]);

  const selectableSymbols = useMemo<string[]>(() => {
    if (!result) return [];
    const ranked = result.ranked ?? [];
    return ranked.map((i) => i.symbol);
  }, [result]);

  const renderEnrichedPanel = (item: ScanItem): React.ReactElement => (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
      <div className="bg-gray-800/50 rounded p-3 border border-gray-700">
        <div className="text-sm font-semibold text-green-300 mb-2">Thesis</div>
        {item.thesis || item.thesis_markdown ? (
          renderMarkdown(item.thesis ?? item.thesis_markdown)
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
            <div className={`font-mono ${(item.quote?.change_pct ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
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
            <div className={`font-mono ${(item.projection?.upside ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {formatPercent(item.projection?.upside, true)}
            </div>
          </div>
        </div>
      </div>

      <div className="bg-gray-800/50 rounded p-3 border border-gray-700">
        <div className="text-sm font-semibold text-green-300 mb-2">Signals</div>
        <div className="grid grid-cols-3 gap-2">
          <div>
            <div className="text-gray-400 text-xs uppercase">Technical</div>
            <div className="text-white font-mono">{formatScore(item.signals_summary?.technical?.score)}</div>
            <div className="text-gray-400 text-xs">{item.signals_summary?.technical?.reason ?? '—'}</div>
          </div>
          <div>
            <div className="text-gray-400 text-xs uppercase">Projection</div>
            <div className="text-white font-mono">{formatScore(item.signals_summary?.projection?.score)}</div>
            <div className="text-gray-400 text-xs">{item.signals_summary?.projection?.reason ?? '—'}</div>
          </div>
          <div>
            <div className="text-gray-400 text-xs uppercase">Narrative</div>
            <div className="text-white font-mono">{formatScore(item.signals_summary?.narrative?.score)}</div>
            <div className="text-gray-400 text-xs">{item.signals_summary?.narrative?.reason ?? '—'}</div>
          </div>
        </div>
      </div>
    </div>
  );

  const renderCard = (item: ScanItem, index: number): React.ReactElement => {
    const isSelected = item.symbol === selected;
    return (
      <div
        key={`${item.symbol}-${index}`}
        className={`bg-gray-700 rounded-lg p-4 border ${isSelected ? 'border-green-400' : 'border-gray-600'}`}
      >
        <div className="flex justify-between items-start">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <button
                type="button"
                onClick={() => setSelected(item.symbol)}
                className="text-xl font-bold hover:text-green-300"
                title="Chart this ticker"
              >
                {item.symbol}
              </button>
              <span className={`px-2 py-1 rounded text-xs font-medium ${verdictColor(item.verdict)}`}>
                {item.verdict}
              </span>
            </div>
            <div className="text-3xl font-mono text-green-300 mb-3">
              {formatScore(item.composite_score ?? item.scores?.combined)}
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
          <div className="mt-3 pt-3 border-t border-gray-600">{renderEnrichedPanel(item)}</div>
        )}
      </div>
    );
  };

  const renderProgressBar = (): React.ReactElement | null => {
    if (status !== 'queued' && status !== 'running') return null;
    const hasProgress = progress.total > 0;
    if (hasProgress) {
      const percentage = Math.round((progress.scanned / progress.total) * 100);
      return (
        <div className="mb-6">
          <div className="flex justify-between text-sm text-gray-300 mb-1">
            <span>
              Scanning {progress.scanned} / {progress.total} tickers
            </span>
            <span>{percentage}%</span>
          </div>
          <div className="w-full bg-gray-700 rounded-full h-2.5">
            <div
              className="bg-green-600 h-2.5 rounded-full transition-all duration-300"
              style={{ width: `${percentage}%` }}
            />
          </div>
        </div>
      );
    }
    return (
      <div className="mb-6">
        <div className="text-sm text-gray-300 mb-1">Working...</div>
        <div className="w-full bg-gray-700 rounded-full h-2.5">
          <div className="bg-green-600 h-2.5 rounded-full animate-pulse w-full" />
        </div>
      </div>
    );
  };

  const rankedSorted = useMemo<ScanItem[]>(() => {
    const ranked = result?.ranked ?? [];
    return [...ranked].sort(
      (a, b) =>
        (b.composite_score ?? b.scores?.combined ?? 0) -
        (a.composite_score ?? a.scores?.combined ?? 0),
    );
  }, [result?.ranked]);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-8">
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
          <h1 className="text-2xl font-bold text-white">Portfolio Scan</h1>
          <button
            onClick={() => void runScan()}
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
            {ageMinutes != null && <>&nbsp;·&nbsp;{formatAge(ageMinutes)}</>}
            {stale && (
              <>
                &nbsp;·&nbsp;<span className="font-semibold">stale</span>
              </>
            )}
          </div>
        )}

        {result?.partial_failure && (
          <div className="bg-yellow-900/40 border border-yellow-700 rounded-lg p-3 mb-4 text-yellow-200 text-sm">
            Partial scan: {result.failed_count ?? 0} ticker(s) failed to fetch. Results below
            exclude them.
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
            {/* ---- regime banner ---- */}
            {result.regime && <RegimeBanner regime={result.regime} />}

            <div className="text-center py-2">
              <div className="text-gray-400 text-sm">Portfolio Value</div>
              <div className="text-3xl font-bold text-white">
                {formatCurrency(result.portfolio_value)}
              </div>
            </div>

            {/* ---- risk strip: gauges + redundancy callout + alerts ---- */}
            {(result.portfolio_risk || (result.alerts && result.alerts.length > 0)) && (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {result.portfolio_risk && (
                  <div>
                    <h2 className="text-lg font-bold text-green-300 mb-3">Portfolio Risk</h2>
                    <RiskGauges portfolioRisk={result.portfolio_risk} />
                  </div>
                )}
                {result.portfolio_risk && (
                  <div>
                    <h2 className="text-lg font-bold text-green-300 mb-3">Concentration</h2>
                    <RedundancyCallout portfolioRisk={result.portfolio_risk} />
                  </div>
                )}
                <div>
                  <h2 className="text-lg font-bold text-green-300 mb-3">Alerts</h2>
                  <AlertTimeline alerts={result.alerts} maxItems={12} />
                </div>
              </div>
            )}

            {/* ---- CENTERPIECE: TradingView-style chart workspace ---- */}
            <div>
              <div className="flex flex-wrap items-center gap-3 mb-3">
                <h2 className="text-xl font-bold text-green-300">Chart Workspace</h2>
                <span className="text-xs text-gray-500">
                  Individual · Compare · Portfolio — live AI indicator layers
                </span>
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
                <div className="xl:col-span-3">
                  {selectableSymbols.length > 0 ? (
                    <ChartWorkspace
                      tickers={selectableSymbols}
                      initialSymbol={selected ?? undefined}
                      initialMode="individual"
                      initialRange="1y"
                      height={560}
                    />
                  ) : (
                    <div className="border-2 border-dashed border-gray-600 rounded-lg p-8 text-center text-gray-500">
                      No tickers to chart yet.
                    </div>
                  )}
                </div>
                <div>
                  <div className="flex flex-wrap items-center gap-2 mb-2">
                    <h3 className="text-sm font-semibold text-green-300">Signal Confluence</h3>
                    {selectableSymbols.length > 0 && (
                      <select
                        value={selected ?? ''}
                        onChange={(e) => setSelected(e.target.value || null)}
                        className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs text-white"
                        aria-label="Confluence ticker"
                      >
                        {selectableSymbols.map((sym) => (
                          <option key={sym} value={sym}>
                            {sym}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>
                  <SignalRadar symbol={selected ?? '—'} signals={signalsBlockOf(selectedItem)} size={240} />
                </div>
              </div>
            </div>

            {/* ---- buy/sell/hold scorecards ---- */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div>
                <h2 className="text-xl font-bold text-green-300 mb-4 flex items-center">
                  <span className="mr-2">🟢</span> Top Buys
                </h2>
                <div className="space-y-4">
                  {(result.top_buys ?? []).map((item, index) => renderCard(item, index))}
                </div>
              </div>
              <div>
                <h2 className="text-xl font-bold text-red-300 mb-4 flex items-center">
                  <span className="mr-2">🔴</span> Top Sells
                </h2>
                <div className="space-y-4">
                  {(result.top_sells ?? []).map((item, index) => renderCard(item, index))}
                </div>
              </div>
              <div>
                <h2 className="text-xl font-bold text-yellow-300 mb-4 flex items-center">
                  <span className="mr-2">🟡</span> Top Holds
                </h2>
                <div className="space-y-4">
                  {(result.top_holds ?? []).map((item, index) => renderCard(item, index))}
                </div>
              </div>
            </div>

            {/* ---- ranked table ---- */}
            <div>
              <h2 className="text-xl font-bold text-white mb-4">
                All Ranked Tickers ({result.ranked?.length ?? 0})
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
                      <th className="py-3 px-4 text-left" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-600">
                    {rankedSorted.map((item, index) => (
                      <React.Fragment key={item.symbol}>
                        <tr className="hover:bg-gray-600/50">
                          <td className="py-3 px-4 text-gray-300">{index + 1}</td>
                          <td className="py-3 px-4 font-medium">
                            <button
                              type="button"
                              onClick={() => setSelected(item.symbol)}
                              className={`hover:text-green-300 ${item.symbol === selected ? 'text-green-400' : ''}`}
                            >
                              {item.symbol}
                            </button>
                          </td>
                          <td className="py-3 px-4">
                            <span className={`px-2 py-1 rounded text-xs font-medium ${verdictColor(item.verdict)}`}>
                              {item.verdict}
                            </span>
                          </td>
                          <td className="py-3 px-4 font-mono text-green-300">
                            {formatScore(item.composite_score ?? item.scores?.combined)}
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
                            <td colSpan={8} className="px-4 pb-4">
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
