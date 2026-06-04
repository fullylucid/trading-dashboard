import { useState, useEffect } from 'react';
import { Rnd } from 'react-rnd';
import { TICKER_H } from '../../layout';
import useMessengerStore from '../../store/messengerStore';
import ConversationList from './ConversationList';
import ChatPane from './ChatPane';

const GREEN = '#00ff41';

const panelStyle: React.CSSProperties = {
  background: '#000',
  border: `1px solid ${GREEN}`,
  borderRadius: 6,
  boxShadow: '0 0 16px rgba(0,255,65,0.4)',
  display: 'flex',
  flexDirection: 'column',
  height: '100%',
  width: '100%',
  overflow: 'hidden',
  fontFamily: 'monospace',
};

const titleBarStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  padding: '6px 10px',
  borderBottom: `1px solid rgba(0,255,65,0.3)`,
  color: GREEN,
  cursor: 'move',
  userSelect: 'none',
};

// Finger-sized tap targets for collapse/close (the old bare glyphs were ~12px and un-tappable).
const msgrBtnStyle: React.CSSProperties = {
  background: 'transparent',
  border: 'none',
  color: GREEN,
  cursor: 'pointer',
  fontSize: 16,
  lineHeight: 1,
  padding: '2px 10px',
  minWidth: 38,
  minHeight: 26,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  borderRadius: 4,
};

function LoginGate() {
  const login = useMessengerStore((s) => s.login);
  const [pw, setPw] = useState('');
  const [err, setErr] = useState(false);
  return (
    <div style={{ padding: 16, color: GREEN, fontFamily: 'monospace' }}>
      <div style={{ marginBottom: 8 }}>🔒 Authenticate</div>
      <input
        type="password"
        value={pw}
        onChange={(e) => setPw(e.target.value)}
        onKeyDown={async (e) => {
          if (e.key === 'Enter') {
            const ok = await login(pw);
            setErr(!ok);
          }
        }}
        placeholder="password"
        style={{ background: '#000', color: GREEN, border: `1px solid ${GREEN}`, borderRadius: 4, padding: 6, width: '100%', fontFamily: 'monospace' }}
      />
      {err && <div style={{ color: '#ff5555', marginTop: 6, fontSize: 12 }}>Invalid credentials</div>}
    </div>
  );
}

function MessengerWidget() {
  const geometry = useMessengerStore((s) => s.geometry);
  const setGeometry = useMessengerStore((s) => s.setGeometry);
  const toggleOpen = useMessengerStore((s) => s.toggleOpen);
  const toggleCollapsed = useMessengerStore((s) => s.toggleCollapsed);
  const authed = useMessengerStore((s) => s.authed);
  const wsConnected = useMessengerStore((s) => s.agentWsConnected);
  const init = useMessengerStore((s) => s.init);

  // On mount, check whether app-level auth is required; auto-enter if not.
  useEffect(() => {
    if (!authed) init();
  }, [authed, init]);

  // Launcher bubble when closed
  if (!geometry.open) {
    return (
      <button
        type="button"
        onClick={toggleOpen}
        aria-label="Open messenger"
        style={{
          position: 'fixed',
          bottom: TICKER_H + 16,  // float above the fixed bottom ticker
          right: 20,
          zIndex: 3000,
          background: '#000',
          color: GREEN,
          border: `1px solid ${GREEN}`,
          borderRadius: '50%',
          width: 52,
          height: 52,
          fontSize: 22,
          cursor: 'pointer',
          boxShadow: '0 0 14px rgba(0,255,65,0.5)',
        }}
      >
        💬
      </button>
    );
  }

  const collapsedHeight = 38;

  return (
    <Rnd
      size={{ width: geometry.w, height: geometry.collapsed ? collapsedHeight : geometry.h }}
      position={{ x: geometry.x, y: geometry.y }}
      minWidth={300}
      minHeight={collapsedHeight}
      bounds="window"
      dragHandleClassName="messenger-drag-handle"
      cancel=".messenger-btn"
      onDragStop={(_e, d) => setGeometry({ x: d.x, y: d.y })}
      onResizeStop={(_e, _dir, ref, _delta, pos) =>
        setGeometry({ w: ref.offsetWidth, h: ref.offsetHeight, x: pos.x, y: pos.y })
      }
      style={{ zIndex: 3000 }}
    >
      <div style={panelStyle}>
        <div className="messenger-drag-handle" style={titleBarStyle}>
          <span>
            🕷️ Messenger{' '}
            <span style={{ fontSize: 10, opacity: 0.7 }}>
              {wsConnected ? '● live' : '○ offline'}
            </span>
          </span>
          <span style={{ display: 'flex', gap: 4 }}>
            {/* real buttons + `messenger-btn` (excluded from Rnd drag via cancel) so a tap
                collapses/closes instead of starting a drag; finger-sized tap targets. */}
            <button type="button" className="messenger-btn" onClick={toggleCollapsed}
              title={geometry.collapsed ? 'Expand' : 'Collapse'} aria-label="Collapse messenger"
              style={msgrBtnStyle}>
              {geometry.collapsed ? '▢' : '—'}
            </button>
            <button type="button" className="messenger-btn" onClick={toggleOpen}
              title="Close" aria-label="Close messenger" style={msgrBtnStyle}>
              ✕
            </button>
          </span>
        </div>
        {!geometry.collapsed && (
          <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
            {authed ? (
              <>
                <ConversationList />
                <ChatPane />
              </>
            ) : (
              <LoginGate />
            )}
          </div>
        )}
      </div>
    </Rnd>
  );
}

export default MessengerWidget;
