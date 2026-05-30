/**
 * RedundancyCallout — compact, actionable replacement for the giant N×N
 * CorrelationHeatmap.
 *
 * Instead of rendering the full pairwise matrix, this distills the scan
 * payload's `portfolio_risk.correlation_matrix` (+ `weights`) down to the only
 * thing a trader acts on: the handful of highly-correlated pairs where BOTH
 * legs carry meaningful weight (i.e. real redundant exposure), ranked by a
 * simple "redundancy" score, plus a one-line effective-N / concentration note.
 *
 * Math is read-only off the already-computed backend block — we don't recompute
 * correlations (the backend's rolling-window pearson is the source of truth);
 * we just filter/rank what it emitted. Pure inline styles, no chart deps.
 *
 * A pair qualifies when:
 *   |corr| >= CORR_THRESHOLD              (default 0.70 — moves together / hedged)
 *   min(weightA, weightB) >= WEIGHT_FLOOR (both legs are material, not dust)
 *
 * Score = |corr| * min(weightA, weightB) — biggest redundant dollar overlap
 * first. The smaller-weight leg is flagged as the "trim" candidate.
 */

import React from 'react';
import type { CorrelationMatrix, PortfolioRisk } from '../../types/scanAnalytics';

export interface RedundancyCalloutProps {
  portfolioRisk: PortfolioRisk | null | undefined;
  /** |corr| at/above which a pair is considered redundant. Default 0.70. */
  corrThreshold?: number;
  /**
   * Minimum portfolio weight (fraction, 0..1) BOTH legs must clear for the pair
   * to matter. Default 0.05 (5%). If no weights are present we fall back to
   * showing the strongest correlations regardless of size.
   */
  weightFloor?: number;
  /** Cap on how many pairs to list. Default 5. */
  maxPairs?: number;
  className?: string;
}

const RED = '#ff003c';
const CYAN = '#00d9ff';
const AMBER = '#ffb000';

interface RankedPair {
  a: string;
  b: string;
  corr: number;
  /** Weight of each leg as a fraction (0..1), or null when unknown. */
  weightA: number | null;
  weightB: number | null;
  /** The smaller-weight leg — the trim candidate. */
  trim: string;
  /** Ranking score; higher = more redundant exposure. */
  score: number;
}

function num(v: number | null | undefined): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

/**
 * Normalize a raw weights map to fractions summing to ~1. The backend may emit
 * weights already as fractions, or as raw dollar/share notionals — we divide by
 * the total so the floor comparison is meaningful either way.
 */
function normalizeWeights(
  raw: Record<string, number> | undefined,
): Record<string, number> | null {
  if (!raw) return null;
  let total = 0;
  const clean: Record<string, number> = {};
  for (const [sym, w] of Object.entries(raw)) {
    const v = num(w);
    if (v !== null && v > 0) {
      clean[sym] = v;
      total += v;
    }
  }
  if (total <= 0) return null;
  const out: Record<string, number> = {};
  for (const [sym, w] of Object.entries(clean)) out[sym] = w / total;
  return out;
}

/** Pull the upper-triangle of the matrix as deduped, finite pairs. */
function extractPairs(
  matrix: CorrelationMatrix,
  weights: Record<string, number> | null,
  corrThreshold: number,
  weightFloor: number,
): RankedPair[] {
  const seen = new Set<string>();
  const pairs: RankedPair[] = [];

  for (const a of Object.keys(matrix)) {
    const cols = matrix[a];
    if (!cols) continue;
    for (const b of Object.keys(cols)) {
      if (a === b) continue;
      const key = a < b ? `${a}|${b}` : `${b}|${a}`;
      if (seen.has(key)) continue;
      seen.add(key);

      const corr = num(cols[b]);
      if (corr === null) continue;
      if (Math.abs(corr) < corrThreshold) continue;

      const weightA = weights ? num(weights[a]) ?? 0 : null;
      const weightB = weights ? num(weights[b]) ?? 0 : null;

      // When weights exist, require BOTH legs to be material.
      if (weights) {
        const minW = Math.min(weightA ?? 0, weightB ?? 0);
        if (minW < weightFloor) continue;
      }

      const minW =
        weightA !== null && weightB !== null ? Math.min(weightA, weightB) : 1;
      // Smaller leg is the trim candidate (tie -> alphabetical for stability).
      let trim: string;
      if (weightA !== null && weightB !== null && weightA !== weightB) {
        trim = weightA < weightB ? a : b;
      } else {
        trim = a < b ? a : b;
      }

      pairs.push({
        a,
        b,
        corr,
        weightA,
        weightB,
        trim,
        score: Math.abs(corr) * minW,
      });
    }
  }

  pairs.sort((x, y) => y.score - x.score);
  return pairs;
}

function fmtPct(frac: number | null): string {
  if (frac === null) return '';
  return `${(frac * 100).toFixed(0)}%`;
}

