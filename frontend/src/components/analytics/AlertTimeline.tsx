/**
 * AlertTimeline — ranked list/timeline of multi-signal alerts produced by the
 * scan's `build_alerts` (analytics.score_alert) stage.
 *
 * Each alert carries a bucket (alert/watch/log), a 0..100 confidence, a
 * direction (bullish/bearish/neutral), and its contributing factors. We render
 * them as a vertical timeline ordered the way the backend already ranked them
 * (alert > watch > log, then confidence desc), with a confidence bar, a
 * direction-colored node, and the top contributing factors.
 *
 * Pure CSS; no chart deps.
 */

import React from 'react';
import type { ScoredAlert, AlertBucket, AlertDirection } from '../../types/scanAnalytics';

export interface AlertTimelineProps {
  alerts: ReadonlyArray<ScoredAlert> | null | undefined;
  /** Cap the number rendered (after the backend's own ranking). */
  maxItems?: number;
  className?: string;
}

const GREEN = '#00ff41';
const RED = '#ff003c';
const AMBER = '#ffb000';
const DIM = '#88aa88';

function bucketColor(bucket: AlertBucket): string {
  switch (bucket) {
    case 'alert':
      return RED;
    case 'watch':
      return AMBER;
    default:
      return DIM;
  }
}

function directionColor(direction: AlertDirection): string {
  switch (direction) {
    case 'bullish':
      return GREEN;
    case 'bearish':
      return RED;
    default:
      return DIM;
  }
}

function directionGlyph(direction: AlertDirection): string {
  switch (direction) {
    case 'bullish':
      return '▲';
    case 'bearish':
      return '▼';
    default:
      return '◆';
  }
}

const AlertRow: React.FC<{ alert: ScoredAlert }> = ({ alert }) => {
  const bColor = bucketColor(alert.bucket);
  const dColor = directionColor(alert.direction);
  const conf = Math.max(0, Math.min(100, alert.confidence));
  const topFactors = [...alert.contributing_factors]
    .filter((f) => f.direction !== 'context')
    .slice(0, 3);

  return (
    <div style={{ display: 'flex', gap: 10, position: 'relative', paddingBottom: 14 }}>
      {/* timeline rail + node */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 16 }}>
        <div
          style={{
            width: 12,
            height: 12,
            borderRadius: '50%',
            background: bColor,
            boxShadow: `0 0 6px ${bColor}88`,
            flexShrink: 0,
            marginTop: 2,
          }}
          aria-hidden
        />
        <div style={{ flex: 1, width: 2, background: 'var(--border)', marginTop: 2 }} aria-hidden />
      </div>

      {/* body */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>
            {alert.symbol ?? '—'}
          </span>
          <span style={{ fontSize: 11, color: dColor }}>
            {directionGlyph(alert.direction)} {alert.direction}
          </span>
          <span
            style={{
              fontSize: 9,
              textTransform: 'uppercase',
              letterSpacing: 0.5,
              color: bColor,
              border: `1px solid ${bColor}`,
              borderRadius: 2,
              padding: '0 4px',
            }}
          >
            {alert.bucket}
          </span>
          <span style={{ fontSize: 11, color: 'var(--text-secondary)', marginLeft: 'auto' }}>
            {conf.toFixed(0)}%
          </span>
        </div>

        {/* confidence bar */}
        <div
          style={{
            marginTop: 4,
            height: 5,
            background: 'var(--bg-elevated)',
            borderRadius: 2,
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              width: `${conf}%`,
              height: '100%',
              background: bColor,
              transition: 'width 0.3s ease',
            }}
          />
        </div>

        {/* factors */}
        {topFactors.length > 0 && (
          <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 2 }}>
            {topFactors.map((f, i) => (
              <div
                key={`${f.factor}-${i}`}
                style={{ fontSize: 10.5, color: 'var(--text-secondary)', display: 'flex', gap: 6 }}
              >
                <span style={{ color: directionColor(f.direction), flexShrink: 0 }}>
                  {directionGlyph(f.direction)}
                </span>
                <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {f.detail}
                </span>
                {Number.isFinite(f.points) && f.points > 0 && (
                  <span style={{ color: 'var(--text-secondary)', opacity: 0.7 }}>+{f.points.toFixed(0)}</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

const AlertTimeline: React.FC<AlertTimelineProps> = ({ alerts, maxItems = 20, className }) => {
  if (!alerts || alerts.length === 0) {
    return (
      <div
        className={className}
        style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', fontSize: 12, padding: 12 }}
      >
        No alerts.
      </div>
    );
  }

  const shown = alerts.slice(0, maxItems);

  return (
    <div
      className={className}
      style={{
        padding: '12px 12px 0',
        background: 'var(--bg-panel)',
        border: '1px solid var(--border)',
        borderRadius: 2,
        fontFamily: 'var(--font-mono)',
      }}
    >
      {shown.map((a, i) => (
        <AlertRow key={`${a.symbol ?? 'n'}-${i}`} alert={a} />
      ))}
    </div>
  );
};

export default AlertTimeline;
