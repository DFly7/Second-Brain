import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import {
  type BrowserChatMessage,
  type BrowserChatSession,
  connectBrowserChat,
  disconnectBrowserChat,
  getBrowserChatSession,
  getNovncUrl,
  interruptBrowserChat,
  listBrowserChatSessions,
  recoverBrowserChat,
  sendBrowserChatMessage,
} from '../api/client'
import { useSse } from '../hooks/useSse'

type ActionItem = {
  id: string
  type: string
  detail: string
  error?: boolean
}

type ConnectionState = 'disconnected' | 'connecting' | 'connected'

export default function BrowserChatPage() {
  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected')
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<BrowserChatMessage[]>([])
  const [agentRunning, setAgentRunning] = useState(false)
  const [novncUrl, setNovncUrl] = useState<string | null>(null)
  const [pastSessions, setPastSessions] = useState<BrowserChatSession[]>([])
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(null)
  const [expandedMessages, setExpandedMessages] = useState<BrowserChatMessage[]>([])
  const [input, setInput] = useState('')
  const [connectError, setConnectError] = useState<string | null>(null)
  const [recovering, setRecovering] = useState(false)
  const [currentUrl, setCurrentUrl] = useState('')
  const [actions, setActions] = useState<ActionItem[]>([])
  const [maxTurns, setMaxTurns] = useState(20)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    getNovncUrl().then(setNovncUrl).catch(() => {})
    listBrowserChatSessions().then(setPastSessions).catch(() => {})
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, actions, agentRunning])

  const handleWindowBlur = useCallback(() => {
    if (activeSessionId && agentRunning) {
      interruptBrowserChat(activeSessionId).catch(() => {})
    }
  }, [activeSessionId, agentRunning])

  useEffect(() => {
    if (agentRunning) {
      window.addEventListener('blur', handleWindowBlur)
      return () => window.removeEventListener('blur', handleWindowBlur)
    }
  }, [agentRunning, handleWindowBlur])

  useSse((data: unknown) => {
    const ev = data as Record<string, unknown>
    if (ev.session_id !== activeSessionId) return

    if (ev.event === 'browser_chat:action') {
      if (ev.type === 'navigate') {
        setCurrentUrl(String(ev.detail ?? '').replace('Navigated to ', ''))
      }
      setActions(prev => [...prev, {
        id: String(Date.now()) + Math.random(),
        type: String(ev.type ?? ''),
        detail: String(ev.detail ?? ''),
        error: ev.error === true,
      }])
    }
    if (ev.event === 'browser_chat:reply') {
      const msg: BrowserChatMessage = {
        id: String(Date.now()),
        role: 'assistant',
        content: String(ev.content ?? ''),
        created_at: new Date().toISOString(),
      }
      setMessages(prev => [...prev, msg])
      setAgentRunning(false)
      inputRef.current?.focus()
    }
    if (ev.event === 'browser_chat:status') {
      setAgentRunning(ev.status === 'thinking')
    }
  })

  async function handleConnect() {
    setConnectError(null)
    setConnectionState('connecting')
    try {
      const { session_id } = await connectBrowserChat()
      setActiveSessionId(session_id)
      setMessages([])
      setCurrentUrl('')
      setConnectionState('connected')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setConnectError(msg.includes('409') ? 'A browser session is already active.' : 'Failed to connect.')
      setConnectionState('disconnected')
    }
  }

  async function handleDisconnect() {
    if (!activeSessionId) return
    try {
      await disconnectBrowserChat(activeSessionId)
    } catch { /* best-effort */ }
    setConnectionState('disconnected')
    setActiveSessionId(null)
    setMessages([])
    setAgentRunning(false)
    listBrowserChatSessions().then(setPastSessions).catch(() => {})
  }

  async function handlePastDisconnect(sessionId: string) {
    try {
      await disconnectBrowserChat(sessionId)
    } catch { /* best-effort */ }
    listBrowserChatSessions().then(setPastSessions).catch(() => {})
  }

  async function handleRecover() {
    if (!activeSessionId || recovering) return
    setRecovering(true)
    try {
      await recoverBrowserChat(activeSessionId)
      setMessages(prev => [...prev, {
        id: String(Date.now()),
        role: 'assistant',
        content: 'Browser recovered — you have a fresh tab. Tell me where to continue.',
        created_at: new Date().toISOString(),
      }])
    } catch {
      setMessages(prev => [...prev, {
        id: String(Date.now()),
        role: 'assistant',
        content: 'Failed to recover the browser. Try disconnecting and reconnecting.',
        created_at: new Date().toISOString(),
      }])
    } finally {
      setRecovering(false)
    }
  }

  async function handleSend() {
    if (!input.trim() || !activeSessionId || agentRunning) return
    const content = input.trim()
    setInput('')
    const userMsg: BrowserChatMessage = {
      id: String(Date.now()),
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    }
    setMessages(prev => [...prev, userMsg])
    setAgentRunning(true)
    setActions([])
    try {
      await sendBrowserChatMessage(activeSessionId, content, maxTurns)
    } catch {
      setAgentRunning(false)
      setMessages(prev => [...prev, {
        id: String(Date.now() + 1),
        role: 'assistant',
        content: 'Failed to send message. Please try again.',
        created_at: new Date().toISOString(),
      }])
    }
  }

  async function toggleExpandSession(sessionId: string) {
    if (expandedSessionId === sessionId) {
      setExpandedSessionId(null)
      setExpandedMessages([])
      return
    }
    setExpandedSessionId(sessionId)
    try {
      const detail = await getBrowserChatSession(sessionId)
      setExpandedMessages(detail.messages)
    } catch { setExpandedMessages([]) }
  }

  const pageContent = connectionState === 'connected' ? (
    <div className="flex min-h-0 flex-1 overflow-hidden bg-background">
      {/* Left: chat */}
      <div className="flex w-80 shrink-0 flex-col border-r border-border bg-background">
        <div className="shrink-0 border-b border-border px-3 py-2.5">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Chat
          </span>
        </div>

        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto py-2">
          {messages.length === 0 && (
            <p className="mt-10 px-3 text-center text-sm italic text-muted-foreground">
              Type a message to get started.
            </p>
          )}
          {messages.map(msg =>
            msg.role === 'user' ? (
              <div
                key={msg.id}
                className="whitespace-pre-wrap break-words px-3 py-2 text-sm text-foreground"
              >
                {msg.content}
              </div>
            ) : (
              <Card
                key={msg.id}
                className="mx-3 my-2 border-border bg-card p-3 text-sm leading-relaxed text-card-foreground"
              >
                <div className="whitespace-pre-wrap break-words">{msg.content}</div>
              </Card>
            ),
          )}
          {actions.map(action => (
            <div
              key={action.id}
              className={cn(
                'flex items-baseline gap-1.5 px-3 py-0.5 font-mono text-xs',
                action.error ? 'text-destructive' : 'text-muted-foreground',
              )}
            >
              <span className="shrink-0">{action.error ? '⚠' : actionIcon(action.type)}</span>
              <span className="max-w-[260px] truncate">{action.detail}</span>
            </div>
          ))}
          {agentRunning && (
            <Card className="mx-3 my-2 border-border bg-muted/50 p-3 text-sm text-muted-foreground">
              <span className="inline-block animate-pulse">thinking…</span>
            </Card>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="shrink-0 space-y-2 border-t border-border p-3">
          <Textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSend() }}
            disabled={agentRunning}
            placeholder={agentRunning ? 'Agent is working…' : 'Tell the agent what to do… (⌘↵ to send)'}
            rows={3}
            className="min-h-0 resize-none text-sm"
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 border-destructive/40 text-destructive hover:text-destructive"
              onClick={handleDisconnect}
            >
              Disconnect
            </Button>
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-muted-foreground">Turns</label>
              <Input
                type="number"
                min={1}
                max={100}
                value={maxTurns}
                onChange={e => setMaxTurns(Math.max(1, Math.min(100, Number(e.target.value))))}
                className="h-7 w-12 px-1.5 text-center text-xs"
              />
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              onClick={handleRecover}
              disabled={recovering || agentRunning}
            >
              {recovering ? 'Recovering…' : 'Recover Browser'}
            </Button>
            <Button
              type="button"
              size="sm"
              className="h-7"
              onClick={handleSend}
              disabled={!input.trim() || agentRunning}
            >
              Send
            </Button>
          </div>
        </div>
      </div>

      {/* Right: browser */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center gap-2.5 border-b border-border bg-muted/30 px-3 py-2">
          <div className="flex gap-1">
            <span className="inline-block size-2.5 rounded-full bg-destructive" />
            <span className="inline-block size-2.5 rounded-full bg-amber-400" />
            <span className="inline-block size-2.5 rounded-full bg-emerald-500" />
          </div>
          <div className="min-w-0 flex-1 truncate rounded-md border border-border bg-background px-3 py-1 text-xs text-muted-foreground">
            {currentUrl || 'Browser ready'}
          </div>
          {agentRunning && (
            <div className="flex shrink-0 items-center gap-1.5 rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-xs text-primary">
              <span className="inline-block size-1.5 animate-pulse rounded-full bg-primary" />
              Working
            </div>
          )}
        </div>
        <div className="min-h-0 flex-1 overflow-hidden bg-black">
          {novncUrl ? (
            <iframe
              src={novncUrl}
              className="block h-full w-full border-0"
              title="Live browser"
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              Connecting to browser…
            </div>
          )}
        </div>
      </div>
    </div>
  ) : (
    <div className="min-h-0 flex-1 overflow-y-auto bg-background p-6">
      <div className="mx-auto flex max-w-2xl flex-col gap-4">
        <h2 className="text-lg font-semibold text-foreground">Browser Chat</h2>

        <Card className="flex flex-col items-center gap-3 border-border p-6">
          <p className="text-center text-sm leading-relaxed text-muted-foreground">
            Connect to a live browser and chat with an agent that controls it in real time.
          </p>
          {connectError && (
            <p className="text-sm text-destructive">{connectError}</p>
          )}
          <Button
            type="button"
            onClick={handleConnect}
            disabled={connectionState === 'connecting'}
          >
            {connectionState === 'connecting' ? 'Connecting…' : 'Connect'}
          </Button>
        </Card>

        {pastSessions.length > 0 && (
          <div className="flex flex-col gap-2">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Past Sessions
            </p>
            {pastSessions.map(s => (
              <Card key={s.id} className="overflow-hidden border-border">
                <div className="flex items-center gap-2.5 p-3">
                  <span
                    className={cn(
                      'inline-block size-1.5 shrink-0 rounded-full',
                      s.status === 'active' ? 'bg-primary' : 'bg-muted-foreground',
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-foreground">
                      {new Date(s.created_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {s.status === 'active' ? 'Active' : 'Completed'}
                      {s.completed_at && ` · ${Math.round((new Date(s.completed_at).getTime() - new Date(s.created_at).getTime()) / 60000)}m`}
                    </p>
                  </div>
                  {s.status === 'active' && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-7 border-destructive/40 text-destructive hover:text-destructive"
                      onClick={() => handlePastDisconnect(s.id)}
                    >
                      Disconnect
                    </Button>
                  )}
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 shrink-0 text-xs"
                    onClick={() => toggleExpandSession(s.id)}
                  >
                    Messages {expandedSessionId === s.id ? '▴' : '▾'}
                  </Button>
                </div>
                {expandedSessionId === s.id && (
                  <div className="flex flex-col gap-1.5 border-t border-border bg-muted/20 p-3">
                    {expandedMessages.length === 0 && (
                      <p className="text-sm italic text-muted-foreground">No messages.</p>
                    )}
                    {expandedMessages.map(m =>
                      m.role === 'user' ? (
                        <div
                          key={m.id}
                          className="ml-auto max-w-[90%] whitespace-pre-wrap break-words text-right text-sm text-foreground"
                        >
                          {m.content}
                        </div>
                      ) : (
                        <Card
                          key={m.id}
                          className="max-w-[90%] border-border bg-card p-2.5 text-sm leading-relaxed text-card-foreground"
                        >
                          <div className="whitespace-pre-wrap break-words">{m.content}</div>
                        </Card>
                      ),
                    )}
                  </div>
                )}
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  )

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {pageContent}
      </div>
    </div>
  )
}

function actionIcon(type: string): string {
  const icons: Record<string, string> = {
    navigate: '→',
    page_state: '⊞',
    click: '↖',
    click_at: '↖',
    mouse_move: '⤷',
    type: '✎',
    key: '⌨',
    focus: '◎',
    hover: '⤳',
    select: '▾',
    scroll: '⟳',
    wait_for: '⌛',
    read: '≡',
    execute_js: '{}',
    screenshot: '📷',
    wiki_write: '✦',
  }
  return icons[type] ?? '·'
}
