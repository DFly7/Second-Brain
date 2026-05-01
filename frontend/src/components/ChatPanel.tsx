import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { sendMessage } from '../api/client'

interface Message { role: 'user' | 'assistant'; content: string; cited?: string[] }

function processWikilinks(text: string): string {
  return text.replace(/\[\[([^\]]+)\]\]/g, '[$1](wiki://$1)')
}

function isExternalHref(href: string): boolean {
  return /^(https?:\/\/|mailto:|tel:)/i.test(href)
}

function hrefToSlug(href: string): string | null {
  if (!href) return null
  if (href.startsWith('wiki://')) return href.slice(7)
  if (href.startsWith('#')) return null
  if (isExternalHref(href)) return null
  return href.replace(/^\.\//, '')
}

interface ChatPanelProps {
  onNavigate: (slug: string) => void
  activeSseEvent: { event: string; slug?: string } | null
}

function sseStatusLabel(active: { event: string; slug?: string } | null): string {
  if (!active) return 'Thinking…'
  if (active.event === 'agent:reading') {
    return active.slug ? `⟳ Reading ${active.slug}…` : '⟳ Reading…'
  }
  if (active.event === 'agent:writing') {
    return active.slug ? `⟳ Writing ${active.slug}…` : '⟳ Writing…'
  }
  return 'Thinking…'
}

function sseStatusAnimKey(active: { event: string; slug?: string } | null): string {
  if (!active) return 'thinking'
  return active.slug ?? active.event
}

export default function ChatPanel({ onNavigate, activeSseEvent }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [sessionId, setSessionId] = useState<string | undefined>()
  const [loading, setLoading] = useState(false)
  const [editMode, setEditMode] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  async function submit() {
    if (!input.trim() || loading) return
    const text = input.trim()
    setInput('')
    setMessages(m => [...m, { role: 'user', content: text }])
    setLoading(true)
    try {
      const resp = await sendMessage(text, sessionId, editMode ? 'edit' : 'query')
      setSessionId(resp.session_id)
      setMessages(m => [...m, { role: 'assistant', content: resp.answer, cited: resp.cited_pages }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100%',
      background: '#0d1117', borderLeft: '1px solid #30363d',
    }}>
      <style>{`
        @keyframes fadeSlide {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
      <div style={{
        padding: '12px 16px', borderBottom: '1px solid #30363d',
        fontSize: 13, color: '#8b949e', background: '#161b22',
      }}>
        Chat
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {messages.length === 0 && (
          <div style={{ color: '#8b949e', fontSize: 13, textAlign: 'center', marginTop: 40 }}>
            Ask anything — the agent will search your wiki.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} style={{ maxWidth: '90%', alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
            <div style={{
              padding: '8px 12px', borderRadius: 8, fontSize: 13, lineHeight: 1.6,
              background: m.role === 'user' ? '#1f6feb' : '#161b22',
              color: '#e6edf3', border: m.role === 'assistant' ? '1px solid #30363d' : 'none',
            }}>
              {m.role === 'assistant' ? (
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    a({ href, children }) {
                      const slug = href ? hrefToSlug(href) : null
                      if (href && slug) {
                        return (
                          <a
                            href={href}
                            onClick={(e) => {
                              e.preventDefault()
                              onNavigate(slug)
                            }}
                            style={{ color: '#58a6ff', cursor: 'pointer', textDecoration: 'underline' }}
                          >
                            {children}
                          </a>
                        )
                      }
                      return <a href={href} target="_blank" rel="noreferrer">{children}</a>
                    }
                  }}
                >
                  {processWikilinks(m.content)}
                </ReactMarkdown>
              ) : (
                m.content
              )}
            </div>
            {m.role === 'assistant' && m.cited && m.cited.length > 0 && (
              <div style={{ fontSize: 11, color: '#6e7681', marginTop: 6, paddingLeft: 4 }}>
                searched {m.cited.length} page{m.cited.length === 1 ? '' : 's'}
              </div>
            )}
            {m.cited && m.cited.length > 0 && (
              <div style={{ fontSize: 11, color: '#8b949e', marginTop: 4, paddingLeft: 4 }}>
                Sources: {m.cited.map((slug) => (
                  <span
                    key={slug}
                    onClick={() => onNavigate(slug)}
                    style={{ color: '#58a6ff', cursor: 'pointer', marginRight: 6, textDecoration: 'underline' }}
                  >
                    {slug}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div
            style={{
              alignSelf: 'flex-start',
              padding: '8px 12px',
              borderRadius: 8,
              fontSize: 13,
              lineHeight: 1.6,
              background: '#21262d',
              color: '#8b949e',
              border: '1px solid #30363d',
            }}
          >
            <span
              key={sseStatusAnimKey(activeSseEvent)}
              style={{ display: 'inline-block', animation: 'fadeSlide 200ms ease' }}
            >
              {sseStatusLabel(activeSseEvent)}
            </span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <div style={{
        padding: 12,
        borderTop: '1px solid #30363d',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        ...(editMode ? {
          boxShadow: 'inset 0 0 0 1px #d29922',
          background: 'rgba(210, 153, 34, 0.06)',
        } : {}),
      }}>
        <button
          type="button"
          onClick={() => setEditMode(v => !v)}
          title={editMode ? 'Switch to read-only query' : 'Allow the agent to edit wiki pages'}
          style={{
            padding: '8px 12px',
            borderRadius: 6,
            fontSize: 13,
            cursor: 'pointer',
            flexShrink: 0,
            border: editMode ? '1px solid #d29922' : '1px solid #30363d',
            background: editMode ? 'rgba(210, 153, 34, 0.22)' : '#161b22',
            color: editMode ? '#d29922' : '#8b949e',
            whiteSpace: 'nowrap',
          }}
        >
          Edit Mode
        </button>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && submit()}
          placeholder="Ask your wiki..."
          style={{
            flex: 1, padding: '8px 12px', background: '#161b22',
            border: '1px solid #30363d', borderRadius: 6, color: '#e6edf3', fontSize: 13,
          }}
        />
        <button
          onClick={submit}
          disabled={loading}
          style={{
            padding: '8px 16px', background: '#238636', border: 'none',
            borderRadius: 6, color: '#fff',
            cursor: loading ? 'not-allowed' : 'pointer', fontSize: 13, flexShrink: 0,
          }}
        >
          Send
        </button>
      </div>
    </div>
  )
}
