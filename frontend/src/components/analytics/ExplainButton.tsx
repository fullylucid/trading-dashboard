/**
 * ExplainButton — a tiny, reusable "ask Claude" affordance for any datapoint.
 *
 * Renders a small button; on click it POSTs the given {kind, context, symbol}
 * to /api/ai/explain and shows the returned blurb in place. On-demand by design
 * (one free-Opus worker job per click) — not auto-loaded — so a page render
 * never fans out a dozen jobs. Used by RegimeBanner, AlertTimeline,
 * SectorRotation, and anywhere else a datapoint deserves a plain-language read.
 */

import React, { useState } from 'react';
import { explainDatapoint } from '../../lib/aiApi';
import type { ExplainKind } from '../../lib/aiApi';

export interface ExplainButtonProps {
  kind: ExplainKind;
  context: Record<string, unknown>;
  symbol?: string;
  /** Button label before first run. */
  label?: string;
  className?: string;
}

const ACCENT = '#a78bfa'; // violet = "AI"

const ExplainButton: React.FC<ExplainButtonProps> = ({
  kind,
  context,
  symbol,
  label = '✦ Explain',
  className,
}) => {
  const [loading, setLoading] = useState(false);
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      const res = await explainDatapoint(kind, context, symbol);
      setText(res.text);
    } catch {
      setError('AI read unavailable (worker busy or offline).');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={className} style={{ marginTop: 6 }}>
      {text == null && (
        <button type="button" onClick={() => void run()} disabled={loading} style={btnStyle}>
          {loading ? 'Reading…' : label}
        </button>
      )}
      {error && <div style={errStyle}>{error}</div>}
      {text && (
        <div style={blurbStyle}>
          <span style={{ color: ACCENT, fontWeight: 700, marginRight: 6 }}>✦</span>
          {text}
        </div>
      )}
    </div>
  );
};

const btnStyle: React.CSSProperties = {
  background: 'transparent',
  color: ACCENT,
  border: `1px solid ${ACCENT}66`,
  borderRadius: 4,
  padding: '2px 8px',
  fontSize: 11,
  fontWeight: 600,
  cursor: 'pointer',
  lineHeight: 1.6,
};

const blurbStyle: React.CSSProperties = {
  marginTop: 4,
  padding: '8px 10px',
  fontSize: 12,
  lineHeight: 1.5,
  color: '#cbd5e1',
  background: 'rgba(167,139,250,0.08)',
  border: '1px solid rgba(167,139,250,0.25)',
  borderRadius: 6,
  whiteSpace: 'pre-wrap',
};

const errStyle: React.CSSProperties = {
  marginTop: 4,
  fontSize: 11,
  color: '#f59e0b',
};

export default ExplainButton;
