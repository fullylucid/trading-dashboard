/**
 * Charts — the full-width home for the TradingView-style ChartWorkspace.
 *
 * This is the same workspace embedded as the centerpiece of PortfolioScan, but
 * given the whole viewport: individual / compare / portfolio modes, custom AI
 * indicator layers, all sourced from the `/api/chart/*` endpoints. The ticker
 * picker is seeded from the latest portfolio-scan snapshot (instant load), with
 * a small benchmark fallback so the page is useful even before a scan exists.
 */

import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';

import ChartWorkspace from '../components/charts/ChartWorkspace';

interface ScanItem {
  symbol: string;
}

interface ScanResult {
  ranked?: ScanItem[];
  top_buys?: ScanItem[];
}

interface SnapshotResponse {
  result: ScanResult;
}

/** Benchmark fallback when no scan snapshot is available yet. */
const FALLBACK_TICKERS: string[] = ['SPY', 'QQQ', 'IWM'];

const Charts: React.FC = () => {
  const [tickers, setTickers] = useState<string[]>([]);
  const [loaded, setLoaded] = useState<boolean>(false);

  useEffect(() => {
    let cancelled = false;
    axios
      .get<SnapshotResponse>('/api/portfolio/scan/latest')
      .then((resp) => {
        if (cancelled) return;
        const ranked = resp.data.result.ranked ?? [];
        const syms = ranked.map((i) => i.symbol).filter(Boolean);
        setTickers(syms);
      })
      .catch(() => {
        if (!cancelled) setTickers([]);
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const tickerList = useMemo<string[]>(
    () => (tickers.length > 0 ? tickers : FALLBACK_TICKERS),
    [tickers],
  );

  return (
    <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-8">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h1 className="text-2xl font-bold text-white">Charts</h1>
        <span className="text-xs text-gray-500">
          {tickers.length > 0
            ? `${tickers.length} holdings from latest scan`
            : loaded
              ? 'No scan snapshot — showing benchmarks'
              : 'Loading…'}
        </span>
      </div>

      <ChartWorkspace
        tickers={tickerList}
        initialMode="individual"
        initialRange="1y"
        height={640}
      />
    </div>
  );
};

export default Charts;
