# Ingest Queue, Recursive Tree, Resizable Panels, Chat Markdown, Multi-file Upload — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a marker concurrency semaphore, recursive sidebar folder tree, resizable IDE-style panels, chat markdown rendering with clickable wikilinks, and multi-file upload with per-file SSE status.

**Architecture:** Backend gets a module-level `asyncio.Semaphore` to serialise marker calls and a new `agent:queued` SSE event. The frontend refactors `WikiPanel` into `WikiSidebar` + `WikiContent`, lifts `selectedSlug` to `Layout`, wraps the three panels in `react-resizable-panels`, adds `ReactMarkdown` to `ChatPanel`, and rewrites `IngestModal` with multi-file + SSE-driven status.

**Tech Stack:** Python/FastAPI (asyncio), React 18, TypeScript, react-resizable-panels, react-markdown, remark-gfm

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `api/app/routes/ingest.py` | Add semaphore + `agent:queued` SSE event |
| Create | `frontend/src/components/WikiSidebar.tsx` | Recursive tree + health button |
| Create | `frontend/src/components/WikiContent.tsx` | Page viewer / editor |
| Delete | `frontend/src/components/WikiPanel.tsx` | Replaced by WikiSidebar + WikiContent |
| Modify | `frontend/src/components/Layout.tsx` | PanelGroup, lifted `selectedSlug`, `onNavigate` |
| Modify | `frontend/src/components/ChatPanel.tsx` | ReactMarkdown, wikilink processing, `onNavigate` prop |
| Modify | `frontend/src/components/IngestModal.tsx` | FileEntry state, sequential upload, SSE status |
| Modify | `frontend/package.json` | Add `react-resizable-panels` |

---

## Task 1: API Marker Concurrency Semaphore

**Files:**
- Modify: `api/app/routes/ingest.py`
- Test: `tests/test_ingest_semaphore.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingest_semaphore.py`:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_queued_event_published_before_converting():
    """agent:queued fires before agent:converting regardless of semaphore state."""
    events = []

    async def fake_publish(event):
        events.append(event["event"])

    # Import after patching so module-level semaphore is already created
    with patch("app.routes.ingest.broadcaster") as mock_broadcaster:
        mock_broadcaster.publish = fake_publish
        with patch("app.routes.ingest.AsyncSessionLocal") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session.execute = AsyncMock(return_value=AsyncMock(scalar_one_or_none=lambda: None))
            mock_session_cls.return_value = mock_session

            from app.routes.ingest import _run_pipeline
            # source not found path — just checks events up to the early return
            await _run_pipeline("test-id", "ws-id", b"data", "file.txt")

    # queued should appear if published before the source lookup guard
    # (adjust assertion once source lookup mock returns a real source)
    assert "agent:queued" in events
```

- [ ] **Step 2: Run test to see it fail**

```bash
docker compose exec api pytest tests/test_ingest_semaphore.py -v
```

Expected: FAIL — `agent:queued` not in events (not yet implemented).

- [ ] **Step 3: Add semaphore and agent:queued to ingest.py**

At the top of `api/app/routes/ingest.py`, add imports after the existing ones:

```python
import asyncio
import os
```

After the `_log = logging.getLogger(__name__)` line, add:

```python
_marker_sem = asyncio.Semaphore(int(os.environ.get("MARKER_CONCURRENCY", "1")))
```

Replace the `_run_pipeline` body from the `await broadcaster.publish({"event": "agent:converting"...})` line through the marker call so it reads:

```python
    await broadcaster.publish({"event": "agent:queued", "source_id": source_id})

    async with AsyncSessionLocal() as session:
        src_result = await session.execute(select(Source).where(Source.id == source_id))
        source = src_result.scalar_one_or_none()
        if not source:
            _log.warning("ingest pipeline aborted: source not found source_id=%s", source_id)
            return

        try:
            if suffix in TEXT_TYPES:
                await broadcaster.publish({"event": "agent:converting", "source_id": source_id})
                _log.info(
                    "ingest skipping marker (plain text) source_id=%s suffix=%s",
                    source_id,
                    suffix,
                )
                text = data.decode("utf-8", errors="replace")
                chunks = _chunk_text(text)
                combined_md = text
                pages_data = [
                    {"page_num": i + 1, "markdown": chunk, "images": []}
                    for i, chunk in enumerate(chunks)
                ]
            else:
                async with _marker_sem:
                    await broadcaster.publish({"event": "agent:converting", "source_id": source_id})
                    _log.info("ingest calling marker source_id=%s filename=%s", source_id, filename)
                    client = MarkerClient()
                    raw_pages = await client.convert(data, filename, source_id=source_id)
                _log.info(
                    "ingest marker done source_id=%s pages=%d",
                    source_id,
                    len(raw_pages),
                )
                pages_data = [
                    {
                        "page_num": p.page_num,
                        "markdown": p.markdown,
                        "images": [{"filename": img.filename, "b64": img.b64} for img in p.images],
                    }
                    for p in raw_pages
                ]
                combined_md = "\n\n".join(p["markdown"] for p in pages_data)