const RedundancyCallout: React.FC<RedundancyCalloutProps> = ({
  portfolioRisk,
  corrThreshold = 0.7,
  weightFloor = 0.05,
  maxPairs = 5,
  className,
}) => {
  const matrix: CorrelationMatrix | null = portfolioRisk?.correlation_matrix ?? null;
  const weights = normalizeWeights(portfolioRisk?.weights);
  const effN = num(portfolioRisk?.effective_number ?? null);
  const hhi = num(portfolioRisk?.hhi ?? null);
  const holdingsCount = weights ? Object.keys(weights).length : null;

  const cardStyle: React.CSSProperties = {
    padding: 12,
    background: 'var(--bg-panel)',
    border: '1px solid var(--border)',
    borderRadius: 2,
    fontFamily: 'var(--font-mono)',
    fontSize: 12,
    color: 'var(--text-primary)',
    maxWidth: 420,
  };

  const headerStyle: React.CSSProperties = {
    fontSize: 10,
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    color: 'var(--text-secondary)',
    marginBottom: 8,
  };

  if (!matrix || Object.keys(matrix).length === 0) {
    return (
      <div className={className} style={cardStyle}>
        <div style={headerStyle}>Concentration / Redundancy</div>
        <div style={{ color: 'var(--text-secondary)' }}>
          No correlation data (need 2+ holdings with overlapping history).
        </div>
      </div>
    );
  }

  const pairs = extractPairs(matrix, weights, corrThreshold, weightFloor).slice(
    0,
    maxPairs,
  );

  // Effective-N concentration note.
  let concentrationNote: React.ReactNode = null;
  if (effN !== null) {
    const denom = holdingsCount ?? Object.keys(matrix).length;
    const ratio = denom > 0 ? effN / denom : 1;
    const concentrated = ratio < 0.6 || effN < 3;
    concentrationNote = (
      <div
        style={{
          marginTop: pairs.length > 0 ? 10 : 0,
          paddingTop: 8,
          borderTop: '1px solid var(--border)',
          fontSize: 11,
          color: concentrated ? AMBER : 'var(--text-secondary)',
          display: 'flex',
          alignItems: 'baseline',
          gap: 6,
          flexWrap: 'wrap',
        }}
      >
        <span style={{ fontWeight: 700 }}>
          Effective N {effN.toFixed(1)}
        </span>
        <span style={{ color: 'var(--text-secondary)' }}>
          of {denom} {denom === 1 ? 'name' : 'names'}
          {hhi !== null ? ` · HHI ${hhi.toFixed(2)}` : ''}
        </span>
        <span style={{ color: concentrated ? AMBER : 'var(--text-secondary)' }}>
          {concentrated
            ? '— concentrated; diversification is thinner than the holding count suggests.'
            : '— reasonably diversified.'}
        </span>
      </div>
    );
  }

  return (
    <div className={className} style={cardStyle}>
      <div style={headerStyle}>Concentration / Redundancy</div>

      {pairs.length === 0 ? (
        <div style={{ color: 'var(--text-secondary)', fontSize: 11 }}>
          No redundant pairs (none above |corr| {corrThreshold.toFixed(2)}
          {weights ? ` with both legs ≥ ${fmtPct(weightFloor)}` : ''}). Holdings
          look independent.
        </div>
      ) : (
        <ol style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {pairs.map((p) => {
            const hedged = p.corr < 0;
            const accent = hedged ? CYAN : RED;
            const verb = hedged ? 'inversely linked' : 'redundant';
            const trimWeight =
              p.trim === p.a ? p.weightA : p.weightB;
            const advice = hedged
              ? '— hedged pair; sizing one offsets the other.'
              : `— ${verb}; consider trimming the smaller leg (${p.trim}${
                  trimWeight !== null ? ` ${fmtPct(trimWeight)}` : ''
                }).`;
            return (
              <li
                key={`${p.a}-${p.b}`}
                style={{
                  display: 'flex',
                  alignItems: 'baseline',
                  gap: 8,
                  padding: '5px 0',
                  borderBottom: '1px solid var(--border)',
                  lineHeight: 1.35,
                }}
              >
                <span
                  style={{
                    fontWeight: 700,
                    whiteSpace: 'nowrap',
                    color: 'var(--text-primary)',
                  }}
                >
                  {p.a} ↔ {p.b}
                </span>
                <span
                  style={{
                    fontWeight: 700,
                    color: accent,
                    fontVariantNumeric: 'tabular-nums',
                  }}
                >
                  {p.corr >= 0 ? '+' : ''}
                  {p.corr.toFixed(2)}
                </span>
                <span style={{ color: 'var(--text-secondary)', fontSize: 11 }}>
                  {advice}
                </span>
              </li>
            );
          })}
        </ol>
      )}

      {concentrationNote}
    </div>
  );
};

export default RedundancyCallout;
