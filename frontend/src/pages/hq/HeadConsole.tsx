import { useEffect, useRef, useState } from 'react';
import { DIM, AMBER, card } from './ui';
import { C } from './render/tokens';
import Composer from './Composer';
import RichMarkdown, { CodeBlock, DiffBlock, looksLikeDiff } from './render/RichMarkdown';
import type { ConsoleBlock, ConsoleTurn, MenuPrompt, TranscriptResponse } from './types';

// HeadConsole — one head's full console: the live-tailed conversation (Slice 1) + the composer
// (Slice 2). Fills its parent (height:100%), so it works both as a standalone page (ConsoleView)
// and as one swipeable screen in the console deck (ConsoleDeck, Slice 3). `active` gates polling
// so only the on-screen console in the deck live-tails.

const POLL_MS = 2000;
// queued is only valid WHILE the head is busy; once it goes idle and stays idle this long, any
// still-'delivered' message is resolved (it's been consumed/run) so ⧖ queued can never hang.
const IDLE_GRACE_MS = 4000;

type Pending = { id: string; text: string; status: 'sending' | 'delivered' | 'failed' };

export default function HeadConsole({ name, active = true }: { name: string; active?: boolean }) {
  const [turns, setTurns] = useState<ConsoleTurn[]>([]);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending[]>([]);
  const [headStatus, setHeadStatus] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<MenuPrompt | null>(null);
  const [lightbox, setLightbox] = useState<string | null>(null);
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
        setPrompt(d.prompt ?? null);
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

  // backstop so ⧖ queued can NEVER hang: if the head is idle (not working/waiting) and stays
  // idle through a short grace, resolve any still-'delivered' message. The text-reconcile above
  // clears a message when its transcript user-turn lands — but a menu answer is consumed by the
  // menu and never becomes a turn, so without this it would sit purple-queued forever.
  useEffect(() => {
    const idle = headStatus !== 'working' && headStatus !== 'waiting-input';
    if (!idle || !pending.some((p) => p.status === 'delivered')) return;
    const t = setTimeout(
      () => setPending((prev) => prev.filter((p) => p.status !== 'delivered')),
      IDLE_GRACE_MS,
    );
    return () => clearTimeout(t);
  }, [headStatus, pending]);

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
        {turns.map((t, i) => <Turn key={t.uuid ?? i} turn={t} onImage={setLightbox} />)}
        {pending.map((p) => <PendingBubble key={p.id} msg={p} busy={busy} queuedCount={queuedCount} onImage={setLightbox} />)}
      </div>

      {prompt && (
        <MenuCard
          key={`${prompt.kind}:${prompt.question}:${prompt.options.map((o) => o.index).join(',')}`}
          name={name}
          prompt={prompt}
        />
      )}

      <div style={{ marginTop: 10, flex: '0 0 auto' }}>
        <Composer name={name} onSent={(m) => { setPending((p) => [...p, { ...m, status: 'sending' }]); atBottom.current = true; }} />
      </div>

      {lightbox && (
        <div onClick={() => setLightbox(null)} role="dialog" aria-label="image preview"
          style={{ position: 'fixed', inset: 0, zIndex: 3000, background: 'rgba(0,0,0,.88)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16, cursor: 'zoom-out' }}>
          <img src={lightbox} alt="" style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain', borderRadius: 8, boxShadow: '0 8px 40px rgba(0,0,0,.6)' }} />
        </div>
      )}
    </div>
  );
}

// caption + [image/file attached] path lines parsed out of a user message -> thumbnails + chips.
function parseAttach(text: string): { caption: string; atts: { image: boolean; name: string }[] } {
  const re = /\[(image|file) attached\]\s+(\S+)/g;
  const atts: { image: boolean; name: string }[] = [];
  let first = text.length, m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    atts.push({ image: m[1] === 'image', name: (m[2].split('/').pop() || m[2]) });
    first = Math.min(first, m.index);
  }
  const caption = atts.length ? text.slice(0, first).replace(/\n+$/, '').trim() : text;
  return { caption, atts };
}

function UserContent({ text, onImage, dim }: { text: string; onImage: (src: string) => void; dim?: boolean }) {
  const { caption, atts } = parseAttach(text);
  return (
    <>
      {caption && <div style={{ fontFamily: C.userFont, fontSize: 15, lineHeight: 1.45, color: C.cerulean, whiteSpace: 'pre-wrap', fontStyle: dim ? 'italic' : 'normal', opacity: dim ? 0.8 : 1 }}>{caption}</div>}
      {atts.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: caption ? 6 : 0 }}>
          {atts.map((a, i) => {
            const url = `/api/hq/uploads/${encodeURIComponent(a.name)}`;
            const label = a.name.replace(/^[0-9a-f]{8}-/, '');
            return a.image
              ? <img key={i} src={url} alt={label} title={label} onClick={() => onImage(url)}
                  style={{ width: 96, height: 96, objectFit: 'cover', borderRadius: 8, border: `1px solid ${C.userLine}`, cursor: 'zoom-in', display: 'block' }} />
              : <a key={i} href={url} target="_blank" rel="noreferrer"
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: C.raised, border: `1px solid ${C.line2}`, borderRadius: 8, padding: '6px 9px', textDecoration: 'none', color: C.ink, fontFamily: C.mono, fontSize: 11 }}>📄 {label}</a>;
          })}
        </div>
      )}
    </>
  );
}

