import { useEffect, useMemo, useRef, useState } from 'react';
import { C } from './render/tokens';
import { useIsMobile } from '../../hooks/useMediaQuery';
import type { Roadmap, RoadmapNode, RoadmapResponse } from './types';

// Living-roadmap card (ORCHESTRATION.md) — the autopilot cockpit. A minimizable right-edge card
// per project: hierarchical epics→tasks (collapse/expand), agent color-coding (@owner lanes +
// legend), and {milestone} checkpoints each with a "⏵ autopilot to here" control that POSTs an
// intent the orchestration engine consumes. Data = curated checklist ∪ live PR state (done /
// in-progress / planned), refreshed every cycle. Mobile-first: collapsed → edge handle showing
// N/M + the active milestone.

const OPEN_KEY = 'hq.roadmap.open';

// deterministic per-agent colour (stable lane per head)
function agentColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) | 0;
  return `hsl(${Math.abs(h) % 360} 70% 64%)`;
}

function leafStats(n: RoadmapNode): { done: number; total: number } {
  let done = 0, total = 0;
  if (n.checked !== null) { total = 1; done = n.status === 'done' ? 1 : 0; }
  for (const c of n.children) { const s = leafStats(c); done += s.done; total += s.total; }
  return { done, total };
}
function collectOwners(nodes: RoadmapNode[], acc: Set<string>) {
  for (const n of nodes) { if (n.owner) acc.add(n.owner); collectOwners(n.children, acc); }
}

const STATUS_ICON: Record<string, { ch: string; color: string }> = {
  done: { ch: '✓', color: C.green },
  in_progress: { ch: '◐', color: C.amber },
  planned: { ch: '○', color: C.faint },
};