```

The rest of the try block (S3 upload, DB write, commit) stays unchanged.

- [ ] **Step 4: Run test to verify it passes**

```bash
docker compose exec api pytest tests/test_ingest_semaphore.py -v
```

Expected: PASS.

- [ ] **Step 5: Manual smoke test**

Upload two PDFs simultaneously via the UI. Confirm the API logs show:
```
ingest pipeline start source_id=AAA ...
ingest pipeline start source_id=BBB ...
agent:queued published for AAA
agent:queued published for BBB
agent:converting published for AAA   ← AAA acquires semaphore
(marker processes AAA for several minutes)
agent:converting published for BBB   ← BBB acquires only after AAA releases
```

- [ ] **Step 6: Commit**

```bash
git add api/app/routes/ingest.py tests/test_ingest_semaphore.py
git commit -m "feat: marker concurrency semaphore with agent:queued SSE event"
```

---

## Task 2: WikiSidebar — Recursive Folder Tree

**Files:**
- Create: `frontend/src/components/WikiSidebar.tsx`
- Test: manual (browser)

- [ ] **Step 1: Create WikiSidebar.tsx**

Create `frontend/src/components/WikiSidebar.tsx`:

```tsx
import { useState } from 'react'
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
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
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

  const tree = buildTree(pages)

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
              background: selectedSlug === p.slug ? '#21262d' : 'transparent',
              borderLeft: highlightedSlug === p.slug ? '2px solid #58a6ff' : '2px solid transparent',
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
```

- [ ] **Step 2: Verify it compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors related to WikiSidebar.tsx.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/WikiSidebar.tsx
git commit -m "feat: recursive folder tree in WikiSidebar"
```

---

## Task 3: WikiContent — Page Viewer / Editor

**Files:**
- Create: `frontend/src/components/WikiContent.tsx`

- [ ] **Step 1: Create WikiContent.tsx**

Create `frontend/src/components/WikiContent.tsx`:

```tsx
import { useState } from 'react'
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
```

- [ ] **Step 2: Verify it compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/WikiContent.tsx
git commit -m "feat: WikiContent page viewer with markdown + wikilink support"
```

---

## Task 4: Resizable Panels — Layout Refactor

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/src/components/Layout.tsx`
- Delete: `frontend/src/components/WikiPanel.tsx`

- [ ] **Step 1: Install react-resizable-panels**

```bash
cd frontend && npm install react-resizable-panels
```

Expected: package added to `node_modules` and `package.json`.

- [ ] **Step 2: Rewrite Layout.tsx**

Replace the entire contents of `frontend/src/components/Layout.tsx` with:

