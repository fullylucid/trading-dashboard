import { useEffect, useRef, useState } from 'react';
import { DIM, AMBER, card } from './ui';
import { C } from './render/tokens';
import Composer from './Composer';
import RichMarkdown, { CodeBlock, DiffBlock, looksLikeDiff } from './render/RichMarkdown';
import type { ConsoleBlock, ConsoleTurn, TranscriptResponse } from './types';

// HeadConsole — one head's full console: the live-tailed conversation (Slice 1) + the composer
// (Slice 2). Fills its parent (height:100%), so it works both as a standalone page (ConsoleView)
// and as one swipeable screen in the console deck (ConsoleDeck, Slice 3). `active` gates polling
// so only the on-screen console in the deck live-tails.

const POLL_MS = 2000;

type Pending = { id: string; text: string; attachment?: string; status: 'sending' | 'delivered' | 'failed' };

export default function HeadConsole({ name, active = true }: { name: string; active?: boolean }) {
  const [turns, setTurns] = useState<ConsoleTurn[]>([]);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending[]>([]);
  const [headStatus, setHeadStatus] = useState<string | null>(null);
  const cursor = useRef<number>(0);
  const file = useRef<string | null>(null);
  const seen = useRef<Set<string>>(new Set());
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const atBottom = useRef<boolean>(true);

  useEffect(() => {
    if (!active) return; // off-screen deck consoles don't poll
    let alive = true;
    setTurns([]); setUnavailable(null);
    cursor.current = 0; file.current = null; seen.current = new Set();

    const append = (incoming: ConsoleTurn[]) => {
      const fresh = incoming.filter((t) => {
        const key = t.uuid ?? `${t.timestamp}-${t.type}`;
        if (seen.current.has(key)) return false;
        seen.current.add(key);
        return true;
      });
      if (fresh.length) setTurns((prev) => [...prev, ...fresh]);
    };

    const poll = async () => {
      try {
        const q = new URLSearchParams();
        if (file.current) { q.set('after', String(cursor.current)); q.set('file', file.current); }
        const r = await fetch(`/api/hq/head/${encodeURIComponent(name)}/transcript?${q}`);
        if (!r.ok) return;
        const d = (await r.json()) as TranscriptResponse;
        if (!alive) return;
        if (!d.available) { setUnavailable(d.reason || 'no transcript'); return; }
        setUnavailable(null);
        setHeadStatus(d.status ?? null);
        if (d.rotated) { setTurns([]); seen.current = new Set(); }
        file.current = d.file ?? null;
        cursor.current = d.cursor ?? 0;
        append(d.turns ?? []);
      } catch {
        /* keep last view */
      }
    };
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => { alive = false; clearInterval(id); };
  }, [name, active]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && atBottom.current) el.scrollTop = el.scrollHeight;
  }, [turns, pending]);

  // reconcile: drop an optimistic message once its real transcript user-turn lands
  useEffect(() => {
    if (!pending.length) return;
    const userTexts = new Set(
      turns.filter((t) => t.type === 'user')
        .map((t) => t.blocks.filter((b) => b.kind === 'text').map((b) => (b as { text: string }).text).join('\n').trim())
        .filter(Boolean),
    );
    setPending((prev) => prev.filter((p) => !userTexts.has(p.text.trim())));
  }, [turns]);

  // poll delivery status of in-flight messages (the relay writes the per-job result)
  useEffect(() => {
    const inflight = pending.filter((p) => p.status === 'sending');
    if (!inflight.length) return;
    let alive = true;
    const tick = () => inflight.forEach((p) => {
      fetch(`/api/hq/input/${encodeURIComponent(p.id)}/status`)
        .then((r) => r.json())
        .then((d) => {
          if (alive && (d.status === 'delivered' || d.status === 'failed')) {
            setPending((prev) => prev.map((x) => (x.id === p.id ? { ...x, status: d.status } : x)));
          }
        })
        .catch(() => {});
    });
    const id = setInterval(tick, 1500);
    tick();
    return () => { alive = false; clearInterval(id); };
  }, [pending]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  };

  if (unavailable) {
    return <div style={{ ...card, color: AMBER, borderColor: AMBER, textAlign: 'center', margin: 4 }}>{unavailable}</div>;
  }

  // a delivered message that the agent hasn't picked up yet (busy) is QUEUED in Claude Code's
  // input — render it distinctly until its real transcript turn lands.
  const busy = headStatus === 'working' || headStatus === 'waiting-input';
  const queuedCount = busy ? pending.filter((p) => p.status === 'delivered').length : 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div
        ref={scrollRef}
        onScroll={onScroll}
        style={{ flex: 1, minHeight: 0, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 10, padding: '4px 2px' }}
      >
        {turns.length === 0 && pending.length === 0 && <div style={{ color: DIM, fontSize: 12, textAlign: 'center', marginTop: 20 }}>loading conversation…</div>}
        {turns.map((t, i) => <Turn key={t.uuid ?? i} turn={t} />)}
        {pending.map((p) => <PendingBubble key={p.id} msg={p} busy={busy} queuedCount={queuedCount} />)}
      </div>

      <div style={{ marginTop: 10, flex: '0 0 auto' }}>
        <Composer name={name} onSent={(m) => { setPending((p) => [...p, { ...m, status: 'sending' }]); atBottom.current = true; }} />
      </div>
    </div>
  );
}