export default function RoadmapCard({ roomId, label }: { roomId: string; label?: string }) {
  const isMobile = useIsMobile();
  // Always start MINIMIZED (just the edge handle) — never auto-take-over the screen. Only an
  // explicit prior expand (localStorage '1') reopens it. Avoids any isMobile init-race trap.
  const [open, setOpen] = useState<boolean>(() => {
    try { return localStorage.getItem(OPEN_KEY) === '1'; } catch { return false; }
  });
  const [rm, setRm] = useState<Roadmap | null>(null);
  const [loaded, setLoaded] = useState(false);   // distinct from rm: a null roadmap is "loaded, empty"
  const [groups, setGroups] = useState<Set<string>>(new Set());
  const [leaves, setLeaves] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoaded(false);
    const load = () => fetch(`/api/hq/room/${encodeURIComponent(roomId)}/roadmap`)
      .then((r) => r.json() as Promise<RoadmapResponse>)
      .then((d) => { if (alive) { setRm(d.roadmap); setLoaded(true); } })
      .catch(() => { if (alive) setLoaded(true); });
    load();
    const id = setInterval(load, 10000);
    return () => { alive = false; clearInterval(id); };
  }, [roomId]);

  // default-open the top-level groups once a roadmap arrives
  useEffect(() => {
    if (rm) setGroups(new Set(rm.nodes.map((_, i) => String(i))));
  }, [rm?.source, roomId]);

  const setOpenPersist = (v: boolean) => { setOpen(v); try { localStorage.setItem(OPEN_KEY, v ? '1' : '0'); } catch { /* */ } };

  // Bulletproof close so the card can NEVER trap (Schyler hit a flaky ✕ on mobile). Three guards:
  // (1) handle pointerup AND click — a slightly-imperfect tap on mobile often never becomes a
  // `click`, but pointerup always fires; (2) stopPropagation so nothing else swallows it; (3) a
  // just-closed timestamp so the iOS "ghost click" can't immediately re-open via the edge handle.
  const justClosedAt = useRef(0);
  const closeCard = (e?: React.SyntheticEvent) => {
    e?.stopPropagation();
    justClosedAt.current = Date.now();
    setOpenPersist(false);
  };
  const openCard = () => {
    if (Date.now() - justClosedAt.current < 400) return;  // swallow a ghost-click reopen
    setOpenPersist(true);
  };

  // Esc always collapses (desktop), on top of the ✕ and tap-outside.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeCard(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  const owners = useMemo(() => { const s = new Set<string>(); if (rm) collectOwners(rm.nodes, s); return [...s].sort(); }, [rm]);
  const progress = rm?.progress ?? { done: 0, total: 0 };
  const pct = progress.total ? Math.round((progress.done / progress.total) * 100) : 0;

  const autopilot = async (milestone: string | null) => {
    setBusy(true);
    try {
      await fetch(`/api/hq/room/${encodeURIComponent(roomId)}/autopilot`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ milestone }),
      });
      setRm((p) => (p ? { ...p, active_milestone: milestone } : p));
    } catch { /* next poll recovers */ } finally { setBusy(false); }
  };

  // ---- collapsed edge handle ----
  if (!open) {
    return (
      <button
        type="button" onClick={openCard} aria-label="open roadmap"
        style={{
          position: 'fixed', right: 0, top: '38%', zIndex: 1500, transform: 'translateY(-50%)',
          background: C.panel, color: C.green, border: `1px solid ${C.line2}`, borderRight: 'none',
          borderRadius: '10px 0 0 10px', padding: '10px 7px', cursor: 'pointer', fontFamily: C.mono,
          writingMode: 'vertical-rl', fontSize: 11, boxShadow: '-6px 0 20px rgba(0,0,0,.4)',
          display: 'flex', alignItems: 'center', gap: 8, touchAction: 'manipulation',
        }}
      >
        <span style={{ transform: 'rotate(180deg)' }}>🗺 roadmap</span>
        {rm && <span style={{ color: C.ink, fontWeight: 700 }}>{progress.done}/{progress.total}</span>}
        {rm?.active_milestone && <span style={{ color: C.amber }}>⏵{rm.active_milestone}</span>}
      </button>
    );
  }

  // ---- expanded panel ----
  return (
    <>
      {/* tap-anywhere-outside to collapse — a reliable escape so the card can never trap.
          z ABOVE the global nav (fixed, z2000): that full-width top bar otherwise overlays the
          panel header and SWALLOWS the ✕ tap on mobile — the actual cause of the flaky close. */}
      <div onPointerUp={closeCard} onClick={closeCard}
        style={{ position: 'fixed', inset: 0, zIndex: 2098, background: 'rgba(0,0,0,.35)', touchAction: 'manipulation' }} />
      <div style={{
        position: 'fixed', right: 0, top: 0, bottom: 0, zIndex: 2099,
        width: isMobile ? 'min(88vw, 360px)' : 360, maxWidth: '100vw', background: C.panel,
        borderLeft: `1px solid ${C.line2}`, boxShadow: '-12px 0 40px rgba(0,0,0,.5)',
        display: 'flex', flexDirection: 'column', fontFamily: C.sans,
      }}>
      <div style={{ padding: '12px 14px 10px', borderBottom: `1px solid ${C.line}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontFamily: C.mono, fontWeight: 700, fontSize: 13, color: C.green }}>🗺 {label || roomId}</span>
          <span style={{ marginLeft: 'auto', fontFamily: C.mono, fontSize: 12, color: C.ink }}>{progress.done}/{progress.total}</span>
          <button type="button" onPointerUp={closeCard} onClick={closeCard} aria-label="close roadmap"
            style={{ background: C.raised, border: `1px solid ${C.line}`, color: C.ink, cursor: 'pointer',
              fontSize: 17, lineHeight: 1, width: 38, height: 38, borderRadius: 8, flex: '0 0 auto',
              touchAction: 'manipulation', position: 'relative', zIndex: 1 }}>✕</button>
        </div>
        <div style={{ height: 5, background: C.raised, borderRadius: 3, marginTop: 8, overflow: 'hidden' }}>
          <div style={{ width: `${pct}%`, height: '100%', background: C.green, boxShadow: `0 0 8px ${C.green}` }} />
        </div>
        {owners.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
            {owners.map((o) => (
              <span key={o} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 10, fontFamily: C.mono, color: C.muted }}>
                <span style={{ width: 8, height: 8, borderRadius: 2, background: agentColor(o) }} />@{o}
              </span>
            ))}
          </div>
        )}
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 10px 24px' }}>
        {!loaded ? (
          <div style={{ color: C.muted, fontSize: 12, textAlign: 'center', marginTop: 20 }}>loading…</div>
        ) : !rm || rm.nodes.length === 0 ? (
          <div style={{ color: C.muted, fontSize: 12.5, textAlign: 'center', marginTop: 24, lineHeight: 1.6, padding: '0 12px' }}>
            No roadmap yet.<br />
            <span style={{ color: C.faint }}>Add a <code style={{ fontFamily: C.mono, color: C.greenDim }}>- [ ]</code> checklist to the project's <code style={{ fontFamily: C.mono, color: C.greenDim }}>ROADMAP.md</code> — it appears here live, with PRs auto-checking items.</span>
          </div>
        ) : (
          rm.nodes.map((n, i) => (
            <NodeRow key={i} node={n} path={String(i)} depth={0}
              groups={groups} setGroups={setGroups} leaves={leaves} setLeaves={setLeaves}
              repo={rm.repo} active={rm.active_milestone ?? null} onAutopilot={autopilot} busy={busy} />
          ))
        )}
        {rm?.source && <div style={{ marginTop: 14, fontSize: 9, color: C.faint, fontFamily: C.mono, textAlign: 'center' }}>{rm.source} · live</div>}
      </div>
      </div>
    </>
  );
}

function NodeRow({ node, path, depth, groups, setGroups, leaves, setLeaves, repo, active, onAutopilot, busy }: {
  node: RoadmapNode; path: string; depth: number;
  groups: Set<string>; setGroups: (s: Set<string>) => void;
  leaves: Set<string>; setLeaves: (s: Set<string>) => void;
  repo: string | null; active: string | null; onAutopilot: (m: string | null) => void; busy: boolean;
}) {
  const isGroup = node.checked === null;
  const isOpen = groups.has(path);
  const toggleGroup = () => { const s = new Set(groups); s.has(path) ? s.delete(path) : s.add(path); setGroups(s); };
  const leafOpen = leaves.has(path);
  const toggleLeaf = () => { const s = new Set(leaves); s.has(path) ? s.delete(path) : s.add(path); setLeaves(s); };
  const stats = isGroup ? leafStats(node) : null;
  const oc = node.owner ? agentColor(node.owner) : null;
  const icon = !isGroup ? (STATUS_ICON[node.status || 'planned'] ?? STATUS_ICON.planned) : null;

  // a pure milestone divider (standalone {milestone:NAME} line — no text, no children)
  if (!node.text && node.milestone && node.children.length === 0) {
    return <MilestoneDivider name={node.milestone} active={active === node.milestone} onAutopilot={onAutopilot} busy={busy} />;
  }

  return (
    <div style={{ marginLeft: depth ? 12 : 0 }}>
      {node.milestone && (
        <MilestoneDivider name={node.milestone} active={active === node.milestone} onAutopilot={onAutopilot} busy={busy} />
      )}
      <div
        onClick={isGroup ? toggleGroup : toggleLeaf}
        style={{ display: 'flex', alignItems: 'baseline', gap: 7, padding: '4px 4px', cursor: 'pointer',
          borderLeft: oc ? `2px solid ${oc}` : '2px solid transparent', paddingLeft: oc ? 7 : 6 }}
      >
        {isGroup
          ? <span style={{ color: C.muted, fontSize: 10, width: 10, flex: '0 0 auto' }}>{isOpen ? '▾' : '▸'}</span>
          : <span style={{ color: icon!.color, fontSize: 12, width: 10, flex: '0 0 auto', textAlign: 'center' }}>{icon!.ch}</span>}
        <span style={{
          flex: 1, fontSize: isGroup ? 12.5 : 12, fontFamily: isGroup ? C.mono : C.sans,
          color: isGroup ? C.ink : (node.status === 'done' ? C.muted : 'rgba(215,247,226,.92)'),
          fontWeight: isGroup ? 700 : 400, textDecoration: node.status === 'done' ? 'line-through' : 'none',
          wordBreak: 'break-word',
        }}>
          {node.text}
          {node.owner && <span style={{ color: oc!, fontFamily: C.mono, fontSize: 10 }}> @{node.owner}</span>}
        </span>
        {node.pr && (
          <a href={repo ? `https://github.com/${repo}/pull/${node.pr.number}` : undefined} target="_blank" rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            style={{ fontFamily: C.mono, fontSize: 10, color: node.pr.state === 'MERGED' ? C.green : C.amber, textDecoration: 'none', flex: '0 0 auto' }}>
            #{node.pr.number}
          </a>
        )}
        {isGroup && stats!.total > 0 && (
          <span style={{ fontFamily: C.mono, fontSize: 10, color: C.faint, flex: '0 0 auto' }}>{stats!.done}/{stats!.total}</span>
        )}
      </div>

      {!isGroup && leafOpen && node.pr && (
        <div style={{ marginLeft: 24, fontSize: 10.5, color: C.muted, fontFamily: C.mono, padding: '2px 0 6px' }}>
          {node.pr.state.toLowerCase()} · {node.pr.title}
        </div>
      )}
      {isGroup && isOpen && node.children.map((c, i) => (
        <NodeRow key={i} node={c} path={`${path}.${i}`} depth={depth + 1}
          groups={groups} setGroups={setGroups} leaves={leaves} setLeaves={setLeaves}
          repo={repo} active={active} onAutopilot={onAutopilot} busy={busy} />
      ))}
    </div>
  );
}

function MilestoneDivider({ name, active, onAutopilot, busy }: { name: string; active: boolean; onAutopilot: (m: string | null) => void; busy: boolean }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '10px 0 6px' }}>
      <span style={{ color: active ? C.amber : C.violet, fontFamily: C.mono, fontSize: 11, fontWeight: 700 }}>◆ {name}</span>
      <div style={{ flex: 1, height: 1, background: active ? 'rgba(255,207,92,.4)' : C.line }} />
      <button type="button" disabled={busy} onClick={() => onAutopilot(active ? null : name)}
        style={{ background: active ? 'rgba(255,207,92,.14)' : C.raised, color: active ? C.amber : C.greenDim,
          border: `1px solid ${active ? C.amber : C.line}`, borderRadius: 6, fontFamily: C.mono, fontSize: 10,
          padding: '3px 8px', cursor: busy ? 'wait' : 'pointer', flex: '0 0 auto' }}>
        {active ? '■ autopilot armed' : '⏵ autopilot to here'}
      </button>
    </div>
  );
}
