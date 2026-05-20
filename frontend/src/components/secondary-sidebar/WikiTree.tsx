import { useState, useEffect, useMemo } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ChevronRight, FileText } from 'lucide-react'
import { cn } from '@/lib/utils'
import { usePages } from '@/hooks/useWiki'
import { runHealthCheck } from '@/api/client'
import { SecondarySidebar } from './SecondarySidebar'

interface Page {
  slug: string
  title: string
}

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

function sortFolderEntries(children: Record<string, TreeNode>): [string, TreeNode][] {
  return Object.entries(children).sort(([a], [b]) => {
    if (a === 'meta') return 1
    if (b === 'meta') return -1
    return a.localeCompare(b)
  })
}

function pageMatchesFilter(page: Page, filter: string): boolean {
  const q = filter.toLowerCase()
  return (
    page.title.toLowerCase().includes(q) ||
    page.slug.toLowerCase().includes(q)
  )
}

function filterTreeNode(node: TreeNode, filter: string): TreeNode | null {
  if (!filter) return node
  const pages = node.pages.filter((p) => pageMatchesFilter(p, filter))
  const children: Record<string, TreeNode> = {}
  for (const [name, child] of Object.entries(node.children)) {
    const filtered = filterTreeNode(child, filter)
    if (filtered && (filtered.pages.length > 0 || Object.keys(filtered.children).length > 0)) {
      children[name] = filtered
    }
  }
  if (pages.length === 0 && Object.keys(children).length === 0) return null
  return { pages, children }
}

const STORAGE_KEY = 'wiki_collapsed_folders'

function getCollapsed(): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
  } catch {
    return {}
  }
}

function saveCollapsed(state: Record<string, boolean>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    /* storage unavailable */
  }
}

function wikiPageHref(slug: string): string {
  return `/wiki?slug=${encodeURIComponent(slug)}`
}

function PageRow({
  page,
  depth,
  isMeta,
  activeSlug,
  highlightedSlug,
  onSelect,
}: {
  page: Page
  depth: number
  isMeta: boolean
  activeSlug: string | null
  highlightedSlug: string | null
  onSelect?: (slug: string) => void
}) {
  const leafName = page.slug.split('/').pop() || page.slug
  const isActive = activeSlug === page.slug
  const isHighlighted = highlightedSlug === page.slug

  const className = cn(
    'group flex h-7 w-full items-center gap-1 rounded-sm px-2 text-left text-[13px] hover:bg-muted hover:text-foreground',
    isMeta ? 'text-muted-foreground/60' : 'text-muted-foreground',
    isActive && 'bg-muted text-foreground',
    isHighlighted && 'ring-1 ring-primary/50',
    isActive && 'before:mr-1 before:h-4 before:w-0.5 before:rounded-r before:bg-primary',
  )
  const style = { paddingLeft: 8 + depth * 12 }

  if (onSelect) {
    return (
      <button
        type="button"
        title={page.title}
        onClick={() => onSelect(page.slug)}
        className={className}
        style={style}
      >
        <FileText className="h-3 w-3 shrink-0 text-muted-foreground/60" />
        <span className="truncate">{leafName}</span>
      </button>
    )
  }

  return (
    <Link
      to={wikiPageHref(page.slug)}
      title={page.title}
      className={className}
      style={style}
    >
      <FileText className="h-3 w-3 shrink-0 text-muted-foreground/60" />
      <span className="truncate">{leafName}</span>
    </Link>
  )
}

