import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { usePages, usePage, useUpdatePage } from '../hooks/useWiki'
import { runHealthCheck } from '../api/client'

interface Props {
  highlightedSlug: string | null
}

function getFolderGroups(pages: { slug: string; title: string }[]) {
  const groups: Record<string, { slug: string; title: string }[]> = {}
  for (const page of pages) {
    const parts = page.slug.split('/')
    const folder = parts.length > 1 ? parts[0] + '/' : 'misc/'
    if (!groups[folder]) groups[folder] = []
    groups[folder].push(page)
  }
  // Sort: meta/ last, everything else alphabetical
  return Object.entries(groups).sort(([a], [b]) => {
    if (a === 'meta/') return 1
    if (b === 'meta/') return -1
    return a.localeCompare(b)
  })
}

const STORAGE_KEY = 'wiki_collapsed_folders'

function getCollapsed(): Record<string, boolean> {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') } catch { return {} }
}

function setCollapsed(state: Record<string, boolean>) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
}

export default function WikiPanel({ highlightedSlug }: Props) {
  const { data: pages = [] } = usePages()
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [editBody, setEditBody] = useState('')
  const [collapsed, setCollapsedState] = useState<Record<string, boolean>>(getCollapsed)
  const [healthRunning, setHealthRunning] = useState(false)
  const { data: page } = usePage(selectedSlug)
  const updatePage = useUpdatePage()

  function toggleFolder(folder: string) {
    const next = { ...collapsed, [folder]: !collapsed[folder] }
    setCollapsedState(next)
    setCollapsed(next)
  }

  function startEdit() {
    setEditBody(page?.body_md || '')
    setEditing(true)
  }

  function saveEdit() {
    if (!selectedSlug) return
    updatePage.mutate({ slug: selectedSlug, body_md: editBody })
    setEditing(false)
  }

  async function handleHealthRun() {
    if (healthRunning) return
    setHealthRunning(true)
    try { await runHealthCheck() } finally {
      setTimeout(() => setHealthRunning(false), 3000)
    }
  }

  const folderGroups = getFolderGroups(pages)

  return (
    <div style={{ display: 'flex', height: '100%', borderRight: '1px solid #30363d' }}>
      {/* Sidebar */}
      <div style={{ width: 220, overflowY: 'auto', background: '#161b22', padding: '12px 0', display: 'flex', flexDirection: 'column' }}>
        <div style={{ flex: 1 }}>
          <div style={{ padding: '0 16px 12px', fontSize: 11, color: '#8b949e', textTransform: 'uppercase', letterSpacing: 1 }}>
            Pages
          </div>
          {folderGroups.map(([folder, folderPages]) => {
            const isMeta = folder === 'meta/'
            const isCollapsed = collapsed[folder]
            return (
              <div key={folder}>
                {/* Folder header */}
                <div
                  onClick={() => toggleFolder(folder)}
                  style={{
                    padding: '4px 16px',
                    cursor: 'pointer',
                    fontSize: 11,
                    color: isMeta ? '#484f58' : '#6e7681',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                    userSelect: 'none',
                    letterSpacing: 0.5,
                  }}
                >
                  <span style={{ fontSize: 9 }}>{isCollapsed ? '▶' : '▼'}</span>
                  <span>{folder}</span>
                  <span style={{ marginLeft: 'auto', opacity: 0.6 }}>{folderPages.length}</span>
                </div>
                {/* Pages in folder */}
                {!isCollapsed && folderPages.map((p) => {
                  const leafName = p.slug.includes('/') ? p.slug.split('/').slice(1).join('/') : p.slug
                  return (
                    <div
                      key={p.slug}
                      onClick={() => { setSelectedSlug(p.slug); setEditing(false) }}
                      style={{
                        padding: '5px 16px 5px 28px',
                        cursor: 'pointer',
                        fontSize: 13,
                        color: selectedSlug === p.slug ? '#e6edf3' : isMeta ? '#484f58' : '#8b949e',
                        background: selectedSlug === p.slug ? '#21262d' : 'transparent',
                        borderLeft: highlightedSlug === p.slug ? '2px solid #58a6ff' : '2px solid transparent',
                        transition: 'all 0.15s',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                      title={p.title}
                    >
                      {leafName}
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>

        {/* Health run button */}
        <div style={{ padding: '12px 16px', borderTop: '1px solid #21262d' }}>
          <button
            onClick={handleHealthRun}
            disabled={healthRunning}
            style={{
              width: '100%',
              padding: '6px 0',
              background: healthRunning ? '#21262d' : '#161b22',
              border: '1px solid #30363d',
              borderRadius: 6,
              color: healthRunning ? '#484f58' : '#6e7681',
              fontSize: 11,
              cursor: healthRunning ? 'default' : 'pointer',
              letterSpacing: 0.5,
            }}
          >
            {healthRunning ? 'running health check…' : '⚕ health check'}
          </button>
        </div>
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
