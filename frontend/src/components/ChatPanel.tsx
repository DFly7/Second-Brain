import { useState, useEffect, useCallback } from 'react'
import { sendMessage, listSessions, getSessionMessages } from '../api/client'
import ChatConversation, { type Message } from './ChatConversation'
import SessionDrawer from './SessionDrawer'

const SESSION_KEY = 'chat_session_id'

interface ChatPanelProps {
  onNavigate: (slug: string) => void
  activeSseEvent: { event: string; slug?: string } | null
}

interface Session { id: string; created_at: string }

export default function ChatPanel({ onNavigate, activeSseEvent }: ChatPanelProps) {
  const [sessionId, setSessionId] = useState<string | undefined>(
    () => localStorage.getItem(SESSION_KEY) ?? undefined
  )
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(false)
  const [editMode, setEditMode] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [sessions, setSessions] = useState<Session[]>([])
  const [sessionsError, setSessionsError] = useState(false)

  const loadSessions = useCallback(async () => {
    try {
      const data = await listSessions()
      setSessions(data)
      setSessionsError(false)
    } catch {
      setSessionsError(true)
    }
  }, [])

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  useEffect(() => {
    const id = localStorage.getItem(SESSION_KEY)
    if (!id) return
    getSessionMessages(id).then((msgs) => {
      if (msgs.length === 0) {
        localStorage.removeItem(SESSION_KEY)
        setSessionId(undefined)
        return
      }
      setMessages(msgs.map(m => ({ role: m.role as 'user' | 'assistant', content: m.content })))
    })
  }, [])

  function persistSession(id: string) {
    setSessionId(id)
    localStorage.setItem(SESSION_KEY, id)
  }

  async function handleSubmit(text: string) {
    setMessages(m => [...m, { role: 'user', content: text }])
    setLoading(true)
    const isNew = !sessionId
    try {
      const resp = await sendMessage(text, sessionId, editMode ? 'edit' : 'query')
      persistSession(resp.session_id)
      setMessages(m => [...m, { role: 'assistant', content: resp.answer, cited: resp.cited_pages }])
      if (isNew) await loadSessions()
    } finally {
      setLoading(false)
    }
  }

  async function handleSelectSession(id: string) {
    persistSession(id)
    const msgs = await getSessionMessages(id)
    setMessages(msgs.map(m => ({ role: m.role as 'user' | 'assistant', content: m.content })))
    setDrawerOpen(false)
  }

  function handleNewChat() {
    setMessages([])
    setSessionId(undefined)
    localStorage.removeItem(SESSION_KEY)
    setDrawerOpen(false)
  }

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100%',
      background: '#0d1117', borderLeft: '1px solid #30363d',
      position: 'relative', overflow: 'hidden',
    }}>
      <div style={{
        padding: '12px 16px', borderBottom: '1px solid #30363d',
        fontSize: 13, color: '#8b949e', background: '#161b22',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        flexShrink: 0,
      }}>
        <span>Chat</span>
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            onClick={handleNewChat}
            style={{
              padding: '4px 10px', fontSize: 12, borderRadius: 6,
              border: '1px solid #30363d', background: '#0d1117',
              color: '#8b949e', cursor: 'pointer',
            }}
            title="Start a new chat"
          >
            New Chat
          </button>
          <button
            onClick={() => setDrawerOpen(v => !v)}
            style={{
              padding: '4px 10px', fontSize: 12, borderRadius: 6,
              border: '1px solid #30363d',
              background: drawerOpen ? '#1f6feb22' : '#0d1117',
              color: drawerOpen ? '#58a6ff' : '#8b949e', cursor: 'pointer',
            }}
            title="View chat history"
          >
            History
          </button>
        </div>
      </div>
      <ChatConversation
        messages={messages}
        loading={loading}
        activeSseEvent={activeSseEvent}
        editMode={editMode}
        onSubmit={handleSubmit}
        onNavigate={onNavigate}
        onEditModeToggle={() => setEditMode(v => !v)}
      />
      <SessionDrawer
        open={drawerOpen}
        sessions={sessions}
        loadError={sessionsError}
        activeSessionId={sessionId}
        onSelect={handleSelectSession}
        onNewChat={handleNewChat}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  )
}
