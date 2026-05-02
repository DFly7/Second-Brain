interface Session { id: string; created_at: string }

interface SessionDrawerProps {
  open: boolean
  sessions: Session[]
  loadError: boolean
  activeSessionId: string | undefined
  onSelect: (id: string) => void
  onNewChat: () => void
  onClose: () => void
}

function formatSessionDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export default function SessionDrawer({
  open,
  sessions,
  loadError,
  activeSessionId,
  onSelect,
  onNewChat,
  onClose,
}: SessionDrawerProps) {
  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        right: 0,
        bottom: 0,
        width: 260,
        background: '#161b22',
        borderLeft: '1px solid #30363d',
        display: 'flex',
        flexDirection: 'column',
        transform: open ? 'translateX(0)' : 'translateX(100%)',
        transition: 'transform 200ms ease',
        zIndex: 10,
      }}
    >
      <div style={{
        padding: '12px 16px',
        borderBottom: '1px solid #30363d',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <span style={{ fontSize: 13, color: '#8b949e' }}>History</span>
        <button
          onClick={onClose}
          style={{
            background: 'none', border: 'none', color: '#8b949e',
            cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: 0,
          }}
          title="Close"
        >
          ×
        </button>
      </div>
      <div style={{ padding: '8px 12px', borderBottom: '1px solid #30363d' }}>
        <button
          onClick={onNewChat}
          style={{
            width: '100%', padding: '7px 12px', background: '#238636',
            border: 'none', borderRadius: 6, color: '#fff',
            cursor: 'pointer', fontSize: 13, textAlign: 'left',
          }}
        >
          + New Chat
        </button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: 8 }}>
        {loadError && (
          <div style={{ color: '#f85149', fontSize: 12, padding: '8px 4px' }}>
            Failed to load history
          </div>
        )}
        {!loadError && sessions.length === 0 && (
          <div style={{ color: '#8b949e', fontSize: 12, padding: '8px 4px' }}>
            No previous chats
          </div>
        )}
        {sessions.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            style={{
              display: 'block', width: '100%', textAlign: 'left',
              padding: '8px 10px', borderRadius: 6, marginBottom: 2,
              background: s.id === activeSessionId ? '#1f6feb22' : 'none',
              border: s.id === activeSessionId ? '1px solid #1f6feb55' : '1px solid transparent',
              color: s.id === activeSessionId ? '#58a6ff' : '#c9d1d9',
              cursor: 'pointer', fontSize: 12,
            }}
          >
            {formatSessionDate(s.created_at)}
          </button>
        ))}
      </div>
    </div>
  )
}
