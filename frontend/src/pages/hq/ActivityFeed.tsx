import { GREEN, DIM, FAINT, BLUE, AMBER } from './ui';
import type { ActivityItem, ActivityKind } from './types';

// Hydra HQ 🛰️ — fleet activity feed (Slice 4). A newest-first stream of PR opened/merged
// events + each head's in-progress commits, built host-side into hq:fleet.activity.

const KIND_META: Record<ActivityKind, { glyph: string; color: string; label: string }> = {
  commit: { glyph: '◆', color: GREEN, label: 'commit' },
  pr_opened: { glyph: '⊕', color: BLUE, label: 'PR opened' },
  pr_merged: { glyph: '✓', color: AMBER, label: 'PR merged' },
};

function ago(ts: number): string {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

function Row({ it }: { it: ActivityItem }) {
  const m = KIND_META[it.kind] ?? KIND_META.commit;
  const tag = it.head ?? it.room;
  const body = (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, padding: '3px 0', fontSize: 12 }}>
      <span style={{ color: m.color, width: 12, flex: '0 0 auto', textAlign: 'center' }} title={m.label}>{m.glyph}</span>
      <span style={{ color: BLUE, flex: '0 0 auto', fontSize: 11 }}>{tag}</span>
      <span style={{ color: 'rgba(0,255,65,0.85)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {it.number ? <span style={{ color: DIM }}>#{it.number} </span> : null}
        {it.sha ? <span style={{ color: DIM, fontFamily: 'monospace' }}>{it.sha.slice(0, 7)} </span> : null}
        {it.text}
      </span>
      <span style={{ color: DIM, flex: '0 0 auto', fontSize: 10 }}>{ago(it.ts)}</span>
    </div>
  );
  return it.url ? (
    <a href={it.url} target="_blank" rel="noreferrer" style={{ textDecoration: 'none', color: 'inherit', display: 'block' }}>
      {body}
    </a>
  ) : (
    body
  );
}

export default function ActivityFeed({ items, limit = 30 }: { items: ActivityItem[]; limit?: number }) {
  if (!items.length) {
    return <div style={{ color: DIM, fontSize: 12 }}>no recent fleet activity</div>;
  }
  return (
    <div style={{ border: `1px solid ${FAINT}`, borderRadius: 6, padding: '8px 12px', background: 'rgba(0,255,65,0.03)' }}>
      {items.slice(0, limit).map((it, i) => (
        <Row key={`${it.kind}-${it.number ?? it.sha ?? i}`} it={it} />
      ))}
    </div>
  );
}