function PendingBubble({ msg, busy, queuedCount, onImage }: { msg: Pending; busy: boolean; queuedCount: number; onImage: (src: string) => void }) {
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
        <UserContent text={msg.text} onImage={onImage} dim={queued} />
        <span title={view} style={{ position: 'absolute', right: 8, bottom: -7, fontSize: 9, fontFamily: C.mono, color: badge.color, background: C.bg, padding: '0 4px', borderRadius: 4 }}>{badge.ch}</span>
      </div>
      {queued && <span style={{ fontSize: 9, color: C.faint, fontFamily: C.mono, paddingRight: 4 }}>will run when the agent finishes its turn</span>}
    </div>
  );
}

// F6 — the head is blocked on a menu (a permission prompt or an AskUserQuestion). Render its
// question + options as tappable buttons; a tap send-keys the answer to the head's pane. The
// card auto-dismisses on the next poll once the head leaves waiting-input (prompt -> null).
function MenuCard({ name, prompt }: { name: string; prompt: MenuPrompt }) {
  const [chosen, setChosen] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const permission = prompt.kind === 'permission';
  const accent = permission ? C.amber : C.blue;

  const answer = async (index: number) => {
    if (chosen !== null) return; // one answer per menu; buttons lock after the first tap
    setChosen(index); setErr(null);
    try {
      const r = await fetch(`/api/hq/head/${encodeURIComponent(name)}/answer`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setErr((d as { detail?: string }).detail || `error ${r.status}`); setChosen(null);
      }
    } catch {
      setErr('network error'); setChosen(null);
    }
  };

  return (
    <div style={{
      marginTop: 10, flex: '0 0 auto', border: `1px solid ${accent}`, borderLeftWidth: 3,
      borderRadius: 12, background: C.panel, padding: '10px 12px',
      boxShadow: `0 0 0 1px ${C.bg}, 0 4px 18px rgba(0,0,0,.35)`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ fontFamily: C.mono, fontSize: 9, letterSpacing: '.12em', textTransform: 'uppercase', color: accent, border: `1px solid ${accent}`, borderRadius: 4, padding: '1px 5px' }}>
          {permission ? '⚠ permission' : '❔ choose'}
        </span>
        <span style={{ fontFamily: C.sans, fontSize: 13, fontWeight: 600, color: C.ink, lineHeight: 1.35 }}>{prompt.question}</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {prompt.options.map((o) => {
          const low = o.label.toLowerCase();
          const tint = permission ? (low.startsWith('yes') ? C.green : low.startsWith('no') ? C.red : C.greenDim) : C.greenDim;
          const picked = chosen === o.index;
          const dim = chosen !== null && !picked;
          return (
            <button key={o.index} onClick={() => answer(o.index)} disabled={chosen !== null} title={o.label}
              style={{
                display: 'flex', alignItems: 'baseline', gap: 9, width: '100%', textAlign: 'left',
                fontFamily: C.mono, fontSize: 12.5, textTransform: 'none', letterSpacing: 0,
                background: picked ? 'rgba(34,255,106,.10)' : C.raised,
                border: `1px solid ${picked ? C.green : tint}`, borderRadius: 9, padding: '9px 11px',
                color: dim ? C.faint : C.ink, opacity: dim ? 0.5 : 1,
                cursor: chosen !== null ? 'default' : 'pointer',
              }}>
              <span style={{ color: accent, fontWeight: 700, flex: '0 0 auto' }}>{o.index}</span>
              <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{o.label}</span>
              {picked && <span style={{ marginLeft: 'auto', color: C.green, flex: '0 0 auto' }}>● sending</span>}
            </button>
          );
        })}
      </div>
      {err && <div style={{ marginTop: 7, fontFamily: C.mono, fontSize: 10, color: C.red }}>✗ {err}</div>}
    </div>
  );
}

function Turn({ turn, onImage }: { turn: ConsoleTurn; onImage: (src: string) => void }) {
  const isUser = turn.type === 'user' && turn.blocks.some((b) => b.kind === 'text');
  if (isUser) {
    // a user message: render its text via UserContent so [image/file attached] -> thumbnails
    const text = turn.blocks.filter((b) => b.kind === 'text').map((b) => (b as { text: string }).text).join('\n');
    return (
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <div style={{ maxWidth: '88%', minWidth: 0, border: `1px solid ${C.userLine}`, borderRadius: 14, borderBottomRightRadius: 5, padding: '11px 13px', background: C.userBg, wordBreak: 'break-word' }}>
          <UserContent text={text} onImage={onImage} />
        </div>
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
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
