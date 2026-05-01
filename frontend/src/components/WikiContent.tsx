import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { usePage, useUpdatePage } from '../hooks/useWiki'

interface WikiContentProps {
  selectedSlug: string | null
  onNavigate: (slug: string) => void
}

export default function WikiContent({ selectedSlug, onNavigate }: WikiContentProps) {
  const [editing, setEditing] = useState(false)
  const [editBody, setEditBody] = useState('')
  const { data: page } = usePage(selectedSlug)
  const updatePage = useUpdatePage()

  useEffect(() => {
    setEditing(false)
  }, [selectedSlug])

  function startEdit() {
    setEditBody(page?.body_md || '')
    setEditing(true)
  }

  function saveEdit() {
    if (!selectedSlug) return
    updatePage.mutate({ slug: selectedSlug, body_md: editBody })
    setEditing(false)
  }

  if (!page) {
    return (
      <div style={{ flex: 1, overflowY: 'auto', padding: 24, color: '#8b949e', marginTop: 40, textAlign: 'center' }}>
        Select a page to read it, or ingest your first source.
      </div>
    )
  }

  return (
    <div style={{ height: '100%', overflowY: 'auto', padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, color: '#e6edf3' }}>{page.title}</h1>
        <button
          onClick={editing ? saveEdit : startEdit}
          style={{
            padding: '4px 14px',
            background: editing ? '#238636' : '#21262d',
            border: '1px solid #30363d', borderRadius: 6,
            color: '#e6edf3', cursor: 'pointer', fontSize: 13,
          }}
        >
          {editing ? 'Save' : 'Edit'}
        </button>
      </div>
      {editing ? (
        <textarea
          value={editBody}
          onChange={e => setEditBody(e.target.value)}
          style={{
            width: '100%', minHeight: 400, background: '#0d1117',
            border: '1px solid #30363d', borderRadius: 6,
            color: '#e6edf3', padding: 16, fontFamily: 'monospace',
            fontSize: 13, resize: 'vertical',
          }}
        />
      ) : (
        <div style={{ lineHeight: 1.7, fontSize: 14 }}>
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a({ href, children }) {
                if (href?.startsWith('wiki://')) {
                  const slug = href.slice(7)
                  return (
                    <span
                      onClick={() => onNavigate(slug)}
                      style={{ color: '#58a6ff', cursor: 'pointer', textDecoration: 'underline' }}
                    >
                      {children}
                    </span>
                  )
                }
                return <a href={href} target="_blank" rel="noreferrer">{children}</a>
              }
            }}
          >
            {(page.body_md || '').replace(/\[\[([^\]]+)\]\]/g, '[$1](wiki://$1)')}
          </ReactMarkdown>
        </div>
      )}
    </div>
  )
}
