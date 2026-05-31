import { useState, useRef, useEffect } from 'react';
import useMessengerStore, { JobKind, ChatMessage } from '../../store/messengerStore';

const GREEN = '#00ff41';

const KINDS: { value: JobKind; label: string }[] = [
  { value: 'brainstorm', label: '💭 Brainstorm' },
  { value: 'data', label: '📊 Data' },
  { value: 'code', label: '🛠️ Code' },
  { value: 'scan', label: '🔭 Scan' },
];

function PrCard({ msg }: { msg: ChatMessage }) {
  const approve = useMessengerStore((s) => s.approve);
  if (!msg.jobId) return null;
  return (
    <div
      style={{
        border: `1px solid ${GREEN}`,
        borderRadius: 4,
        padding: 8,
        marginTop: 6,
        background: 'rgba(0,255,65,0.08)',
      }}
    >
      {msg.prUrl && (
        <a href={msg.prUrl} target="_blank" rel="noreferrer" style={{ color: GREEN }}>
          🔗 View pull request
        </a>
      )}
      <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
        <button
          type="button"
          onClick={() => approve(msg.jobId!, 'merge')}
          style={{ background: '#000', color: GREEN, border: `1px solid ${GREEN}`, borderRadius: 4, padding: '4px 10px', cursor: 'pointer' }}
        >
          Approve & merge
        </button>
        <button
          type="button"
          onClick={() => approve(msg.jobId!, 'reject')}
          style={{ background: '#000', color: '#ff5555', border: '1px solid #ff5555', borderRadius: 4, padding: '4px 10px', cursor: 'pointer' }}
        >
          Reject
        </button>
      </div>
    </div>
  );
}

function ChatPane() {
  const activeId = useMessengerStore((s) => s.activeConversationId);
  const messages = useMessengerStore((s) => (activeId ? s.messages[activeId] || [] : []));
  const send = useMessengerStore((s) => s.send);
  const [text, setText] = useState('');
  const [kind, setKind] = useState<JobKind>('brainstorm');
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    // Scroll the chat container itself to the bottom — NOT scrollIntoView,
    // which scrolls every scrollable ancestor (including the whole page) and
    // made the window jump on chat switch / new message.
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, activeId]);

  const submit = () => {
    const t = text.trim();
    if (!t || !activeId) return;
    send(t, kind);
    setText('');
  };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', fontFamily: 'monospace', minWidth: 0 }}>
      <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', padding: 8 }}>
        {!activeId && <div style={{ color: GREEN, opacity: 0.6 }}>Pick or start a chat →</div>}
        {messages.map((m, i) => (
          <div key={i} style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 10, opacity: 0.6, color: GREEN }}>
              {m.role === 'user' ? 'you' : 'claude'}
            </div>
            <div
              style={{
                color: m.type === 'error' ? '#ff5555' : GREEN,
                whiteSpace: 'pre-wrap',
                fontSize: 12,
                lineHeight: 1.4,
              }}
            >
              {m.content}
            </div>
            {m.approvalKind === 'pr' && <PrCard msg={m} />}
          </div>
        ))}
      </div>
      <div style={{ borderTop: '1px solid rgba(0,255,65,0.3)', padding: 6 }}>
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as JobKind)}
          style={{ background: '#000', color: GREEN, border: `1px solid ${GREEN}`, borderRadius: 4, fontFamily: 'monospace', fontSize: 11, marginBottom: 6 }}
        >
          {KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
        <div style={{ display: 'flex', gap: 6 }}>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="Message Claude…"
            rows={2}
            style={{
              flex: 1,
              background: '#000',
              color: GREEN,
              border: `1px solid ${GREEN}`,
              borderRadius: 4,
              fontFamily: 'monospace',
              fontSize: 12,
              padding: 6,
              resize: 'none',
            }}
          />
          <button
            type="button"
            onClick={submit}
            style={{ background: '#000', color: GREEN, border: `1px solid ${GREEN}`, borderRadius: 4, padding: '0 12px', cursor: 'pointer' }}
          >
            ➤
          </button>
        </div>
      </div>
    </div>
  );
}

export default ChatPane;
