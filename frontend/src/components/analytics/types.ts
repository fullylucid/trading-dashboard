// Shared types for the sector-rotation / regime / signal visualizers.
//
// These mirror the exact JSON shapes the backend emits:
//   - `result.market.sectors[ETF]`  -> RRG raw values (RSRatioRow)
//   - `result.rotation[sector]`     -> fused rotation read (RotationRow)
//   - `result.companies`            -> holdings mapped onto rotation (CompaniesBlock)
//   - payload-level `regime`        -> RegimeBlock
//   - per-ticker `analytics.signals`-> SignalsBlock
//
// All number fields are nullable because the pure analytics layer degrades any
// uncomputable field to `null` rather than raising.

/** RRG quadrant label (from `sector_rotation/market.rrg_quadrant`). */
export type RrgQuadrant =
  | 'Leading'
  | 'Improving'
  | 'Weakening'
  | 'Lagging'
  | 'Neutral';

/** Rotation status (from `synthesis.fuse_rotation`). */
export type RotationStatus = 'rotating-IN' | 'rotating-OUT' | 'neutral';

/** Alert band (Tradeskeebot 80/60 thresholds). */
export type RotationAlert = 'immediate' | 'watch' | 'log';

/**
 * Raw per-ETF RRG row: `result.market.sectors[ETF_SYMBOL]`.
 * `rs_ratio` / `rs_momentum` are centered at 100 (RRG convention).
 */
export interface RsRatioRow {
  sector: string | null;
  rs_ratio: number | null;
  rs_momentum: number | null;
  quadrant: RrgQuadrant;
  roc?: Record<string, number | null>;
}

/**
 * Fused per-sector rotation read: `result.rotation[SECTOR_NAME]`.
 * `components` holds the signed [-100,100] sub-scores per stream (or null when
 * a stream was absent for that sector).
 */
export interface RotationRow {
  sector: string;
  etf: string | null;
  rotation_score: number;
  confidence: number;
  status: RotationStatus;
  alert: RotationAlert;
  phase: RrgQuadrant;
  components: Record<string, number | null>;
  present: string[];
  lagging_only: boolean;
}

/** A holding tagged with its sector's rotation read (`companies.tagged[]`). */
export interface TaggedHolding {
  symbol: string;
  sector: string | null;
  etf: string | null;
  rotation_score: number | null;
  confidence: number | null;
  status: RotationStatus | null;
  alert: RotationAlert | null;
  phase: RrgQuadrant | null;
  tag: 'tailwind' | 'risk' | 'neutral' | 'unknown';
}

/** `result.companies` — holdings mapped onto the sector rotation read. */
export interface CompaniesBlock {
  tagged: TaggedHolding[];
  tailwinds: string[];
  risks: string[];
  top_in_sectors: Array<{
    sector: string | null;
    etf: string | null;
    rotation_score: number | null;
    confidence: number | null;
    phase: RrgQuadrant | null;
    candidate_tickers: string[];
  }>;
}

/** Compact per-mover news read (`constituents.fetch_mover_news`). */
export interface MoverNews {
  count: number;
  net_tone: number;
  label: 'positive' | 'negative' | 'neutral';
  top_headline: string | null;
}

/** One constituent's contribution to its sector's move (`contributors.by_etf[ETF].leaders_*[]`). */
export interface ContributorRow {
  symbol: string;
  weight: number;
  pct_change: number | null;
  contribution: number | null;
  in_portfolio: boolean;
  in_watchlist: boolean;
  news: MoverNews | null;
}

/** Per-sector constituent contribution block (`contributors.by_etf[ETF]`). */
export interface SectorContributorBlock {
  etf: string;
  sector: string | null;
  net_contribution: number;
  n_up: number;
  n_down: number;
  n_tracked: number;
  breadth: number | null;
  leaders_up: ContributorRow[];
  leaders_down: ContributorRow[];
}

/** `result.contributors` — which stocks are pulling each sector. */
export interface ContributorsBlock {
  by_etf: Record<string, SectorContributorBlock>;
  quotes_ok: number;
  quotes_tried: number;
  sources_ok: boolean;
}

/** `result.assessment` — the LLM daily rotation read (concise + full briefing). */
export interface AssessmentBlock {
  short: string | null;
  full: string | null;
  model: string | null;
  generated_at: string | null;
}

/** Payload-level market-regime block (`scan_analytics.regime_block`). */
export interface RegimeBlock {
  regime_class: string | null;
  label: string | null;
  size_multiplier: number | null;
  stop_atr_multiplier: number | null;
  note: string | null;
  trend_direction?: string | null;
  volatility_regime?: string | null;
  estimated_probability?: number | null;
  benchmark?: string | null;
  used_spy_prices?: boolean;
}

/** Moving-average structure sub-block (`analytics.signals.ma_structure`). */
export interface MaStructure {
  above_50: boolean | null;
  above_200: boolean | null;
  golden_cross: boolean | null;
  death_cross: boolean | null;
  stacked_bullish: boolean | null;
}

/** Per-ticker signals sub-block (`analytics.signals` in the scan output). */
export interface SignalsBlock {
  rsi: number | null;
  macd: { macd: number | null; signal: number | null; hist: number | null } | null;
  divergence: 'bullish' | 'bearish' | null;
  ma_structure: MaStructure | null;
  roc: number | null;
  relative_strength: number | null;
  rvol: number | null;
  gap_pct: number | null;
  pct_of_52w_range: number | null;
}

/** Quadrant -> brand color, shared across the RRG + donut + banner. */
export const QUADRANT_COLORS: Record<RrgQuadrant, string> = {
  Leading: '#22c55e', // green  — top-right
  Improving: '#3b82f6', // blue   — top-left
  Weakening: '#f59e0b', // amber  — bottom-right
  Lagging: '#ef4444', // red    — bottom-left
  Neutral: '#94a3b8', // slate
};
