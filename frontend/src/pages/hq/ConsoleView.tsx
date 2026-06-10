import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import PageHeader from '../../components/PageHeader';
import { GREEN, DIM, FAINT, AMBER, RED, BLUE, card } from './ui';
import type { ConsoleBlock, ConsoleTurn, TranscriptResponse } from './types';

// HQ Console — a head's live conversation, rendered as a Claude-app-style chat (CONSOLE.md
// Slice 1, read-only). Live-tails the head's transcript .jsonl via /api/hq/head/{name}/transcript:
// a cold load fetches the last N turns, then it polls incrementally (after=cursor & file) and
// appends only new turns. Slice 2 adds the composer; Slice 3 wraps this in project/swipe nav.

const POLL_MS = 2000;

export default function ConsoleView() {
  const { name = '' } = useParams();
  const [turns, setTurns] = useState<ConsoleTurn[]>([]);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [sendErr, setSendErr] = useState<string | null>(null);
  const cursor = useRef<number>(0);
  const file = useRef<string | null>(null);
  const seen = useRef<Set<string>>(new Set());
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const atBottom = useRef<boolean>(true);

  useEffect(() => {
    let active = true;
    // reset when switching heads
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
        if (!active) return;
        if (!d.available) { setUnavailable(d.reason || 'no transcript'); return; }
        setUnavailable(null);
        if (d.rotated) { setTurns([]); seen.current = new Set(); } // new session file
        file.current = d.file ?? null;
        cursor.current = d.cursor ?? 0;
        append(d.turns ?? []);
      } catch {
        /* keep last view */
      }
    };
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => { active = false; clearInterval(id); };
  }, [name]);

  // auto-scroll to newest unless the operator has scrolled up
  useEffect(() => {
    const el = scrollRef.current;
    if (el && atBottom.current) el.scrollTop = el.scrollHeight;
  }, [turns]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  };

  const send = async () => {
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    setSendErr(null);
    try {
      const r = await fetch(`/api/hq/head/${encodeURIComponent(name)}/input`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      if (r.ok) {
        setDraft('');
        atBottom.current = true; // jump to see the response land
      } else {
        const d = await r.json().catch(() => ({}));
        setSendErr(d.detail || `send failed (${r.status})`);
      }
    } catch {
      setSendErr("can't reach the console backend");
    } finally {
      setSending(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: '0 12px 24px', fontFamily: 'monospace', color: GREEN }}>
      <PageHeader title={`🛰️ ${name}`} subtitle="console — conversation (read-only)" />
      <div style={{ marginBottom: 10, display: 'flex', gap: 12 }}>
        <Link to="/hq" style={{ color: BLUE, fontSize: 12, textDecoration: 'none' }}>← fleet</Link>
        <Link to={`/hq/head/${name}`} style={{ color: BLUE, fontSize: 12, textDecoration: 'none' }}>head detail ↗</Link>
      </div>

      {unavailable ? (
        <div style={{ ...card, color: AMBER, borderColor: AMBER, textAlign: 'center' }}>{unavailable}</div>
      ) : (
        <>
          <div
            ref={scrollRef}
            onScroll={onScroll}
            style={{ height: 'calc(100vh - 320px)', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 10, padding: '4px 2px' }}
          >
            {turns.length === 0 && <div style={{ color: DIM, fontSize: 12, textAlign: 'center', marginTop: 20 }}>loading conversation…</div>}
            {turns.map((t, i) => <Turn key={t.uuid ?? i} turn={t} />)}
          </div>

          {/* composer — sends to the head's tmux pane (Slice 2) */}
          <div style={{ marginTop: 10 }}>
            {sendErr && <div style={{ color: RED, fontSize: 11, marginBottom: 6 }}>{sendErr}</div>}
            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder={`message ${name}…  (Enter to send · Shift+Enter for newline)`}
                rows={2}
                style={{
                  flex: 1, resize: 'vertical', background: '#000', color: GREEN, border: `1px solid ${FAINT}`,
                  borderRadius: 6, padding: '8px 10px', fontFamily: 'monospace', fontSize: 13, lineHeight: 1.4,
                  outline: 'none', minHeight: 40,
                }}
              />
              <button
                type="button"
                onClick={send}
                disabled={sending || !draft.trim()}
                style={{
                  background: '#000', color: draft.trim() ? GREEN : FAINT,
                  border: `1px solid ${draft.trim() ? GREEN : FAINT}`, borderRadius: 6,
                  fontFamily: 'monospace', fontSize: 13, padding: '8px 16px',
                  cursor: sending || !draft.trim() ? 'not-allowed' : 'pointer', opacity: sending ? 0.6 : 1,
                }}
              >
                {sending ? '…' : 'Send'}
              </button>
            </div>
            <div style={{ fontSize: 9, color: FAINT, marginTop: 4 }}>
              ⚠ drives {name}'s live session — sends to its tmux pane
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Turn({ turn }: { turn: ConsoleTurn }) {
  const isUser = turn.type === 'user' && turn.blocks.some((b) => b.kind === 'text');
  // a user turn that's only tool_results reads as the assistant's tool output, not a user message
  const align = isUser ? 'flex-end' : 'flex-start';
  return (
    <div style={{ display: 'flex', justifyContent: align }}>
      <div style={{ maxWidth: '88%', display: 'flex', flexDirection: 'column', gap: 6 }}>
        {turn.blocks.map((b, i) => <Block key={i} block={b} isUser={isUser} />)}
      </div>
    </div>
  );
}

function Block({ block, isUser }: { block: ConsoleBlock; isUser: boolean }) {
  if (block.kind === 'text') {
    return (
      <div
        style={{
          ...card,
          background: isUser ? 'rgba(77,184,255,0.08)' : 'rgba(0,255,65,0.04)',
          borderColor: isUser ? 'rgba(77,184,255,0.4)' : FAINT,
          color: isUser ? '#cfe8ff' : 'rgba(0,255,65,0.9)',
          fontSize: 13, lineHeight: 1.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        }}
      >
        {block.text}
      </div>
    );
  }
  if (block.kind === 'thinking') {
    return (
      <details style={{ ...card, borderColor: 'rgba(176,124,255,0.35)', background: 'rgba(176,124,255,0.05)' }}>
        <summary style={{ cursor: 'pointer', fontSize: 11, color: '#b07cff' }}>🧠 thinking</summary>
        <div style={{ fontSize: 12, color: 'rgba(176,124,255,0.8)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginTop: 6, fontStyle: 'italic' }}>
          {block.text}
        </div>
      </details>
    );
  }
  if (block.kind === 'tool_use') {
    return (
      <details style={{ ...card, borderColor: FAINT, background: 'rgba(0,255,65,0.03)' }}>
        <summary style={{ cursor: 'pointer', fontSize: 11, color: DIM }}>🔧 {block.name}</summary>
        <pre style={{ fontSize: 11, color: 'rgba(0,255,65,0.75)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '6px 0 0' }}>
          {block.input}
        </pre>
      </details>
    );
  }
  // tool_result
  return (
    <details style={{ ...card, borderColor: block.is_error ? RED : FAINT, background: 'rgba(0,0,0,0.25)' }}>
      <summary style={{ cursor: 'pointer', fontSize: 11, color: block.is_error ? RED : DIM }}>
        {block.is_error ? '⚠ tool error' : '↳ tool result'}
      </summary>
      <pre style={{ fontSize: 11, color: block.is_error ? '#ffb3b3' : 'rgba(0,255,65,0.6)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '6px 0 0' }}>
        {block.text}
      </pre>
    </details>
  );
}
