/**
 * Strict TypeScript shapes for the scan_analytics payload consumed by the
 * Phase-3 risk-visualization components.
 *
 * These mirror what `backend/scan_analytics.py` emits:
 *  - payload-level `portfolio_risk` (PortfolioRisk)
 *  - per-ticker `analytics` (TickerAnalytics) + `signals` (TickerSignals)
 *  - payload-level ranked `alerts` (build_alerts -> ScoredAlert[])
 *
 * Every numeric field is `number | null` where the backend may omit it (it
 * folds NaN/None to null and omits failed sub-blocks). Nothing here assumes a
 * field is present; consumers must null-guard.
 */

/** VaR sub-block as emitted under portfolio_risk.var_95. */
export interface VarBlock {
  historical: number | null;
  parametric: number | null;
  confidence: number;
  horizon: string;
  units: string;
}

/** A single sector-exposure row. */
export interface SectorExposureRow {
  sector: string;
  weight: number;
}

/**
 * JSON-friendly correlation matrix: { rowSym: { colSym: corr | null } }.
 * Diagonal is ~1.0; missing pairs are null.
 */
export type CorrelationMatrix = Record<string, Record<string, number | null>>;

/** Payload-level portfolio_risk block (all fields optional / nullable). */
export interface PortfolioRisk {
  benchmark?: string;
  periods_per_year?: number;
  holdings_used?: string[];
  correlation_window_bars?: number;

  hhi?: number | null;
  effective_number?: number | null;
  weights?: Record<string, number>;
  sector_exposure?: SectorExposureRow[] | Record<string, number>;

  annualized_vol?: number | null;
  var_95?: VarBlock;
  sharpe?: number | null;
  sortino?: number | null;
  max_drawdown?: number | null;
  max_drawdown_note?: string;

  beta_to_spy?: number | null;
  per_holding_beta?: Record<string, number>;

  correlation_matrix?: CorrelationMatrix;
  data_gaps?: string[];
}

/** Per-ticker technical `signals` sub-block (only the fields the viz reads). */
export interface TickerSignals {
  rsi?: number | null;
  macd?: number | null;
  macd_signal?: number | null;
  macd_hist?: number | null;
  sma_20?: number | null;
  sma_50?: number | null;
  sma_200?: number | null;
  relative_strength?: number | null;
  days_to_earnings?: number | null;
  /** Recent adjusted-close series, oldest -> newest, when present. */
  price_series?: number[] | null;
  [key: string]: unknown;
}

/** Per-ticker `insider` sub-block (subset). */
export interface TickerInsider {
  has_cluster?: boolean;
  confidence?: number | null;
  buy_count?: number | null;
  net_dollars?: number | null;
  [key: string]: unknown;
}

/** Per-ticker `analytics` block. */
export interface TickerAnalytics {
  symbol?: string;
  entry_price?: number | null;
  stop_from_entry?: number | null;
  distance_to_stop_pct?: number | null;
  unrealized_r?: number | null;
  r_multiple?: number | null;
  suggested_size_shares?: number | null;
  suggested_risk_dollars?: number | null;
  annualized_vol?: number | null;
  beta_to_spy?: number | null;
  days_held?: number | null;
  signals?: TickerSignals;
  insider?: TickerInsider;
  data_gaps?: string[];
  [key: string]: unknown;
}

export type AlertBucket = 'alert' | 'watch' | 'log';
export type AlertDirection = 'bullish' | 'bearish' | 'neutral' | 'context';

/** A contributing factor row inside a ScoredAlert. */
export interface AlertFactor {
  factor: string;
  detail: string;
  points: number;
  direction: AlertDirection;
}

/** One ranked alert as produced by analytics.score_alert / build_alerts. */
export interface ScoredAlert {
  symbol: string | null;
  bucket: AlertBucket;
  confidence: number;
  direction: AlertDirection;
  contributing_factors: AlertFactor[];
  score_breakdown: {
    bullish: number;
    bearish: number;
  };
}
