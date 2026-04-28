import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { usePages, usePage, useUpdatePage } from '../hooks/useWiki'

interface Props {
  highlightedSlug: string | null
}

export default function WikiPanel({ highlightedSlug }: Props) {
  const { data: pages = [] } = usePages()
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [editBody, setEditBody] = useState('')
  const { data: page } = usePage(selectedSlug)
  const updatePage = useUpdatePage()

  function startEdit() {
    setEditBody(page?.body_md || '')
    setEditing(true)
  }

  function saveEdit() {
    if (!selectedSlug) return
    updatePage.mutate({ slug: selectedSlug, body_md: editBody })
    setEditing(false)
  }

  return (
    <div style={{ display: 'flex', height: '100%', borderRight: '1px solid #30363d' }}>
      {/* Sidebar */}
      <div style={{ width: 220, overflowY: 'auto', background: '#161b22', padding: '12px 0' }}>
        <div style={{ padding: '0 16px 12px', fontSize: 11, color: '#8b949e', textTransform: 'uppercase', letterSpacing: 1 }}>
          Pages
        </div>
        {pages.map((p: { slug: string; title: string }) => (
          <div key={p.slug} onClick={() => { setSelectedSlug(p.slug); setEditing(false) }}
            style={{
              padding: '6px 16px', cursor: 'pointer', fontSize: 13,
              color: selectedSlug === p.slug ? '#e6edf3' : '#8b949e',
              background: selectedSlug === p.slug ? '#21262d' : 'transparent',
              borderLeft: highlightedSlug === p.slug ? '2px solid #58a6ff' : '2px solid transparent',
              transition: 'all 0.15s'
            }}>
            {p.title}
          </div>
        ))}
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 24 }}>
        {page ? (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h1 style={{ fontSize: 20, color: '#e6edf3' }}>{page.title}</h1>
              <button onClick={editing ? saveEdit : startEdit}
                style={{ padding: '4px 14px', background: editing ? '#238636' : '#21262d',
                  border: '1px solid #30363d', borderRadius: 6, color: '#e6edf3', cursor: 'pointer', fontSize: 13 }}>
                {editing ? 'Save' : 'Edit'}
              </button>
            </div>
            {editing ? (
              <textarea value={editBody} onChange={e => setEditBody(e.target.value)}
                style={{ width: '100%', minHeight: 400, background: '#0d1117', border: '1px solid #30363d',
                  borderRadius: 6, color: '#e6edf3', padding: 16, fontFamily: 'monospace', fontSize: 13,
                  resize: 'vertical' }} />
            ) : (
              <div style={{ lineHeight: 1.7, fontSize: 14 }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{page.body_md}</ReactMarkdown>
              </div>
            )}
          </>
        ) : (
          <div style={{ color: '#8b949e', marginTop: 40, textAlign: 'center' }}>
            Select a page to read it, or ingest your first source.
          </div>
        )}
      </div>
    </div>
  )
}
