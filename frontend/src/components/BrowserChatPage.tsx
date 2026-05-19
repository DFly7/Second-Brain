import React, { useCallback, useEffect, useRef, useState } from 'react'
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
import TopBar from './TopBar'

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
  }, [messages])

  // Blur listener: fires when user clicks into the noVNC iframe while agent is running.
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
      <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden', background: '#0d1117' }}>
        {/* Left: chat */}
        <div style={{
          width: 320,
          flexShrink: 0,
          background: '#161b22',
          borderRight: '1px solid #30363d',
          display: 'flex',
          flexDirection: 'column',
        }}>
          <div style={{ padding: '10px 14px', borderBottom: '1px solid #30363d', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.8px', color: '#8b949e' }}>
            Chat
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
            {messages.length === 0 && (
              <div style={{ color: '#8b949e', fontSize: 12, fontStyle: 'italic', textAlign: 'center', marginTop: 24 }}>
                Type a message to get started.
              </div>
            )}
            {messages.map(msg => (
              <React.Fragment key={msg.id}>
                <div style={{
                  alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  maxWidth: '90%',
                  background: msg.role === 'user' ? '#1f3a5f' : '#21262d',
                  border: `1px solid ${msg.role === 'user' ? '#388bfd40' : '#30363d'}`,
                  borderRadius: msg.role === 'user' ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
                  padding: '8px 12px',
                  fontSize: 13,
                  color: '#e6edf3',
                  lineHeight: 1.5,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}>
                  {msg.content}
                </div>
              </React.Fragment>
            ))}
            {actions.map(action => (
              <div key={action.id} style={{
                alignSelf: 'flex-start',
                display: 'flex',
                alignItems: 'baseline',
                gap: 6,
                padding: '3px 8px',
                fontSize: 11,
                color: action.error ? '#f85149' : '#8b949e',
                fontFamily: 'monospace',
              }}>
                <span>{action.error ? '⚠' : actionIcon(action.type)}</span>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 260 }}>
                  {action.detail}
                </span>
              </div>
            ))}
            {agentRunning && (
              <div style={{ alignSelf: 'flex-start', background: '#21262d', border: '1px solid #30363d', borderRadius: '12px 12px 12px 2px', padding: '8px 12px', fontSize: 13, color: '#8b949e' }}>
                <span style={{ animation: 'pulse 1.5s ease-in-out infinite', display: 'inline-block' }}>thinking…</span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
          <div style={{ padding: '10px 12px', borderTop: '1px solid #30363d', display: 'flex', flexDirection: 'column', gap: 8 }}>
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSend() }}
              disabled={agentRunning}
              placeholder={agentRunning ? 'Agent is working…' : 'Tell the agent what to do… (⌘↵ to send)'}
              rows={3}
              style={{
                width: '100%',
                background: '#0d1117',
                border: `1px solid ${agentRunning ? '#30363d' : '#388bfd40'}`,
                borderRadius: 8,
                padding: '8px 10px',
                color: agentRunning ? '#8b949e' : '#e6edf3',
                fontSize: 13,
                resize: 'none',
                outline: 'none',
                fontFamily: 'inherit',
                lineHeight: 1.5,
                boxSizing: 'border-box',
              }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <button
                type="button"
                onClick={handleDisconnect}
                style={{ padding: '5px 10px', background: 'transparent', border: '1px solid #f8514940', borderRadius: 6, color: '#f85149', fontSize: 11, cursor: 'pointer' }}
              >
                Disconnect
              </button>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <label style={{ fontSize: 11, color: '#8b949e' }}>Turns</label>
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={maxTurns}
                  onChange={e => setMaxTurns(Math.max(1, Math.min(100, Number(e.target.value))))}
                  style={{ width: 46, padding: '3px 6px', background: '#0d1117', border: '1px solid #30363d', borderRadius: 5, color: '#e6edf3', fontSize: 11, textAlign: 'center' }}
                />
              </div>
              <button
                type="button"
                onClick={handleRecover}
                disabled={recovering || agentRunning}
                style={{
                  padding: '5px 10px',
                  background: 'transparent',
                  border: `1px solid ${recovering || agentRunning ? '#30363d' : '#d2992240'}`,
                  borderRadius: 6,
                  color: recovering || agentRunning ? '#8b949e' : '#d29922',
                  fontSize: 11,
                  cursor: recovering || agentRunning ? 'default' : 'pointer',
                }}
              >
                {recovering ? 'Recovering…' : 'Recover Browser'}
              </button>
              <button
                type="button"
                onClick={handleSend}
                disabled={!input.trim() || agentRunning}
                style={{
                  padding: '6px 14px',
                  background: input.trim() && !agentRunning ? '#238636' : '#21262d',
                  border: `1px solid ${input.trim() && !agentRunning ? '#2ea043' : '#30363d'}`,
                  borderRadius: 6,
                  color: input.trim() && !agentRunning ? '#ffffff' : '#8b949e',
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: input.trim() && !agentRunning ? 'pointer' : 'default',
                }}
              >
                Send
              </button>
            </div>
          </div>
        </div>

        {/* Right: browser */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <div style={{ background: '#161b22', borderBottom: '1px solid #30363d', padding: '8px 12px', display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
            <div style={{ display: 'flex', gap: 4 }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#f85149', display: 'inline-block' }} />
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#ffbd2e', display: 'inline-block' }} />
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#3fb950', display: 'inline-block' }} />
            </div>
            <div style={{ flex: 1, background: '#0d1117', border: '1px solid #30363d', borderRadius: 6, padding: '4px 12px', fontSize: 12, color: '#8b949e', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {currentUrl || 'Browser ready'}
            </div>
            {agentRunning && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 5, background: '#388bfd12', border: '1px solid #388bfd40', padding: '3px 8px', borderRadius: 20, fontSize: 11, color: '#58a6ff', flexShrink: 0 }}>
                <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#58a6ff', display: 'inline-block', animation: 'pulse 1.5s ease-in-out infinite' }} />
                Working
              </div>
            )}
          </div>
          <div style={{ flex: 1, background: '#000', overflow: 'hidden' }}>
            {novncUrl ? (
              <iframe
                src={novncUrl}
                style={{ width: '100%', height: '100%', border: 'none', display: 'block' }}
                title="Live browser"
              />
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#8b949e', fontSize: 13 }}>
                Connecting to browser…
              </div>
            )}
          </div>
        </div>

        <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }`}</style>
      </div>
  ) : (
    <div style={{ flex: 1, overflowY: 'auto', background: '#0d1117', padding: 24 }}>
      <div style={{ maxWidth: 680, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 16 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: '#e6edf3', margin: 0 }}>Browser Chat</h2>

        <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 10, padding: 24, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
          <div style={{ fontSize: 13, color: '#8b949e', textAlign: 'center', lineHeight: 1.6 }}>
            Connect to a live browser and chat with an agent that controls it in real time.
          </div>
          {connectError && (
            <div style={{ fontSize: 12, color: '#f85149' }}>{connectError}</div>
          )}
          <button
            type="button"
            onClick={handleConnect}
            disabled={connectionState === 'connecting'}
            style={{
              padding: '10px 28px',
              background: connectionState === 'connecting' ? '#21262d' : '#238636',
              border: `1px solid ${connectionState === 'connecting' ? '#30363d' : '#2ea043'}`,
              borderRadius: 8,
              color: connectionState === 'connecting' ? '#8b949e' : '#ffffff',
              fontSize: 14,
              fontWeight: 600,
              cursor: connectionState === 'connecting' ? 'default' : 'pointer',
            }}
          >
            {connectionState === 'connecting' ? 'Connecting…' : 'Connect'}
          </button>
        </div>

        {pastSessions.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.8px', color: '#8b949e' }}>Past Sessions</div>
            {pastSessions.map(s => (
              <div key={s.id} style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 10, overflow: 'hidden' }}>
                <div style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ width: 7, height: 7, borderRadius: '50%', background: s.status === 'active' ? '#58a6ff' : '#8b949e', display: 'inline-block', flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, color: '#e6edf3' }}>
                      {new Date(s.created_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}
                    </div>
                    <div style={{ fontSize: 11, color: '#8b949e' }}>
                      {s.status === 'active' ? 'Active' : 'Completed'}
                      {s.completed_at && ` · ${Math.round((new Date(s.completed_at).getTime() - new Date(s.created_at).getTime()) / 60000)}m`}
                    </div>
                  </div>
                  {s.status === 'active' && (
                    <button
                      type="button"
                      onClick={() => handlePastDisconnect(s.id)}
                      style={{ padding: '4px 8px', background: 'transparent', border: '1px solid #f8514940', borderRadius: 5, color: '#f85149', fontSize: 11, cursor: 'pointer' }}
                    >
                      Disconnect
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => toggleExpandSession(s.id)}
                    style={smallBtn}
                  >
                    Messages {expandedSessionId === s.id ? '▴' : '▾'}
                  </button>
                </div>
                {expandedSessionId === s.id && (
                  <div style={{ borderTop: '1px solid #30363d', background: '#0d1117', padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {expandedMessages.length === 0 && (
                      <div style={{ fontSize: 12, color: '#8b949e', fontStyle: 'italic' }}>No messages.</div>
                    )}
                    {expandedMessages.map(m => (
                      <div key={m.id} style={{
                        alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                        maxWidth: '90%',
                        background: m.role === 'user' ? '#1f3a5f' : '#21262d',
                        border: `1px solid ${m.role === 'user' ? '#388bfd40' : '#30363d'}`,
                        borderRadius: 8,
                        padding: '6px 10px',
                        fontSize: 12,
                        color: '#c9d1d9',
                        lineHeight: 1.5,
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                      }}>
                        {m.content}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <TopBar />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden', minHeight: 0 }}>
        {pageContent}
      </div>
    </div>
  )
}

const smallBtn: React.CSSProperties = {
  padding: '4px 10px',
  background: '#21262d',
  border: '1px solid #30363d',
  borderRadius: 6,
  color: '#8b949e',
  fontSize: 11,
  cursor: 'pointer',
  flexShrink: 0,
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