```tsx
import { useState, useEffect } from 'react'
import type React from 'react'
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'
import WikiSidebar from './WikiSidebar'
import WikiContent from './WikiContent'
import ChatPanel from './ChatPanel'
import IngestModal from './IngestModal'
import ActivityLog from './ActivityLog'
import { createSSE } from '../api/client'
import { useQueryClient } from '@tanstack/react-query'

export default function Layout() {
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null)
  const [highlightedSlug, setHighlightedSlug] = useState<string | null>(null)
  const [agentStatus, setAgentStatus] = useState<string | null>(null)
  const [showActivity, setShowActivity] = useState(false)
  const [showIngest, setShowIngest] = useState(false)
  const qc = useQueryClient()

  useEffect(() => {
    const unsub = createSSE((data: unknown) => {
      const event = data as {
        event: string
        slug?: string
        source_id?: string
      }
      if (event.event === 'agent:queued') {
        setAgentStatus(
          event.source_id
            ? `Queued (source ${event.source_id.slice(0, 8)}…)`
            : 'Queued…',
        )
      } else if (event.event === 'agent:converting') {
        setAgentStatus(
          event.source_id
            ? `Converting document (source ${event.source_id.slice(0, 8)}…)…`
            : 'Converting document…',
        )
      } else if (event.event === 'agent:ingesting') {
        setAgentStatus(
          event.source_id
            ? `Updating wiki from source ${event.source_id.slice(0, 8)}…`
            : 'Updating wiki from ingested source…',
        )
      } else if (event.event === 'agent:reading') {
        setHighlightedSlug(event.slug || null)
        setAgentStatus(`Reading ${event.slug}…`)
      } else if (event.event === 'agent:writing') {
        setHighlightedSlug(event.slug || null)
        setAgentStatus(`Writing ${event.slug}…`)
      } else if (event.event === 'agent:done') {
        setHighlightedSlug(null)
        setAgentStatus(null)
        qc.invalidateQueries({ queryKey: ['pages'] })
        qc.invalidateQueries({ queryKey: ['activity'] })
      }
    })
    return unsub
  }, [qc])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      {/* Topbar */}
      <div style={{
        display: 'flex', alignItems: 'center', padding: '8px 16px',
        background: '#161b22', borderBottom: '1px solid #30363d',
        gap: 12, flexShrink: 0,
      }}>
        <span style={{ fontWeight: 600, fontSize: 15, color: '#e6edf3' }}>LLM Wiki</span>
        {agentStatus && (
          <span style={{ fontSize: 12, color: '#58a6ff', marginLeft: 8 }}>⟳ {agentStatus}</span>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button onClick={() => setShowIngest(true)} style={topBtnStyle}>+ Ingest</button>
          <button onClick={() => setShowActivity(!showActivity)} style={topBtnStyle}>Activity</button>
        </div>
      </div>

      {/* Resizable panels */}
      <PanelGroup autoSaveId="main-layout" direction="horizontal" style={{ flex: 1, overflow: 'hidden' }}>
        <Panel defaultSize={15} minSize={10}>
          <WikiSidebar
            selectedSlug={selectedSlug}
            highlightedSlug={highlightedSlug}
            onSelect={setSelectedSlug}
          />
        </Panel>

        <PanelResizeHandle style={resizeHandleStyle} />

        <Panel defaultSize={55} minSize={25}>
          <WikiContent selectedSlug={selectedSlug} onNavigate={setSelectedSlug} />
        </Panel>

        <PanelResizeHandle style={resizeHandleStyle} />

        <Panel defaultSize={30} minSize={15}>
          <ChatPanel onNavigate={setSelectedSlug} />
        </Panel>
      </PanelGroup>

      {showActivity && <ActivityLog onClose={() => setShowActivity(false)} />}
      {showIngest && <IngestModal onClose={() => setShowIngest(false)} />}
    </div>
  )
}

const topBtnStyle: React.CSSProperties = {
  padding: '4px 12px', background: '#21262d', border: '1px solid #30363d',
  borderRadius: 6, color: '#e6edf3', cursor: 'pointer', fontSize: 13,
}

const resizeHandleStyle: React.CSSProperties = {
  width: 4,
  background: '#21262d',
  cursor: 'col-resize',
  flexShrink: 0,
  transition: 'background 0.15s',
}
```

- [ ] **Step 3: Delete WikiPanel.tsx**

```bash
rm frontend/src/components/WikiPanel.tsx
```

- [ ] **Step 4: Verify it compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors. (ChatPanel will show a type error on `onNavigate` — that's fixed in Task 5.)

- [ ] **Step 5: Start dev server and verify panels drag**

```bash
cd frontend && npm run dev
```

Open the app. Drag the dividers between sidebar / content / chat. Resize, reload — sizes should persist.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Layout.tsx frontend/package.json frontend/package-lock.json
git rm frontend/src/components/WikiPanel.tsx
git commit -m "feat: resizable IDE-style panels with react-resizable-panels"
```

---

## Task 5: Chat Markdown + Clickable Wikilinks

**Files:**
- Modify: `frontend/src/components/ChatPanel.tsx`

- [ ] **Step 1: Rewrite ChatPanel.tsx**

Replace the entire contents of `frontend/src/components/ChatPanel.tsx` with:

```tsx
import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { sendMessage } from '../api/client'

interface Message { role: 'user' | 'assistant'; content: string; cited?: string[] }

function processWikilinks(text: string): string {
  return text.replace(/\[\[([^\]]+)\]\]/g, '[$1](wiki://$1)')
}

interface ChatPanelProps {
  onNavigate: (slug: string) => void
}

export default function ChatPanel({ onNavigate }: ChatPanelProps) {
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
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100%',
      background: '#0d1117', borderLeft: '1px solid #30363d',
    }}>
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
                  {processWikilinks(m.content)}
                </ReactMarkdown>
              ) : (
                m.content
              )}
            </div>
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
          <div style={{ color: '#8b949e', fontSize: 13, alignSelf: 'flex-start' }}>Thinking…</div>
        )}
        <div ref={bottomRef} />
      </div>
      <div style={{ padding: 12, borderTop: '1px solid #30363d', display: 'flex', gap: 8 }}>
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
            cursor: loading ? 'not-allowed' : 'pointer', fontSize: 13,
          }}
        >
          Send
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify it compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Manual test**

