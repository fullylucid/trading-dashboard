import { useEffect, useMemo, useRef, useState } from 'react';
import { C } from './render/tokens';
import type { CommandsResponse, SlashCommand } from './types';

// Console composer with full slash-command discovery (Schyler's ask). Two affordances:
//  • an autocomplete popup that appears the instant you type '/' at the start — fuzzy-filtered,
//    arrow/tap to pick, Enter/Tab inserts the /command so you can add args before sending;
//  • a '/' button that opens a browsable, searchable list of EVERY command (built-in / skill /
//    custom), grouped by source.
// The catalog is the collector-published hq:commands (164: 15 built-ins + 149 skills + custom).
// Mechanism is unchanged — slash commands already run via send-keys; this is the discovery layer.

let CACHE: SlashCommand[] | null = null;

const SRC: Record<string, { label: string; color: string }> = {
  builtin: { label: 'built-in', color: C.green },
  skill: { label: 'skill', color: C.blue },
  custom: { label: 'custom', color: C.violet },
};

function score(cmd: SlashCommand, q: string): number {
  if (!q) return 1;
  const n = cmd.name.toLowerCase();
  if (n === q) return 1000;
  if (n.startsWith(q)) return 600 - n.length;
  const idx = n.indexOf(q);
  if (idx >= 0) return 300 - idx;
  let i = 0;
  for (const ch of n) { if (ch === q[i]) i++; if (i === q.length) break; }
  if (i === q.length) return 80 - n.length * 0.1;
  if (cmd.desc.toLowerCase().includes(q)) return 15;
  return -1;
}
function filterCmds(cmds: SlashCommand[], q: string): SlashCommand[] {
  return cmds.map((c) => ({ c, s: score(c, q) })).filter((x) => x.s > 0).sort((a, b) => b.s - a.s).map((x) => x.c);
}

type SentMsg = { id: string; text: string; attachment?: string };

