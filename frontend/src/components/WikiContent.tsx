import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
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
  const { data: page, isError, error } = usePage(selectedSlug)
  const updatePage = useUpdatePage()

  useEffect(() => {
    setEditing(false)
  }, [selectedSlug])

  useEffect(() => {
    const onEdit = () => startEdit()
    const onSave = () => saveEdit()
    window.addEventListener('wiki:edit', onEdit)
    window.addEventListener('wiki:save', onSave)
    return () => {
      window.removeEventListener('wiki:edit', onEdit)
      window.removeEventListener('wiki:save', onSave)
    }
  }) // eslint-disable-line react-hooks/exhaustive-deps

  function startEdit() {
    setEditBody(page?.body_md || '')
    setEditing(true)
  }

  function saveEdit() {
    if (!selectedSlug) return
    updatePage.mutate({ slug: selectedSlug, body_md: editBody })
    setEditing(false)
  }

  if (isError && (error as { status?: number })?.status === 404) {
    return (
      <div style={{ flex: 1, overflowY: 'auto', padding: 24, marginTop: 40, textAlign: 'center' }}>
        <div style={{ fontSize: 40, marginBottom: 16 }}>🗒️</div>
        <div style={{ color: '#e6edf3', fontSize: 16, fontWeight: 600, marginBottom: 8 }}>Page not found</div>
        <div style={{ color: '#8b949e', fontSize: 13 }}>
          This wiki page no longer exists — it may have been deleted.
        </div>
      </div>
    )
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
        <Button
          type="button"
          variant={editing ? 'default' : 'outline'}
          size="sm"
          onClick={editing ? saveEdit : startEdit}
        >
          {editing ? 'Save' : 'Edit'}
        </Button>
      </div>
      {editing ? (
        <Textarea
          value={editBody}
          onChange={e => setEditBody(e.target.value)}
          className="min-h-[400px] resize-y font-mono text-[13px]"
        />
      ) : (
        <article className="prose prose-invert prose-zinc max-w-none px-8 py-6">
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
                      className="cursor-pointer text-blue-400 underline"
                    >
                      {children}
                    </span>
                  )
                }
                return <a href={href} target="_blank" rel="noreferrer">{children}</a>
              },
            }}
          >
            {(page.body_md || '').replace(
              /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,
              (_: string, slug: string, display?: string) =>
                `[${display ?? slug}](wiki://${slug})`
            )}
          </ReactMarkdown>
        </article>
      )}
    </div>
  )
}
