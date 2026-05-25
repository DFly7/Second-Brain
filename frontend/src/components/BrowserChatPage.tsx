import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { MoreHorizontal } from 'lucide-react'
import { cn } from '@/lib/utils'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from '@/components/ui/resizable'
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
  const [historicMessages, setHistoricMessages] = useState<BrowserChatMessage[]>([])
  const [priorSessionCreatedAt, setPriorSessionCreatedAt] = useState<string | null>(null)
  const [sessionParam] = useSearchParams()
  const [maxTurns, setMaxTurns] = useState(20)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    getNovncUrl().then(setNovncUrl).catch(() => {})
    listBrowserChatSessions().then(setPastSessions).catch(() => {})
  }, [])

  useEffect(() => {
    const paramId = sessionParam.get('session')
    if (!paramId || connectionState !== 'disconnected') return

    getBrowserChatSession(paramId).then(async detail => {
      if (detail.status === 'active') {
        setActiveSessionId(detail.id)
        setMessages(detail.messages)
        setHistoricMessages([])
        setPriorSessionCreatedAt(null)
        setCurrentUrl('')
        setConnectionState('connected')
      } else {
        setConnectionState('connecting')
        try {
          const { session_id } = await connectBrowserChat(detail.id)
          setActiveSessionId(session_id)
          setHistoricMessages(detail.messages)
          setPriorSessionCreatedAt(detail.created_at)
          setMessages([])
          setCurrentUrl('')
          setConnectionState('connected')
        } catch {
          setConnectError('Failed to resume session.')
          setConnectionState('disconnected')
        }
      }
    }).catch(() => {})
  }, [sessionParam, connectionState])

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
    setHistoricMessages([])
    setPriorSessionCreatedAt(null)
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
    setHistoricMessages([])
    setPriorSessionCreatedAt(null)
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
    <ResizablePanelGroup id="browser-chat" orientation="horizontal" className="min-h-0 flex-1">
      {/* Left: chat */}
      <ResizablePanel id="browser-chat-panel" defaultSize="28%" minSize="18%" maxSize="50%" className="flex flex-col border-r border-border bg-background">
        <div className="shrink-0 border-b border-border px-3 py-2.5">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Chat
          </span>
        </div>

        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto py-2">
          {historicMessages.length === 0 && messages.length === 0 && (
            <p className="mt-10 px-3 text-center text-sm italic text-muted-foreground">
              Type a message to get started.
            </p>
          )}
          {historicMessages.map(msg =>
            msg.role === 'user' ? (
              <div key={msg.id} className="flex justify-end px-3 py-1">
                <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-sm bg-muted px-3 py-2 text-sm text-foreground">
                  {msg.content}
                </div>
              </div>
            ) : (
              <Card
                key={msg.id}
                className="mx-3 my-2 border-border bg-card p-3 text-sm leading-relaxed text-card-foreground"
              >
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    p: ({ children }) => <p className="my-1">{children}</p>,
                    ul: ({ children }) => <ul className="my-1 list-disc pl-5">{children}</ul>,
                    ol: ({ children }) => <ol className="my-1 list-decimal pl-5">{children}</ol>,
                    a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer" className="text-primary underline">{children}</a>,
                    code: ({ children }) => <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">{children}</code>,
                    pre: ({ children }) => <pre className="my-2 overflow-x-auto rounded bg-muted p-2 font-mono text-xs">{children}</pre>,
                  }}
                >
                  {msg.content}
                </ReactMarkdown>
              </Card>
            ),
          )}
          {priorSessionCreatedAt && (
            <div className="my-3 flex items-center gap-2 px-3">
              <div className="h-px flex-1 bg-border" />
              <span className="shrink-0 text-xs text-muted-foreground">
                Resumed from {new Date(priorSessionCreatedAt).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}
              </span>
              <div className="h-px flex-1 bg-border" />
            </div>
          )}
          {messages.map(msg =>
            msg.role === 'user' ? (
              <div key={msg.id} className="flex justify-end px-3 py-1">
                <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-sm bg-muted px-3 py-2 text-sm text-foreground">
                  {msg.content}
                </div>
              </div>
            ) : (
              <Card
                key={msg.id}
                className="mx-3 my-2 border-border bg-card p-3 text-sm leading-relaxed text-card-foreground"
              >
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    p: ({ children }) => <p className="my-1">{children}</p>,
                    ul: ({ children }) => <ul className="my-1 list-disc pl-5">{children}</ul>,
                    ol: ({ children }) => <ol className="my-1 list-decimal pl-5">{children}</ol>,
                    a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer" className="text-primary underline">{children}</a>,
                    code: ({ children }) => <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">{children}</code>,
                    pre: ({ children }) => <pre className="my-2 overflow-x-auto rounded bg-muted p-2 font-mono text-xs">{children}</pre>,
                  }}
                >
                  {msg.content}
                </ReactMarkdown>
              </Card>
            ),
          )}
          {agentRunning && (
            <div className="mx-3 my-2 flex flex-col gap-1.5">
              {actions.length > 0 && (
                <ActionLog actions={actions} />
              )}
              <Card className="border-border bg-muted/50 p-3 text-sm text-muted-foreground">
                <span className="inline-block animate-pulse">thinking…</span>
              </Card>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="shrink-0 border-t border-border p-3 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <label className="text-xs text-muted-foreground">Max turns for this message</label>
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="h-6 w-6 text-xs"
                onClick={() => setMaxTurns(t => Math.max(1, t - 1))}
                disabled={agentRunning}
              >
                −
              </Button>
              <span className="w-8 text-center text-sm tabular-nums">{maxTurns}</span>
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="h-6 w-6 text-xs"
                onClick={() => setMaxTurns(t => Math.min(100, t + 1))}
                disabled={agentRunning}
              >
                +
              </Button>
            </div>
          </div>
          <Textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSend()
              }
            }}
            disabled={agentRunning}
            placeholder={agentRunning ? 'Agent is working…' : 'Tell the agent what to do…'}
            rows={3}
            className="min-h-0 resize-none text-sm"
          />
          <div className="flex items-center justify-between gap-2">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-muted-foreground"
                  disabled={agentRunning}
                >
                  <MoreHorizontal className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                <DropdownMenuItem
                  onClick={handleRecover}
                  disabled={recovering || agentRunning}
                >
                  {recovering ? 'Recovering…' : 'Recover Browser'}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={handleDisconnect}
                  className="text-destructive focus:text-destructive"
                >
                  Disconnect
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button
              type="button"
              size="sm"
              onClick={handleSend}
              disabled={!input.trim() || agentRunning}
            >
              Send
            </Button>
          </div>
        </div>
      </ResizablePanel>
      <ResizableHandle withHandle />
      {/* Right: browser */}
      <ResizablePanel id="browser-view" defaultSize="72%" minSize="50%" className="flex flex-col">
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
      </ResizablePanel>
    </ResizablePanelGroup>
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

