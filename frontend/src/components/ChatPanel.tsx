import { useState, useEffect, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { sendMessage, listSessions, getSessionMessages } from '../api/client'
import ChatConversation, { type Message } from './ChatConversation'
import SessionDrawer from './SessionDrawer'

const SESSION_KEY = 'chat_session_id'
const SELECT_SESSION_EVENT = 'chat:select-session'

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
  const [messagesLoading, setMessagesLoading] = useState(!!localStorage.getItem(SESSION_KEY))
  const [editMode, setEditMode] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [sessions, setSessions] = useState<Session[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(true)
  const [sessionsError, setSessionsError] = useState(false)
  const [input, setInput] = useState('')

  const loadSessions = useCallback(async () => {
    setSessionsLoading(true)
    try {
      const data = await listSessions()
      setSessions(data)
      setSessionsError(false)
    } catch {
      setSessionsError(true)
    } finally {
      setSessionsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  useEffect(() => {
    const onSelect = (e: Event) => {
      const id = (e as CustomEvent<{ id: string }>).detail?.id
      if (id) void handleSelectSession(id)
    }
    window.addEventListener(SELECT_SESSION_EVENT, onSelect)
    return () => window.removeEventListener(SELECT_SESSION_EVENT, onSelect)
  }) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const id = localStorage.getItem(SESSION_KEY)
    if (!id) {
      setMessagesLoading(false)
      return
    }
    getSessionMessages(id)
      .then((msgs) => {
        if (msgs.length === 0) {
          localStorage.removeItem(SESSION_KEY)
          setSessionId(undefined)
          return
        }
        setMessages(msgs.map(m => ({ role: m.role as 'user' | 'assistant', content: m.content })))
      })
      .finally(() => setMessagesLoading(false))
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

  function handleComposerSubmit() {
    if (!input.trim() || loading) return
    const text = input.trim()
    setInput('')
    handleSubmit(text)
  }

  async function handleSelectSession(id: string) {
    persistSession(id)
    setMessagesLoading(true)
    try {
      const msgs = await getSessionMessages(id)
      setMessages(msgs.map(m => ({ role: m.role as 'user' | 'assistant', content: m.content })))
    } finally {
      setMessagesLoading(false)
      setDrawerOpen(false)
    }
  }

  function handleNewChat() {
    setMessages([])
    setSessionId(undefined)
    localStorage.removeItem(SESSION_KEY)
    setDrawerOpen(false)
  }

  return (
    <div className="relative flex h-full flex-col overflow-hidden border-l border-border bg-background">
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-border px-3">
        <span className="text-sm text-muted-foreground">Chat</span>
        <div className="flex gap-1.5">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={handleNewChat}
            title="Start a new chat"
          >
            New Chat
          </Button>
          <Button
            type="button"
            variant={drawerOpen ? 'secondary' : 'outline'}
            size="sm"
            className="h-7 text-xs"
            onClick={() => setDrawerOpen(v => !v)}
            title="View chat history"
          >
            History
          </Button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        <ChatConversation
          messages={messages}
          loading={loading}
          messagesLoading={messagesLoading}
          activeSseEvent={activeSseEvent}
          onNavigate={onNavigate}
        />
      </div>
      <div
        className={cn(
          'shrink-0 border-t border-border p-3',
          editMode && 'bg-amber-500/5 ring-1 ring-inset ring-amber-500/40',
        )}
      >
        <div className="flex items-end gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setEditMode(v => !v)}
            title={editMode ? 'Switch to read-only query' : 'Allow the agent to edit wiki pages'}
            className={cn(
              'shrink-0 whitespace-nowrap',
              editMode && 'border-amber-500/60 bg-amber-500/20 text-amber-500 hover:bg-amber-500/25',
            )}
          >
            Edit Mode
          </Button>
          <Textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleComposerSubmit()
              }
            }}
            placeholder="Ask your wiki..."
            rows={2}
            disabled={loading}
            className="min-h-0 flex-1 resize-none text-sm"
          />
          <Button
            type="button"
            size="sm"
            onClick={handleComposerSubmit}
            disabled={loading || !input.trim()}
            className="shrink-0"
          >
            Send
          </Button>
        </div>
      </div>
      <SessionDrawer
        open={drawerOpen}
        sessions={sessions}
        loading={sessionsLoading}
        loadError={sessionsError}
        activeSessionId={sessionId}
        onSelect={handleSelectSession}
        onNewChat={handleNewChat}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  )
}
