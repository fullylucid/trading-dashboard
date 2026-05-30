/**
 * CorrelationHeatmap — matrix heatmap of pairwise holding correlations from the
 * scan payload's `portfolio_risk.correlation_matrix`.
 *
 * The backend emits a nested dict { rowSym: { colSym: corr | null } } over the
 * rolling ~1-month window. We render it as a labeled grid of colored cells:
 *   +1 (move together)  -> red  (concentration risk)
 *    0 (uncorrelated)   -> dim
 *   -1 (hedged)         -> cyan
 *
 * Null cells (insufficient overlap) render as a dim dash. Pure CSS-grid + a
 * tiny color-lerp; no chart deps.
 */

import React from 'react';
import type { CorrelationMatrix } from '../../types/scanAnalytics';

export interface CorrelationHeatmapProps {
  matrix: CorrelationMatrix | null | undefined;
  /** Cell edge length in px. */
  cellSize?: number;
  className?: string;
}

/** Collect a stable, sorted, union list of symbols across rows and columns. */
function symbolsOf(matrix: CorrelationMatrix): string[] {
  const set = new Set<string>();
  for (const row of Object.keys(matrix)) {
    set.add(row);
    const cols = matrix[row];
    if (cols) for (const c of Object.keys(cols)) set.add(c);
  }
  return Array.from(set).sort();
}

/** Map a correlation in [-1, 1] to an rgba background color. */
function corrColor(v: number): string {
  const c = Math.max(-1, Math.min(1, v));
  if (c >= 0) {
    // 0 -> dim, +1 -> red
    const a = (0.12 + 0.78 * c).toFixed(3);
    return `rgba(255, 0, 60, ${a})`;
  }
  // 0 -> dim, -1 -> cyan
  const a = (0.12 + 0.78 * -c).toFixed(3);
  return `rgba(0, 217, 255, ${a})`;
}

function cellTextColor(v: number): string {
  return Math.abs(v) > 0.55 ? '#0a0e0a' : 'var(--text-primary)';
}

const CorrelationHeatmap: React.FC<CorrelationHeatmapProps> = ({
  matrix,
  cellSize = 34,
  className,
}) => {
  if (!matrix || Object.keys(matrix).length === 0) {
    return (
      <div
        className={className}
        style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', fontSize: 12, padding: 12 }}
      >
        No correlation matrix (need 2+ holdings with overlapping history).
      </div>
    );
  }

  const syms = symbolsOf(matrix);
  const labelW = 48;

  const getCorr = (row: string, col: string): number | null => {
    const r = matrix[row];
    if (!r) return null;
    const v = r[col];
    return typeof v === 'number' && Number.isFinite(v) ? v : null;
  };

  return (
    <div
      className={className}
      style={{
        padding: 12,
        background: 'var(--bg-panel)',
        border: '1px solid var(--border)',
        borderRadius: 2,
        overflowX: 'auto',
        fontFamily: 'var(--font-mono)',
      }}
    >
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `${labelW}px repeat(${syms.length}, ${cellSize}px)`,
          gap: 2,
          width: 'max-content',
        }}
      >
        {/* top-left corner spacer */}
        <div />
        {/* column headers */}
        {syms.map((c) => (
          <div
            key={`col-${c}`}
            style={{
              fontSize: 9,
              color: 'var(--text-secondary)',
              textAlign: 'center',
              alignSelf: 'end',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
            title={c}
          >
            {c}
          </div>
        ))}

        {/* rows */}
        {syms.map((row) => (
          <React.Fragment key={`row-${row}`}>
            <div
              style={{
                fontSize: 10,
                color: 'var(--text-secondary)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'flex-end',
                paddingRight: 4,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
              title={row}
            >
              {row}
            </div>
            {syms.map((col) => {
              const v = getCorr(row, col);
              const isDiag = row === col;
              if (v === null) {
                return (
                  <div
                    key={`${row}-${col}`}
                    style={{
                      width: cellSize,
                      height: cellSize,
                      background: 'var(--bg-elevated)',
                      color: 'var(--text-secondary)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 10,
                      opacity: 0.5,
                    }}
                    title={`${row} vs ${col}: n/a`}
                  >
                    —
                  </div>
                );
              }
              return (
                <div
                  key={`${row}-${col}`}
                  style={{
                    width: cellSize,
                    height: cellSize,
                    background: corrColor(v),
                    color: cellTextColor(v),
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 9.5,
                    fontWeight: isDiag ? 700 : 500,
                    outline: isDiag ? '1px solid var(--border-active)' : 'none',
                  }}
                  title={`${row} vs ${col}: ${v.toFixed(2)}`}
                >
                  {v.toFixed(2)}
                </div>
              );
            })}
          </React.Fragment>
        ))}
      </div>

      {/* legend */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginTop: 10,
          fontSize: 9,
          color: 'var(--text-secondary)',
        }}
      >
        <span>-1</span>
        <div
          style={{
            flex: 1,
            height: 8,
            maxWidth: 200,
            background:
              'linear-gradient(90deg, rgba(0,217,255,0.9), rgba(0,217,255,0.12), rgba(255,0,60,0.12), rgba(255,0,60,0.9))',
            border: '1px solid var(--border)',
          }}
        />
        <span>+1</span>
        <span style={{ marginLeft: 8 }}>cyan = hedged · red = moves together</span>
      </div>
    </div>
  );
};

export default CorrelationHeatmap;