function PendingBubble({ msg, busy, queuedCount }: { msg: Pending; busy: boolean; queuedCount: number }) {
  const caption = msg.text.replace(/\n?\[(image|file) attached\][^\n]*$/i, '').trim();
  // delivered + agent busy = QUEUED in Claude Code's input (runs when the agent finishes)
  const queued = msg.status === 'delivered' && busy;
  const view = msg.status === 'failed' ? 'failed' : queued ? 'queued' : msg.status; // sending | delivered | queued | failed
  const badge = {
    failed: { ch: '✗ failed', color: C.red },
    queued: { ch: queuedCount > 1 ? `⧖ queued · ${queuedCount} waiting` : '⧖ queued', color: C.violet },
    delivered: { ch: '✓ delivered', color: C.green },
    sending: { ch: '● sending', color: C.amber },
  }[view] ?? { ch: '● sending', color: C.amber };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
      <div style={{
        maxWidth: '88%', minWidth: 0, position: 'relative',
        border: `1px solid ${view === 'failed' ? C.red : view === 'queued' ? 'rgba(183,155,255,.4)' : C.userLine}`,
        borderRadius: 14, borderBottomRightRadius: 5, padding: '11px 13px',
        background: view === 'queued' ? 'rgba(183,155,255,.06)' : C.userBg,
        opacity: view === 'sending' ? 0.72 : view === 'queued' ? 0.92 : 1,
      }}>
        {msg.attachment && <div style={{ fontFamily: C.mono, fontSize: 11.5, color: C.blue, marginBottom: caption ? 5 : 0 }}>📎 {msg.attachment}</div>}
        {caption && <div style={{ fontFamily: C.mono, fontSize: 13.5, lineHeight: 1.5, color: view === 'queued' ? 'rgba(215,247,226,.78)' : C.userInk, whiteSpace: 'pre-wrap', fontStyle: view === 'queued' ? 'italic' : 'normal' }}>{caption}</div>}
        <span title={view} style={{ position: 'absolute', right: 8, bottom: -7, fontSize: 9, fontFamily: C.mono, color: badge.color, background: C.bg, padding: '0 4px', borderRadius: 4 }}>{badge.ch}</span>
      </div>
      {queued && <span style={{ fontSize: 9, color: C.faint, fontFamily: C.mono, paddingRight: 4 }}>will run when the agent finishes its turn</span>}
    </div>
  );
}

function Turn({ turn }: { turn: ConsoleTurn }) {
  const isUser = turn.type === 'user' && turn.blocks.some((b) => b.kind === 'text');
  return (
    <div style={{ display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start' }}>
      <div style={{ maxWidth: '88%', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
        {turn.blocks.map((b, i) => <Block key={i} block={b} isUser={isUser} />)}
      </div>
    </div>
  );
}

const detailsCard: React.CSSProperties = {
  border: `1px solid ${C.line}`, borderRadius: 9, background: 'rgba(0,0,0,.25)', fontFamily: C.mono, fontSize: 12,
};
const summaryStyle: React.CSSProperties = { cursor: 'pointer', listStyle: 'none', padding: '7px 11px', display: 'flex', alignItems: 'center', gap: 8 };

function Block({ block, isUser }: { block: ConsoleBlock; isUser: boolean }) {
  if (block.kind === 'text') {
    return (
      <div style={{
        border: `1px solid ${isUser ? C.userLine : C.line}`, borderRadius: 14,
        borderBottomRightRadius: isUser ? 5 : 14, borderBottomLeftRadius: isUser ? 14 : 5,
        padding: '11px 13px', background: isUser ? C.userBg : C.panel2, wordBreak: 'break-word',
      }}>
        {isUser
          ? <div style={{ fontFamily: C.mono, fontSize: 13.5, lineHeight: 1.5, color: C.userInk, whiteSpace: 'pre-wrap' }}>{block.text}</div>
          : <RichMarkdown source={block.text} />}
      </div>
    );
  }
  if (block.kind === 'thinking') {
    return (
      <details style={{ ...detailsCard, borderColor: 'rgba(183,155,255,.26)', background: 'rgba(183,155,255,.05)' }}>
        <summary style={{ ...summaryStyle, color: C.violet }}>🧠 thinking</summary>
        <div style={{ padding: '0 11px 9px' }}><RichMarkdown source={block.text} dim /></div>
      </details>
    );
  }
  if (block.kind === 'tool_use') {
    return (
      <details style={{ ...detailsCard, background: 'rgba(0,255,65,.03)' }}>
        <summary style={{ ...summaryStyle, color: C.muted }}>
          🔧 <b style={{ color: C.greenDim }}>{block.name}</b>
        </summary>
        <div style={{ padding: '0 10px 8px' }}><CodeBlock code={block.input} lang="json" /></div>
      </details>
    );
  }
  // tool_result
  const diff = looksLikeDiff(block.text);
  return (
    <details style={{ ...detailsCard, borderColor: block.is_error ? C.red : C.line }}>
      <summary style={{ ...summaryStyle, color: block.is_error ? C.red : C.muted }}>
        {block.is_error ? '⚠ tool error' : '↳ tool result'}
      </summary>
      <div style={{ padding: diff ? '0 10px 8px' : '0 11px 9px' }}>
        {diff
          ? <DiffBlock source={block.text} />
          : <pre style={{ margin: 0, fontFamily: C.mono, fontSize: 11, color: block.is_error ? '#ffadad' : C.greenDim, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{block.text}</pre>}
      </div>
    </details>
  );
}