function ActionLog({ actions }: { actions: ActionItem[] }) {
  const [expanded, setExpanded] = useState(false)
  const errorCount = actions.filter(a => a.error).length

  return (
    <div className="rounded-md border border-border bg-muted/30 text-xs">
      <button
        type="button"
        onClick={() => setExpanded(v => !v)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-muted-foreground hover:text-foreground"
      >
        <span className="font-mono">{expanded ? '▾' : '▸'}</span>
        <span>{actions.length} action{actions.length !== 1 ? 's' : ''}</span>
        {errorCount > 0 && (
          <span className="ml-auto text-destructive">{errorCount} error{errorCount !== 1 ? 's' : ''}</span>
        )}
        {errorCount === 0 && (
          <span className="ml-auto truncate font-mono text-muted-foreground/70">
            {actions[actions.length - 1]?.detail}
          </span>
        )}
      </button>
      {expanded && (
        <div className="flex flex-col border-t border-border py-1">
          {actions.map(action => (
            <div
              key={action.id}
              className={cn(
                'flex items-baseline gap-1.5 px-2.5 py-0.5 font-mono',
                action.error ? 'text-destructive' : 'text-muted-foreground',
              )}
            >
              <span className="shrink-0">{action.error ? '⚠' : actionIcon(action.type)}</span>
              <span className="min-w-0 break-all">{action.detail}</span>
            </div>
          ))}
        </div>
      )}
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
