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

export default function HeadConsole({ name, active = true }: { name: string; active?: boolean }) {
  const [turns, setTurns] = useState<ConsoleTurn[]>([]);
  const [unavailable, setUnavailable] = useState<string | null>(null);
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
  }, [turns]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  };

  if (unavailable) {
    return <div style={{ ...card, color: AMBER, borderColor: AMBER, textAlign: 'center', margin: 4 }}>{unavailable}</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div
        ref={scrollRef}
        onScroll={onScroll}
        style={{ flex: 1, minHeight: 0, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 10, padding: '4px 2px' }}
      >
        {turns.length === 0 && <div style={{ color: DIM, fontSize: 12, textAlign: 'center', marginTop: 20 }}>loading conversation…</div>}
        {turns.map((t, i) => <Turn key={t.uuid ?? i} turn={t} />)}
      </div>

      <div style={{ marginTop: 10, flex: '0 0 auto' }}>
        <Composer name={name} onSent={() => { atBottom.current = true; }} />
      </div>
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
