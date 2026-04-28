import { useState, useRef, useEffect } from 'react'
import { sendMessage } from '../api/client'

interface Message { role: 'user' | 'assistant'; content: string; cited?: string[] }

export default function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [sessionId, setSessionId] = useState<string | undefined>()
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  async function submit() {
    if (!input.trim() || loading) return
    const text = input.trim()
    setInput('')
    setMessages(m => [...m, { role: 'user', content: text }])
    setLoading(true)
    try {
      const resp = await sendMessage(text, sessionId)
      setSessionId(resp.session_id)
      setMessages(m => [...m, { role: 'assistant', content: resp.answer, cited: resp.cited_pages }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#0d1117',
      borderLeft: '1px solid #30363d' }}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid #30363d', fontSize: 13,
        color: '#8b949e', background: '#161b22' }}>
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
              color: '#e6edf3', border: m.role === 'assistant' ? '1px solid #30363d' : 'none'
            }}>
              {m.content}
            </div>
            {m.cited && m.cited.length > 0 && (
              <div style={{ fontSize: 11, color: '#8b949e', marginTop: 4, paddingLeft: 4 }}>
                Sources: {m.cited.join(', ')}
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div style={{ color: '#8b949e', fontSize: 13, alignSelf: 'flex-start' }}>Thinking…</div>
        )}
        <div ref={bottomRef} />
      </div>
      <div style={{ padding: 12, borderTop: '1px solid #30363d', display: 'flex', gap: 8 }}>
        <input value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && submit()}
          placeholder="Ask your wiki..." style={{
            flex: 1, padding: '8px 12px', background: '#161b22', border: '1px solid #30363d',
            borderRadius: 6, color: '#e6edf3', fontSize: 13
          }} />
        <button onClick={submit} disabled={loading} style={{
          padding: '8px 16px', background: '#238636', border: 'none', borderRadius: 6,
          color: '#fff', cursor: loading ? 'not-allowed' : 'pointer', fontSize: 13
        }}>Send</button>
      </div>
    </div>
  )
}