export default function Composer({ name, onSent }: { name: string; onSent?: (msg: SentMsg) => void }) {
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [sendErr, setSendErr] = useState<string | null>(null);
  const [commands, setCommands] = useState<SlashCommand[]>(CACHE ?? []);
  const [hi, setHi] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const [browse, setBrowse] = useState(false);
  const [browseQ, setBrowseQ] = useState('');
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (CACHE) return;
    let alive = true;
    fetch('/api/hq/commands')
      .then((r) => r.json() as Promise<CommandsResponse>)
      .then((d) => { if (alive && d.commands?.length) { CACHE = d.commands; setCommands(d.commands); } })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  // auto-grow to fit the message (up to ~8 lines, then internal scroll)
  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 184)}px`;
  }, [draft]);

  const slashM = /^\/(\S*)$/.exec(draft);
  const query = slashM ? slashM[1] : null;
  const acOpen = query !== null && !dismissed && commands.length > 0;
  const matches = useMemo(() => (acOpen ? filterCmds(commands, (query as string).toLowerCase()).slice(0, 8) : []), [acOpen, query, commands]);
  useEffect(() => { setHi(0); }, [query]);

  const insert = (cmd: SlashCommand) => {
    setDraft('/' + cmd.name + ' ');
    setDismissed(true);
    setBrowse(false);
    requestAnimationFrame(() => { const t = taRef.current; if (t) { t.focus(); const e = t.value.length; t.setSelectionRange(e, e); } });
  };

  const send = async () => {
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true); setSendErr(null);
    try {
      const r = await fetch(`/api/hq/head/${encodeURIComponent(name)}/input`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }),
      });
      if (r.ok) { const d = await r.json().catch(() => ({})); setDraft(''); setDismissed(false); onSent?.({ id: d.id, text }); }
      else { const d = await r.json().catch(() => ({})); setSendErr(d.detail || `send failed (${r.status})`); }
    } catch { setSendErr("can't reach the console backend"); } finally { setSending(false); }
  };

  const attach = async (files: FileList | null) => {
    const file = files?.[0];
    if (!file || uploading) return;
    setUploading(true); setSendErr(null);
    const caption = draft.trim();
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('caption', caption);
      const r = await fetch(`/api/hq/head/${encodeURIComponent(name)}/upload`, { method: 'POST', body: fd });
      if (r.ok) { const d = await r.json(); setDraft(''); onSent?.({ id: d.id, text: d.text, attachment: d.filename }); }
      else { const d = await r.json().catch(() => ({})); setSendErr(d.detail || `upload failed (${r.status})`); }
    } catch { setSendErr("upload failed — can't reach the backend"); }
    finally { setUploading(false); if (fileRef.current) fileRef.current.value = ''; }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (acOpen && matches.length) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setHi((h) => (h + 1) % matches.length); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); setHi((h) => (h - 1 + matches.length) % matches.length); return; }
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) { e.preventDefault(); insert(matches[hi]); return; }
      if (e.key === 'Escape') { e.preventDefault(); setDismissed(true); return; }
    }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  };

  const browseList = useMemo(() => {
    const q = browseQ.trim().toLowerCase();
    const list = q ? filterCmds(commands, q) : [...commands];
    const groups: Record<string, SlashCommand[]> = {};
    for (const c of list) (groups[c.source] ||= []).push(c);
    return groups;
  }, [browse, browseQ, commands]);

  return (
    <div style={{ position: 'relative', flex: '0 0 auto' }}>
      {sendErr && <div style={{ color: C.red, fontSize: 11, marginBottom: 6, fontFamily: C.mono }}>{sendErr}</div>}

      {/* autocomplete popup (opens upward, thumb-reachable) */}
      {acOpen && matches.length > 0 && (
        <Popup>
          {matches.map((c, i) => <Row key={c.source + c.name} cmd={c} active={i === hi} onPick={() => insert(c)} onHover={() => setHi(i)} />)}
        </Popup>
      )}

      {/* full browse dropdown */}
      {browse && (
        <Popup tall>
          <div style={{ position: 'sticky', top: 0, background: C.panel, padding: '8px 8px 6px', borderBottom: `1px solid ${C.line}` }}>
            <input
              autoFocus value={browseQ} onChange={(e) => setBrowseQ(e.target.value)}
              placeholder={`search ${commands.length} commands…`}
              style={{ width: '100%', background: '#060a06', color: C.ink, border: `1px solid ${C.line2}`, borderRadius: 8, padding: '7px 9px', fontFamily: C.mono, fontSize: 12.5, outline: 'none' }}
            />
          </div>
          {(['builtin', 'skill', 'custom'] as const).map((src) => (browseList[src]?.length ? (
            <div key={src}>
              <div style={{ fontFamily: C.mono, fontSize: 10, color: SRC[src].color, textTransform: 'uppercase', letterSpacing: 1, padding: '8px 11px 3px' }}>
                {SRC[src].label} <span style={{ color: C.faint }}>· {browseList[src].length}</span>
              </div>
              {browseList[src].map((c) => <Row key={src + c.name} cmd={c} onPick={() => insert(c)} />)}
            </div>
          ) : null))}
        </Popup>
      )}

      <input ref={fileRef} type="file" accept="image/*,.pdf,.txt,.md,.csv,.json,.log,.py,.ts,.tsx,.js" style={{ display: 'none' }} onChange={(e) => attach(e.target.files)} />
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, background: '#060a06', border: `1px solid ${C.line2}`, borderRadius: 14, padding: '8px 10px' }}>
        <button type="button" title="attach photo or document" onClick={() => fileRef.current?.click()} disabled={uploading}
          style={{ width: 34, height: 34, borderRadius: 9, border: `1px solid ${C.line}`, background: C.raised, color: uploading ? C.green : C.greenDim, cursor: uploading ? 'wait' : 'pointer', fontSize: 15, flex: '0 0 auto' }}>{uploading ? '…' : '📎'}</button>
        <button type="button" title="browse slash commands" onClick={() => { setBrowse((v) => !v); setBrowseQ(''); }}
          style={{ width: 34, height: 34, borderRadius: 9, border: `1px solid ${browse ? C.green : C.line}`, background: C.raised, color: browse ? C.green : C.greenDim, cursor: 'pointer', fontFamily: C.mono, fontSize: 16, flex: '0 0 auto' }}>/</button>
        <textarea
          ref={taRef} value={draft}
          onChange={(e) => { setDraft(e.target.value); setDismissed(false); }}
          onKeyDown={onKeyDown}
          placeholder={`message ${name}…  ( / for commands )`}
          rows={1}
          style={{ flex: 1, resize: 'none', background: 'transparent', color: C.ink, border: 'none', outline: 'none', fontFamily: C.sans, fontSize: 14, lineHeight: 1.5, maxHeight: 184, minHeight: 24, overflowY: 'auto', paddingTop: 4 }}
        />
        <button type="button" onClick={send} disabled={sending || !draft.trim()}
          style={{ width: 38, height: 34, borderRadius: 9, border: `1px solid ${draft.trim() ? C.green : C.line}`, background: draft.trim() ? 'rgba(34,255,106,.14)' : C.raised, color: draft.trim() ? C.green : C.faint, cursor: sending || !draft.trim() ? 'not-allowed' : 'pointer', flex: '0 0 auto', opacity: sending ? 0.6 : 1, fontSize: 14 }}>➤</button>
      </div>
      <div style={{ fontSize: 9, color: C.faint, marginTop: 4, fontFamily: C.mono, display: 'flex', justifyContent: 'space-between' }}>
        <span>Enter to send · Shift+Enter newline · / for commands</span>
        <span>⚠ drives {name}'s live session</span>
      </div>
    </div>
  );
}

function Popup({ children, tall }: { children: React.ReactNode; tall?: boolean }) {
  return (
    <div style={{
      position: 'absolute', bottom: 'calc(100% + 8px)', left: 0, right: 0, zIndex: 50,
      background: C.panel, border: `1px solid ${C.line2}`, borderRadius: 12, overflow: 'hidden',
      maxHeight: tall ? 360 : 300, overflowY: 'auto', boxShadow: '0 12px 40px rgba(0,0,0,.6)',
    }}>
      {children}
    </div>
  );
}

function Row({ cmd, active, onPick, onHover }: { cmd: SlashCommand; active?: boolean; onPick: () => void; onHover?: () => void }) {
  return (
    <div
      onMouseDown={(e) => { e.preventDefault(); onPick(); }}
      onMouseEnter={onHover}
      style={{ display: 'flex', alignItems: 'baseline', gap: 8, padding: '7px 11px', cursor: 'pointer', background: active ? 'rgba(34,255,106,.10)' : 'transparent' }}
    >
      <span style={{ fontFamily: C.mono, fontSize: 12.5, color: C.green, flex: '0 0 auto' }}>/{cmd.name}</span>
      <span style={{ fontFamily: C.sans, fontSize: 11.5, color: C.muted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>{cmd.desc}</span>
      <span style={{ fontFamily: C.mono, fontSize: 9, color: SRC[cmd.source]?.color ?? C.faint, flex: '0 0 auto' }}>{SRC[cmd.source]?.label}</span>
    </div>
  );
}
