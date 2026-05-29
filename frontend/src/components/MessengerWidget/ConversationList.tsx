import useMessengerStore from '../../store/messengerStore';

const GREEN = '#00ff41';

const railStyle: React.CSSProperties = {
  width: 140,
  borderRight: `1px solid rgba(0,255,65,0.3)`,
  display: 'flex',
  flexDirection: 'column',
  fontFamily: 'monospace',
  overflow: 'hidden',
};

const newBtnStyle: React.CSSProperties = {
  background: '#000',
  color: GREEN,
  border: `1px solid ${GREEN}`,
  borderRadius: 4,
  padding: '6px 8px',
  margin: 6,
  cursor: 'pointer',
  fontSize: 12,
  fontFamily: 'monospace',
};

function ConversationList() {
  const conversations = useMessengerStore((s) => s.conversations);
  const activeId = useMessengerStore((s) => s.activeConversationId);
  const select = useMessengerStore((s) => s.selectConversation);
  const create = useMessengerStore((s) => s.newConversation);
  const remove = useMessengerStore((s) => s.deleteConversation);

  return (
    <div style={railStyle}>
      <button type="button" style={newBtnStyle} onClick={() => create()}>
        ＋ New chat
      </button>
      <div style={{ overflowY: 'auto', flex: 1 }}>
        {conversations.map((c) => {
          const active = c.conversationId === activeId;
          return (
            <div
              key={c.conversationId}
              onClick={() => select(c.conversationId)}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 4,
                padding: '6px 8px',
                cursor: 'pointer',
                fontSize: 11,
                color: GREEN,
                background: active ? 'rgba(0,255,65,0.15)' : 'transparent',
                borderBottom: '1px solid rgba(0,255,65,0.12)',
              }}
            >
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {c.title}
              </span>
              <span
                onClick={(e) => {
                  e.stopPropagation();
                  remove(c.conversationId);
                }}
                title="Delete"
                style={{ opacity: 0.5, paddingLeft: 4 }}
              >
                ✕
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default ConversationList;
