import { useState, useEffect } from 'react'
import { usePages } from '../hooks/useWiki'
import { runHealthCheck } from '../api/client'

interface Page { slug: string; title: string }

interface TreeNode {
  children: Record<string, TreeNode>
  pages: Page[]
}

function buildTree(pages: Page[]): TreeNode {
  const root: TreeNode = { children: {}, pages: [] }
  for (const page of pages) {
    const parts = page.slug.split('/')
    let node = root
    for (let i = 0; i < parts.length - 1; i++) {
      const seg = parts[i]
      if (!node.children[seg]) node.children[seg] = { children: {}, pages: [] }
      node = node.children[seg]
    }
    node.pages.push(page)
  }
  return root
}

function countPages(node: TreeNode): number {
  let n = node.pages.length
  for (const c of Object.values(node.children)) n += countPages(c)
  return n
}

const STORAGE_KEY = 'wiki_collapsed_folders'

function getCollapsed(): Record<string, boolean> {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') } catch { return {} }
}

function saveCollapsed(state: Record<string, boolean>) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)) } catch { /* storage unavailable */ }
}

interface FolderNodeProps {
  name: string
  node: TreeNode
  depth: number
  fullPath: string
  selectedSlug: string | null
  highlightedSlug: string | null
  collapsed: Record<string, boolean>
  onToggle: (path: string) => void
  onSelect: (slug: string) => void
}

function FolderNode({
  name, node, depth, fullPath,
  selectedSlug, highlightedSlug,
  collapsed, onToggle, onSelect,
}: FolderNodeProps) {
  const isMeta = name === 'meta'
  const isCollapsed = collapsed[fullPath]
  const indent = 16 + depth * 12

  const sortedChildren = Object.entries(node.children).sort(([a], [b]) => {
    if (a === 'meta') return 1
    if (b === 'meta') return -1
    return a.localeCompare(b)
  })

  return (
    <div>
      <div
        onClick={() => onToggle(fullPath)}
        style={{
          padding: `4px 16px 4px ${indent}px`,
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
        <span>{name}/</span>
        <span style={{ marginLeft: 'auto', opacity: 0.6 }}>{countPages(node)}</span>
      </div>
      {!isCollapsed && (
        <>
          {node.pages.map((p) => {
            const leafName = p.slug.split('/').pop() || p.slug
            return (
              <div
                key={p.slug}
                onClick={() => onSelect(p.slug)}
                style={{
                  padding: `5px 16px 5px ${indent + 12}px`,
                  cursor: 'pointer',
                  fontSize: 13,
                  color: selectedSlug === p.slug ? '#e6edf3' : isMeta ? '#484f58' : '#8b949e',
                  background: selectedSlug === p.slug ? '#1c2128' : 'transparent',
                  borderLeft: highlightedSlug === p.slug ? '2px solid #58a6ff' : selectedSlug === p.slug ? '2px solid #388bfd' : '2px solid transparent',
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
          {sortedChildren.map(([childName, childNode]) => (
            <FolderNode
              key={childName}
              name={childName}
              node={childNode}
              depth={depth + 1}
              fullPath={`${fullPath}${childName}/`}
              selectedSlug={selectedSlug}
              highlightedSlug={highlightedSlug}
              collapsed={collapsed}
              onToggle={onToggle}
              onSelect={onSelect}
            />
          ))}
        </>
      )}
    </div>
  )
}

interface WikiSidebarProps {
  selectedSlug: string | null
  highlightedSlug: string | null
  onSelect: (slug: string) => void
}

export default function WikiSidebar({ selectedSlug, highlightedSlug, onSelect }: WikiSidebarProps) {
  const { data: pages = [] } = usePages()
  const [collapsed, setCollapsedState] = useState<Record<string, boolean>>(getCollapsed)
  const [healthRunning, setHealthRunning] = useState(false)

  // Auto-expand ancestor folders when the selected page changes (e.g. navigating via a link)
  useEffect(() => {
    if (!selectedSlug) return
    const parts = selectedSlug.split('/')
    if (parts.length <= 1) return
    const ancestors = parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join('/') + '/')
    if (!ancestors.some(f => collapsed[f])) return
    const next = { ...collapsed }
    for (const f of ancestors) delete next[f]
    setCollapsedState(next)
    saveCollapsed(next)
  }, [selectedSlug]) // eslint-disable-line react-hooks/exhaustive-deps

  function toggleFolder(path: string) {
    const next = { ...collapsed, [path]: !collapsed[path] }
    setCollapsedState(next)
    saveCollapsed(next)
  }

  async function handleHealthRun() {
    if (healthRunning) return
    setHealthRunning(true)
    try { await runHealthCheck() } finally {
      setTimeout(() => setHealthRunning(false), 3000)
    }
  }

  const tree = buildTree(Array.isArray(pages) ? pages : [])

  const sortedRootFolders = Object.entries(tree.children).sort(([a], [b]) => {
    if (a === 'meta') return 1
    if (b === 'meta') return -1
    return a.localeCompare(b)
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#161b22', overflowY: 'auto' }}>
      <div style={{ flex: 1 }}>
        <div style={{ padding: '12px 16px 12px', fontSize: 11, color: '#8b949e', textTransform: 'uppercase', letterSpacing: 1 }}>
          Pages
        </div>
        {tree.pages.map((p) => (
          <div
            key={p.slug}
            onClick={() => onSelect(p.slug)}
            style={{
              padding: '5px 16px 5px 16px',
              cursor: 'pointer',
              fontSize: 13,
              color: selectedSlug === p.slug ? '#e6edf3' : '#8b949e',
              background: selectedSlug === p.slug ? '#1c2128' : 'transparent',
              borderLeft: highlightedSlug === p.slug ? '2px solid #58a6ff' : selectedSlug === p.slug ? '2px solid #388bfd' : '2px solid transparent',
              transition: 'all 0.15s',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
            title={p.title}
          >
            {p.slug}
          </div>
        ))}
        {sortedRootFolders.map(([name, node]) => (
          <FolderNode
            key={name}
            name={name}
            node={node}
            depth={0}
            fullPath={`${name}/`}
            selectedSlug={selectedSlug}
            highlightedSlug={highlightedSlug}
            collapsed={collapsed}
            onToggle={toggleFolder}
            onSelect={onSelect}
          />
        ))}
      </div>
      <div style={{ padding: '12px 16px', borderTop: '1px solid #21262d', flexShrink: 0 }}>
        <button
          onClick={handleHealthRun}
          disabled={healthRunning}
          style={{
            width: '100%', padding: '6px 0',
            background: healthRunning ? '#21262d' : '#161b22',
            border: '1px solid #30363d', borderRadius: 6,
            color: healthRunning ? '#484f58' : '#6e7681',
            fontSize: 11, cursor: healthRunning ? 'default' : 'pointer', letterSpacing: 0.5,
          }}
        >
          {healthRunning ? 'running health check…' : '⚕ health check'}
        </button>
      </div>
    </div>
  )
}
