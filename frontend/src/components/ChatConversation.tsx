import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'

export interface Message { role: 'user' | 'assistant'; content: string; cited?: string[] }

interface ChatConversationProps {
  messages: Message[]
  loading: boolean
  activeSseEvent: { event: string; slug?: string } | null
  editMode: boolean
  onSubmit: (text: string) => void
  onNavigate: (slug: string) => void
  onEditModeToggle: () => void
}

function processWikilinks(text: string): string {
  return text.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, slug, display) =>
    `[${display ?? slug}](wiki://${slug})`
  )
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

function sseStatusLabel(active: { event: string; slug?: string } | null): string {
  if (!active) return 'Thinking…'
  if (active.event === 'agent:reading') return active.slug ? `⟳ Reading ${active.slug}…` : '⟳ Reading…'
  if (active.event === 'agent:writing') return active.slug ? `⟳ Writing ${active.slug}…` : '⟳ Writing…'
  return 'Thinking…'
}

function sseStatusAnimKey(active: { event: string; slug?: string } | null): string {
  if (!active) return 'thinking'
  return active.slug ?? active.event
}

export default function ChatConversation({
  messages,
  loading,
  activeSseEvent,
  editMode,
  onSubmit,
  onNavigate,
  onEditModeToggle,
}: ChatConversationProps) {
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  function handleSubmit() {
    if (!input.trim() || loading) return
    const text = input.trim()
    setInput('')
    onSubmit(text)
  }

  return (
    <>
      <style>{`
        @keyframes fadeSlide {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
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
                  remarkPlugins={[remarkGfm, remarkMath]}
                  rehypePlugins={[rehypeKatex]}
                  urlTransform={(url) => url}
                  components={{
                    a({ href, children }) {
                      const slug = href ? hrefToSlug(href) : null
                      if (href && slug) {
                        return (
                          <span
                            role="link"
                            tabIndex={0}
                            onClick={() => onNavigate(slug)}
                            onKeyDown={(e) => e.key === 'Enter' && onNavigate(slug)}
                            style={{ color: '#58a6ff', cursor: 'pointer', textDecoration: 'underline' }}
                          >
                            {children}
                          </span>
                        )
                      }
                      return <a href={href} target="_blank" rel="noreferrer">{children}</a>
                    },
                    ul({ children }) { return <ul style={{ margin: '4px 0', paddingLeft: 20 }}>{children}</ul> },
                    ol({ children }) { return <ol style={{ margin: '4px 0', paddingLeft: 20 }}>{children}</ol> },
                    p({ children }) { return <p style={{ margin: '4px 0' }}>{children}</p> },
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
          <div style={{
            alignSelf: 'flex-start', padding: '8px 12px', borderRadius: 8,
            fontSize: 13, lineHeight: 1.6, background: '#21262d',
            color: '#8b949e', border: '1px solid #30363d',
          }}>
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
        padding: 12, borderTop: '1px solid #30363d',
        display: 'flex', alignItems: 'center', gap: 8,
        ...(editMode ? { boxShadow: 'inset 0 0 0 1px #d29922', background: 'rgba(210, 153, 34, 0.06)' } : {}),
      }}>
        <button
          type="button"
          onClick={onEditModeToggle}
          title={editMode ? 'Switch to read-only query' : 'Allow the agent to edit wiki pages'}
          style={{
            padding: '8px 12px', borderRadius: 6, fontSize: 13, cursor: 'pointer', flexShrink: 0,
            border: editMode ? '1px solid #d29922' : '1px solid #30363d',
            background: editMode ? 'rgba(210, 153, 34, 0.22)' : '#161b22',
            color: editMode ? '#d29922' : '#8b949e', whiteSpace: 'nowrap',
          }}
        >
          Edit Mode
        </button>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleSubmit()}
          placeholder="Ask your wiki..."
          style={{
            flex: 1, padding: '8px 12px', background: '#161b22',
            border: '1px solid #30363d', borderRadius: 6, color: '#e6edf3', fontSize: 13,
          }}
        />
        <button
          onClick={handleSubmit}
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
    </>
  )
}