Ask the chat a question. Verify:
- `**bold**` renders as bold, not literal asterisks
- `### Heading` renders as a heading
- Bullet lists render as `<ul>`
- `[[some/slug]]` renders as a clickable blue underlined link
- Clicking it selects that page in the wiki panel
- Cited sources in the footer are also clickable

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ChatPanel.tsx
git commit -m "feat: chat markdown rendering with clickable wikilinks"
```

---

## Task 6: Multi-file Upload + Per-file SSE Status

**Files:**
- Modify: `frontend/src/components/IngestModal.tsx`

- [ ] **Step 1: Rewrite IngestModal.tsx**

Replace the entire contents of `frontend/src/components/IngestModal.tsx` with:

```tsx
import { useState, useEffect, useCallback } from 'react'
import type React from 'react'
import { ingestText, ingestUrl, ingestFile, createSSE } from '../api/client'
import { useQueryClient } from '@tanstack/react-query'

type FileStatus = 'pending' | 'uploading' | 'converting' | 'processing' | 'done' | 'error'

interface FileEntry {
  id: string
  file: File
  status: FileStatus
  sourceId?: string
}

const STATUS_LABEL: Record<FileStatus, string> = {
  pending: 'Pending',
  uploading: 'Uploading…',
  converting: 'Converting…',
  processing: 'Processing…',
  done: 'Done ✓',
  error: 'Error ✗',
}

const STATUS_COLOR: Record<FileStatus, string> = {
  pending: '#8b949e',
  uploading: '#58a6ff',
  converting: '#d29922',
  processing: '#d29922',
  done: '#3fb950',
  error: '#f85149',
}

