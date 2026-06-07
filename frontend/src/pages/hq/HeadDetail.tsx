import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import PageHeader from '../../components/PageHeader';
import { GREEN, DIM, FAINT, AMBER, RED, BLUE, card, fmtAge, STATUS_META, StatusDot, Pill } from './ui';
import type { HeadDetail as HeadDetailT, HeadDetailResponse } from './types';

// Hydra HQ 🛰️ — per-head detail (Slice 5). One head's full card: live status, git + recent
// commits, the PRs it owns, its memory scope, and its fossil-archive index (metadata only —
// no transcript bodies ever leave the host). "Drive in RC" links out to Remote Control.

function ago(ts: number | null): string {
  return ts == null ? '—' : fmtAge(Math.max(0, Date.now() / 1000 - ts));
}

function Section({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <section style={{ marginBottom: 20 }}>
      <div style={{ color: GREEN, fontWeight: 700, fontSize: 15, marginBottom: 8 }}>
        {title}
        {count != null && <span style={{ color: DIM, fontWeight: 400, fontSize: 12 }}> ({count})</span>}
      </div>
      {children}
    </section>
  );
}

export default function HeadDetail() {
  const { name = '' } = useParams();
  const [head, setHead] = useState<HeadDetailT | null>(null);
  const [err, setErr] = useState<number | 'net' | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const r = await fetch(`/api/hq/head/${encodeURIComponent(name)}`);
        if (!r.ok) {
          if (active) setErr(r.status);
          return;
        }
        const d = (await r.json()) as HeadDetailResponse;
        if (active && d.available && d.head) {
          setHead(d.head);
          setErr(null);
        }
      } catch {
        if (active) setErr('net');
      }
    };
    load();
    const t = setInterval(load, 8000);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, [name]);

  const m = head ? STATUS_META[head.status] ?? STATUS_META.offline : null;

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '0 16px 40px', fontFamily: 'monospace', color: GREEN }}>
      <PageHeader title={`🛰️ ${name}`} subtitle={head?.branch ?? undefined} />
      <div style={{ marginBottom: 14 }}>
        <Link to="/hq" style={{ color: BLUE, fontSize: 12, textDecoration: 'none' }}>← fleet</Link>
        {head && (
          <>
            {' · '}
            <Link to={`/hq/room/${head.room}`} style={{ color: BLUE, fontSize: 12, textDecoration: 'none' }}>
              {head.room} ↗
            </Link>
          </>
        )}
      </div>

      {err === 404 && <div style={{ ...card, color: AMBER, borderColor: AMBER, textAlign: 'center' }}>no head <code>{name}</code> in the current snapshot</div>}
      {err === 'net' && !head && <div style={{ ...card, color: RED, borderColor: RED, textAlign: 'center' }}>can't reach /api/hq/head</div>}

      {head && m && (
        <>
          {/* status + identity */}
          <div style={{ ...card, marginBottom: 18, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <StatusDot status={head.status} />
              <span style={{ color: m.color, fontSize: 11, textTransform: 'uppercase', letterSpacing: 1 }}>{m.label}</span>
              <span style={{ marginLeft: 'auto', fontSize: 11, color: DIM }}>active {fmtAge(head.last_active_age_s)}</span>
            </div>
            <div style={{ fontSize: 12, color: head.current ? 'rgba(0,255,65,0.85)' : FAINT, fontStyle: head.current ? 'normal' : 'italic' }}>
              {head.current || 'no recent activity'}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
              {head.source === 'bus' && (
                <Pill color={BLUE}>{head.kind === 'windows' ? '⊞ Windows' : 'external'}</Pill>
              )}
              {head.tick != null && <Pill color={DIM}>tick {head.tick}</Pill>}
              {head.branch && <Pill color={BLUE}>⎇ {head.branch}</Pill>}
              {head.git.ahead > 0 && <Pill color={GREEN}>↑{head.git.ahead}</Pill>}
              {head.git.uncommitted > 0 && <Pill color={AMBER}>±{head.git.uncommitted} uncommitted</Pill>}
              {head.source !== 'bus' &&
                (head.rc.paired ? (
                  <a href="https://claude.ai/code" target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
                    <Pill color={BLUE}>🎮 Drive in RC</Pill>
                  </a>
                ) : (
                  <Pill color={FAINT}>RC not paired</Pill>
                ))}
            </div>
            {head.workdir && <div style={{ fontSize: 10, color: FAINT }}>{head.workdir}</div>}
            {head.source === 'bus' && (
              <div style={{ fontSize: 10, color: FAINT }}>
                external head — status via gaia bus heartbeat (no git / fossils)
              </div>
            )}
          </div>

          {/* recent commits */}
          <Section title="Recent commits" count={head.recent_commits.length}>
            {head.recent_commits.length === 0 ? (
              <div style={{ color: DIM, fontSize: 12 }}>none</div>
            ) : (
              <div style={{ ...card, padding: '6px 12px' }}>
                {head.recent_commits.map((cm) => (
                  <div key={cm.sha} style={{ display: 'flex', gap: 8, alignItems: 'baseline', padding: '2px 0', fontSize: 12 }}>
                    <span style={{ color: DIM, fontFamily: 'monospace', flex: '0 0 auto' }}>{cm.sha.slice(0, 7)}</span>
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'rgba(0,255,65,0.85)' }}>{cm.text}</span>
                    <span style={{ color: DIM, fontSize: 10, flex: '0 0 auto' }}>{ago(cm.ts)}</span>
                  </div>
                ))}
              </div>
            )}
          </Section>

          {/* open PRs */}
          {head.open_prs.length > 0 && (
            <Section title="Open PRs" count={head.open_prs.length}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {head.open_prs.map((pr) => (
                  <div key={pr.number} style={{ ...card, display: 'flex', gap: 10, alignItems: 'center' }}>
                    <span style={{ color: DIM, fontSize: 12 }}>#{pr.number}</span>
                    <span style={{ flex: 1, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{pr.title}</span>
                    <Pill color={pr.mergeable ? GREEN : AMBER}>{pr.mergeable ? 'mergeable' : 'conflicts'}</Pill>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* memory scope */}
          <Section title="Memory scope" count={head.memory_scope.length}>
            {head.memory_scope.length === 0 ? (
              <div style={{ color: DIM, fontSize: 12 }}>no scoped memory docs</div>
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {head.memory_scope.map((d) => (
                  <Link key={d.name} to={`/hq/memory/${d.name}`} style={{ textDecoration: 'none' }}>
                    <Pill color={BLUE}>🧠 {d.title}</Pill>
                  </Link>
                ))}
              </div>
            )}
          </Section>

          {/* fossils */}
          <Section title="Fossil archive" count={head.fossils.count}>
            <div style={{ fontSize: 10, color: DIM, marginBottom: 6 }}>
              archived transcripts (metadata only — bodies stay on the host)
            </div>
            {head.fossils.files.length === 0 ? (
              <div style={{ color: DIM, fontSize: 12 }}>no fossils</div>
            ) : (
              <div style={{ ...card, padding: '6px 12px' }}>
                {head.fossils.files.map((f) => (
                  <div key={f.name} style={{ display: 'flex', gap: 8, alignItems: 'baseline', padding: '2px 0', fontSize: 11 }}>
                    <span style={{ color: f.kind === 'subagent' ? DIM : GREEN, flex: '0 0 auto', fontSize: 10 }}>{f.kind === 'subagent' ? '↳ sub' : 'sess'}</span>
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'rgba(0,255,65,0.75)' }}>{f.name}</span>
                    <span style={{ color: DIM, flex: '0 0 auto' }}>{(f.size / 1e6).toFixed(1)}MB</span>
                    <span style={{ color: DIM, fontSize: 10, flex: '0 0 auto' }}>{ago(f.ts)}</span>
                  </div>
                ))}
              </div>
            )}
          </Section>
        </>
      )}
    </div>
  );
}
