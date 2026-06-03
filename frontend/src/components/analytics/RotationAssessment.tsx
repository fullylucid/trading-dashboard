/**
 * RotationAssessment — the LLM daily rotation read.
 *
 * Renders `result.assessment` (generated once/day by the Opus worker and cached
 * in the snapshot): the concise `short` read is always visible; the full
 * markdown briefing lives behind a "Deep dive" expander.
 *
 * No markdown dependency — a tiny inline renderer handles the subset the model
 * emits (headings, bullets, bold). Degrades to nothing when there's no read.
 */

import { useMemo, useState } from 'react';
import type { AssessmentBlock } from './types';

const AI_ACCENT = '#a78bfa'; // violet, matching ExplainButton's "AI" theme.

export interface RotationAssessmentProps {
  assessment: AssessmentBlock | null | undefined;
}

/** Inline-render `**bold**` spans within a single line of text. */
function renderInline(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) =>
    p.startsWith('**') && p.endsWith('**') ? (
      <strong key={i} style={{ color: 'var(--text-primary)' }}>
        {p.slice(2, -2)}
      </strong>
    ) : (
      <span key={i}>{p}</span>
    ),
  );
}

/** Minimal markdown -> React: headings (#, ##, ###), bullets (-, *), paragraphs. */
function renderMarkdown(md: string): React.ReactNode[] {
  const lines = md.split('\n');
  const out: React.ReactNode[] = [];
  let bullets: string[] = [];

  const flushBullets = () => {
    if (bullets.length === 0) return;
    out.push(
      <ul key={`ul-${out.length}`} style={{ margin: '4px 0 10px', paddingLeft: 18 }}>
        {bullets.map((b, i) => (
          <li key={i} style={{ fontSize: 13, lineHeight: 1.5, marginBottom: 3 }}>
            {renderInline(b)}
          </li>
        ))}
      </ul>,
    );
    bullets = [];
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const trimmed = line.trim();
    if (trimmed === '') {
      flushBullets();
      continue;
    }
    const bullet = /^[-*]\s+(.*)$/.exec(trimmed);
    if (bullet) {
      bullets.push(bullet[1]);
      continue;
    }
    flushBullets();
    const heading = /^(#{1,3})\s+(.*)$/.exec(trimmed);
    if (heading) {
      const level = heading[1].length;
      out.push(
        <div
          key={`h-${out.length}`}
          style={{
            fontSize: level === 1 ? 15 : 13,
            fontWeight: 700,
            color: 'var(--text-primary)',
            textTransform: level >= 2 ? 'uppercase' : 'none',
            letterSpacing: level >= 2 ? 0.4 : 0,
            margin: '12px 0 4px',
          }}
        >
          {renderInline(heading[2])}
        </div>,
      );
      continue;
    }
    out.push(
      <p key={`p-${out.length}`} style={{ fontSize: 13, lineHeight: 1.55, margin: '0 0 8px' }}>
        {renderInline(trimmed)}
      </p>,
    );
  }
  flushBullets();
  return out;
}

const RotationAssessment: React.FC<RotationAssessmentProps> = ({ assessment }) => {
  const [open, setOpen] = useState<boolean>(false);
  const fullNodes = useMemo(
    () => (assessment?.full ? renderMarkdown(assessment.full) : null),
    [assessment?.full],
  );

  if (!assessment || (!assessment.short && !assessment.full)) return null;

  const hasDeepDive = Boolean(assessment.full && assessment.full !== assessment.short);

  return (
    <div
      style={{
        background: 'var(--bg-panel)',
        border: `1px solid ${AI_ACCENT}55`,
        borderRadius: 8,
        padding: 16,
        boxShadow: `0 0 12px ${AI_ACCENT}22`,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <h2
          style={{
            fontSize: 13,
            fontWeight: 700,
            color: AI_ACCENT,
            margin: 0,
            textTransform: 'uppercase',
            letterSpacing: 0.5,
          }}
        >
          ✦ Daily Rotation Read
        </h2>
        {assessment.model && (
          <span style={{ fontSize: 10, color: 'var(--text-secondary)' }}>{assessment.model}</span>
        )}
      </div>

      {assessment.short && (
        <p style={{ fontSize: 14, lineHeight: 1.6, color: 'var(--text-primary)', margin: '10px 0 0' }}>
          {assessment.short}
        </p>
      )}

      {hasDeepDive && (
        <>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            style={{
              marginTop: 12,
              background: 'transparent',
              color: AI_ACCENT,
              border: `1px solid ${AI_ACCENT}66`,
              borderRadius: 4,
              padding: '4px 12px',
              fontSize: 12,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            {open ? 'Hide deep dive ▴' : 'Deep dive ▾'}
          </button>
          {open && (
            <div
              style={{
                marginTop: 12,
                paddingTop: 12,
                borderTop: '1px solid var(--border)',
                color: 'var(--text-secondary)',
              }}
            >
              {fullNodes}
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default RotationAssessment;