function FolderRow({
  name,
  node,
  depth,
  fullPath,
  isMeta,
  activeSlug,
  highlightedSlug,
  collapsed,
  onToggle,
  filter,
  onSelect,
}: {
  name: string
  node: TreeNode
  depth: number
  fullPath: string
  isMeta: boolean
  activeSlug: string | null
  highlightedSlug: string | null
  collapsed: Record<string, boolean>
  onToggle: (path: string) => void
  filter: string
  onSelect?: (slug: string) => void
}) {
  const isCollapsed = collapsed[fullPath]
  const sortedChildren = sortFolderEntries(node.children)

  return (
    <div>
      <button
        type="button"
        onClick={() => onToggle(fullPath)}
        className={cn(
          'flex h-7 w-full items-center gap-1 rounded-sm px-2 text-[11px] uppercase tracking-wide hover:bg-muted',
          isMeta ? 'text-muted-foreground/50' : 'text-muted-foreground/70',
        )}
        style={{ paddingLeft: 8 + depth * 12 }}
      >
        <ChevronRight
          className={cn('h-3 w-3 shrink-0 transition-transform', !isCollapsed && 'rotate-90')}
        />
        <span className="truncate">{name}/</span>
        <span className="ml-auto text-[10px] opacity-60">{countPages(node)}</span>
      </button>
      {!isCollapsed && (
        <>
          {node.pages.map((p) => (
            <PageRow
              key={p.slug}
              page={p}
              depth={depth + 1}
              isMeta={isMeta || name === 'meta'}
              activeSlug={activeSlug}
              highlightedSlug={highlightedSlug}
              onSelect={onSelect}
            />
          ))}
          {sortedChildren.map(([childName, childNode]) => (
            <FolderRow
              key={childName}
              name={childName}
              node={childNode}
              depth={depth + 1}
              fullPath={`${fullPath}${childName}/`}
              isMeta={isMeta || name === 'meta'}
              activeSlug={activeSlug}
              highlightedSlug={highlightedSlug}
              collapsed={collapsed}
              onToggle={onToggle}
              filter={filter}
              onSelect={onSelect}
            />
          ))}
        </>
      )}
    </div>
  )
}

export function WikiTree({
  selectedSlug: selectedSlugProp,
  highlightedSlug = null,
  onSelect,
}: {
  selectedSlug?: string | null
  highlightedSlug?: string | null
  onSelect?: (slug: string) => void
} = {}) {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { data: pages = [] } = usePages()
  const [filter, setFilter] = useState('')
  const [collapsed, setCollapsedState] = useState<Record<string, boolean>>(getCollapsed)
  const [healthRunning, setHealthRunning] = useState(false)

  const activeSlug = selectedSlugProp ?? searchParams.get('slug')

  useEffect(() => {
    if (!activeSlug) return
    const parts = activeSlug.split('/')
    if (parts.length <= 1) return
    const ancestors = parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join('/') + '/')
    if (!ancestors.some((f) => collapsed[f])) return
    const next = { ...collapsed }
    for (const f of ancestors) delete next[f]
    setCollapsedState(next)
    saveCollapsed(next)
  }, [activeSlug]) // eslint-disable-line react-hooks/exhaustive-deps

  function toggleFolder(path: string) {
    const next = { ...collapsed, [path]: !collapsed[path] }
    setCollapsedState(next)
    saveCollapsed(next)
  }

  async function handleHealthRun() {
    if (healthRunning) return
    setHealthRunning(true)
    try {
      await runHealthCheck()
    } finally {
      setTimeout(() => setHealthRunning(false), 3000)
    }
  }

  const tree = useMemo(() => {
    const built = buildTree(Array.isArray(pages) ? pages : [])
    return filter ? filterTreeNode(built, filter) : built
  }, [pages, filter])

  const sortedRootFolders = tree ? sortFolderEntries(tree.children) : []

  return (
    <SecondarySidebar
      title="Wiki"
      primaryAction="New"
      onPrimaryAction={() => navigate('/wiki/new')}
      search={filter}
      onSearchChange={setFilter}
    >
      <div className="p-1">
        {tree?.pages.map((p) => (
          <PageRow
            key={p.slug}
            page={p}
            depth={0}
            isMeta={false}
            activeSlug={activeSlug}
            highlightedSlug={highlightedSlug}
            onSelect={onSelect}
          />
        ))}
        {sortedRootFolders.map(([name, node]) => (
          <FolderRow
            key={name}
            name={name}
            node={node}
            depth={0}
            fullPath={`${name}/`}
            isMeta={name === 'meta'}
            activeSlug={activeSlug}
            highlightedSlug={highlightedSlug}
            collapsed={collapsed}
            onToggle={toggleFolder}
            filter={filter}
            onSelect={onSelect}
          />
        ))}
      </div>
      <div className="shrink-0 border-t border-border p-2">
        <button
          type="button"
          onClick={handleHealthRun}
          disabled={healthRunning}
          className={cn(
            'w-full rounded-md border border-border px-2 py-1.5 text-[11px] tracking-wide',
            healthRunning
              ? 'cursor-default text-muted-foreground/50'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground',
          )}
        >
          {healthRunning ? 'running health check…' : '⚕ health check'}
        </button>
      </div>
    </SecondarySidebar>
  )
}