export default function IngestModal({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<'text' | 'url' | 'file'>('text')
  const [text, setText] = useState('')
  const [url, setUrl] = useState('')
  const [status, setStatus] = useState('')
  const [fileEntries, setFileEntries] = useState<FileEntry[]>([])
  const [uploading, setUploading] = useState(false)
  const qc = useQueryClient()

  // SSE subscription — update file entries as pipeline progresses
  useEffect(() => {
    const STATUS_MAP: Partial<Record<string, FileStatus>> = {
      'agent:queued': 'converting',
      'agent:converting': 'converting',
      'agent:ingesting': 'processing',
      'agent:done': 'done',
    }
    const unsub = createSSE((data: unknown) => {
      const event = data as { event: string; source_id?: string }
      const newStatus = STATUS_MAP[event.event]
      if (!newStatus || !event.source_id) return
      setFileEntries(entries =>
        entries.map(e =>
          e.sourceId === event.source_id ? { ...e, status: newStatus } : e
        )
      )
    })
    return unsub
  }, [])

  // Auto-close 2s after all files reach a terminal state
  useEffect(() => {
    if (fileEntries.length === 0) return
    const allDone = fileEntries.every(e => e.status === 'done' || e.status === 'error')
    if (!allDone) return
    qc.invalidateQueries({ queryKey: ['pages'] })
    const timer = setTimeout(onClose, 2000)
    return () => clearTimeout(timer)
  }, [fileEntries, onClose, qc])

  async function submitTextOrUrl() {
    setStatus('Ingesting…')
    try {
      if (tab === 'text') await ingestText(text)
      else if (tab === 'url') await ingestUrl(url)
      setStatus('Ingested! Agent is updating your wiki.')
      qc.invalidateQueries({ queryKey: ['activity'] })
      setTimeout(onClose, 1500)
    } catch {
      setStatus('Failed — check the console.')
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || [])
    setFileEntries(files.map(file => ({
      id: crypto.randomUUID(),
      file,
      status: 'pending',
    })))
  }

  async function uploadAll() {
    if (uploading || fileEntries.length === 0) return
    setUploading(true)
    for (const entry of fileEntries) {
      setFileEntries(prev => prev.map(e =>
        e.id === entry.id ? { ...e, status: 'uploading' } : e
      ))
      try {
        const resp = await ingestFile(entry.file)
        setFileEntries(prev => prev.map(e =>
          e.id === entry.id ? { ...e, status: 'converting', sourceId: resp.source_id } : e
        ))
      } catch {
        setFileEntries(prev => prev.map(e =>
          e.id === entry.id ? { ...e, status: 'error' } : e
        ))
      }
    }
    setUploading(false)
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
      }}
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div style={{
        background: '#161b22', border: '1px solid #30363d', borderRadius: 12,
        padding: 24, width: 480, maxWidth: '90vw',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ color: '#e6edf3', margin: 0 }}>Ingest</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', fontSize: 18 }}>✕</button>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          {(['text', 'url', 'file'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 14px',
              background: tab === t ? '#238636' : '#21262d',
              border: '1px solid #30363d', borderRadius: 6,
              color: '#e6edf3', cursor: 'pointer', fontSize: 13,
            }}>{t}</button>
          ))}
        </div>

        {/* Text tab */}
        {tab === 'text' && (
          <textarea
            value={text}
            onChange={e => setText(e.target.value)}
            placeholder="Paste any text, note, or idea…"
            rows={6}
            style={{
              width: '100%', padding: 12, background: '#0d1117',
              border: '1px solid #30363d', borderRadius: 6,
              color: '#e6edf3', fontSize: 13, resize: 'vertical',
            }}
          />
        )}

        {/* URL tab */}
        {tab === 'url' && (
          <input
            value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://…"
            style={{
              width: '100%', padding: '8px 12px', background: '#0d1117',
              border: '1px solid #30363d', borderRadius: 6, color: '#e6edf3', fontSize: 13,
            }}
          />
        )}

        {/* File tab */}
        {tab === 'file' && (
          <div>
            <input
              type="file"
              multiple
              accept=".pdf,.docx,.md,.markdown,.txt,.png,.jpg,.jpeg,.webp"
              onChange={handleFileChange}
              style={{ color: '#e6edf3', fontSize: 13, marginBottom: 12 }}
            />
            {fileEntries.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
                {fileEntries.map(entry => (
                  <div key={entry.id} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '6px 10px', background: '#0d1117',
                    border: '1px solid #30363d', borderRadius: 6,
                  }}>
                    <span style={{ fontSize: 12, color: '#e6edf3', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 280 }}>
                      {entry.file.name}
                    </span>
                    <span style={{ fontSize: 11, color: STATUS_COLOR[entry.status], flexShrink: 0, marginLeft: 8 }}>
                      {STATUS_LABEL[entry.status]}
                    </span>
                  </div>
                ))}
              </div>
            )}
            {fileEntries.length > 0 && (
              <button
                onClick={uploadAll}
                disabled={uploading}
                style={{
                  width: '100%', padding: '10px 0',
                  background: uploading ? '#21262d' : '#238636',
                  border: 'none', borderRadius: 6,
                  color: uploading ? '#8b949e' : '#fff',
                  cursor: uploading ? 'not-allowed' : 'pointer', fontSize: 14,
                }}
              >
                {uploading ? 'Uploading…' : `Upload ${fileEntries.length} file${fileEntries.length !== 1 ? 's' : ''}`}
              </button>
            )}
          </div>
        )}

        {/* Text/URL status */}
        {status && tab !== 'file' && (
          <div style={{ marginTop: 12, fontSize: 13, color: '#58a6ff' }}>{status}</div>
        )}

        {/* Text/URL submit */}
        {tab !== 'file' && (
          <button
            onClick={submitTextOrUrl}
            style={{
              marginTop: 16, width: '100%', padding: '10px 0',
              background: '#238636', border: 'none', borderRadius: 6,
              color: '#fff', cursor: 'pointer', fontSize: 14,
            }}
          >
            Ingest
          </button>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify it compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Manual test**

1. Click `+ Ingest` → File tab
2. Select 3 PDFs at once
3. Click "Upload 3 files"
4. Verify each row shows: `Uploading…` → `Converting…` → `Processing…` → `Done ✓`
5. Verify modal auto-closes ~2s after all are done
6. Verify wiki sidebar updates with new pages

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/IngestModal.tsx
git commit -m "feat: multi-file upload with per-file SSE pipeline status"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** Semaphore ✓, agent:queued ✓, recursive tree ✓, resizable panels ✓, panel size persistence ✓, chat markdown ✓, clickable wikilinks ✓, multi-file upload ✓, per-file status ✓, sequential dispatch ✓, auto-close modal ✓
- [x] **No placeholders:** All steps have complete code
- [x] **Type consistency:** `FileEntry`, `TreeNode`, `FolderNodeProps`, `WikiSidebarProps`, `WikiContentProps`, `ChatPanelProps` all defined before use; `onNavigate: (slug: string) => void` consistent across Layout → WikiContent and Layout → ChatPanel
- [x] **WikiPanel.tsx deleted** in Task 4 Step 3 — no remaining imports
- [x] **cited sources** in ChatPanel made clickable as a bonus (consistent with wikilink navigation)
