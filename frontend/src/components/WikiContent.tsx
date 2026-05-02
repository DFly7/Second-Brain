import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import { usePage, useUpdatePage } from '../hooks/useWiki'

interface WikiContentProps {
  selectedSlug: string | null
  onNavigate: (slug: string) => void
}

function isExternalHref(href: string): boolean {
  return /^(https?:\/\/|mailto:|tel:)/i.test(href)
}

function hrefToSlug(href: string): string | null {
  if (!href) return null
  if (href.startsWith('wiki://')) return href.slice(7)
  if (href.startsWith('#')) return null
  if (isExternalHref(href)) return null
  // treat relative links as wiki slugs (e.g. sources/foo, meta/index, etc.)
  return href.replace(/^\.\//, '')
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
              ul({ children }) {
                return <ul style={{ margin: '6px 0', paddingLeft: 22 }}>{children}</ul>
              },
              ol({ children }) {
                return <ol style={{ margin: '6px 0', paddingLeft: 22 }}>{children}</ol>
              },
              p({ children }) {
                return <p style={{ margin: '6px 0' }}>{children}</p>
              },
            }}
          >
            {(page.body_md || '').replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, slug, display) =>
              `[${display ?? slug}](wiki://${slug})`
            )}
          </ReactMarkdown>
        </div>
      )}
    </div>
  )
}
