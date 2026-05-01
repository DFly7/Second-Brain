# Design: Ingest Queue, Recursive Tree, Multi-file Upload, Resizable Panels, Chat Markdown

Date: 2026-05-01

## Overview

Five coordinated improvements to the ingestion pipeline and UI:

1. **API-level marker concurrency semaphore** — prevents OOM from bulk uploads hitting marker simultaneously
2. **Recursive infinite-depth folder tree** — sidebar currently only handles 1 level of slug nesting
3. **Multi-file upload with per-file pipeline status** — modal currently accepts one file at a time with no per-file visibility
4. **Resizable panels** — sidebar, wiki content, and chat panel are fixed-width; should be draggable like an IDE
5. **Chat markdown rendering with clickable wikilinks** — chat currently renders raw markdown text

---

## 1. API Semaphore (`api/app/routes/ingest.py`)

A module-level `asyncio.Semaphore` controls concurrent marker conversions:

```python
import os, asyncio
_marker_sem = asyncio.Semaphore(int(os.environ.get("MARKER_CONCURRENCY", "1")))
```

`_run_pipeline` publishes `agent:queued` via SSE immediately on entry, then acquires the semaphore before calling marker. Files uploaded while the semaphore is held await in their background task — no rejection, no timeout, natural queue.

**New SSE event:** `agent:queued` — `{ event: "agent:queued", source_id: str }`

**Env var:** `MARKER_CONCURRENCY` (default `"1"`) — allows tuning without code changes.

**Files changed:** `api/app/routes/ingest.py`

---

## 2. Recursive Folder Tree (`frontend/src/components/WikiPanel.tsx`)

### Data structure

Replace `getFolderGroups` with `buildTree`:

```ts
interface TreeNode {
  children: Record<string, TreeNode>
  pages: { slug: string; title: string }[]
}
```

`buildTree(pages)` splits each slug by `/`, walks the segment path creating nested `TreeNode` objects, and places the page at the leaf folder.

### Rendering

A recursive `FolderNode` component:

```ts
function FolderNode({ name, node, depth, fullPath, ...props })
```

- Renders a folder header (collapse toggle, name, page count)
- Renders `node.pages` as page items with `paddingLeft: 16 + depth * 12`
- Renders `Object.entries(node.children)` as nested `FolderNode` at `depth + 1`
- `meta/` sorted last at every level

### Collapse state

localStorage key `wiki_collapsed_folders`, keyed by full folder path (e.g. `ade/algorithms/`). Existing mechanism unchanged, just extended to arbitrary paths.

### Props threading

`selectedSlug`, `highlightedSlug`, `onSelect` passed down through `FolderNode` as props. No global state changes.

**Files changed:** `frontend/src/components/WikiPanel.tsx` (delete `getFolderGroups`, add `buildTree` + `FolderNode`)

---

## 3. Multi-file Upload + Per-file Status (`frontend/src/components/IngestModal.tsx`)

### State

Replace `status: string` with:

```ts
interface FileEntry {
  file: File
  status: 'pending' | 'uploading' | 'converting' | 'processing' | 'done' | 'error'
  sourceId?: string
}
const [fileEntries, setFileEntries] = useState<FileEntry[]>([])
```

### Upload flow

1. File input with `multiple` attribute populates `fileEntries` with `status: 'pending'`
2. "Upload all" button iterates entries sequentially:
   - Set entry to `uploading`
   - Call `ingestFile(file)` → get `source_id` back
   - Store `sourceId` on entry, set to `converting`
3. Sequential dispatch fills the API semaphore queue predictably

### SSE integration

`IngestModal` subscribes to SSE directly via its own `createSSE` call in a `useEffect` (runs while the modal is mounted). Events matched by `source_id` against `fileEntries`:

- `agent:queued` → `'converting'` (queued behind semaphore)
- `agent:converting` → `'converting'`
- `agent:ingesting` → `'processing'`
- `agent:done` → `'done'`
- pipeline error → `'error'`

### UX

- Modal stays open showing file list with status badges
- Close button always visible
- Auto-closes 2 seconds after last entry reaches `done` or `error`
- Old single-file `handleFile` replaced entirely

**Files changed:** `frontend/src/components/IngestModal.tsx` only — Layout.tsx unchanged

---

## SSE event summary

| Event | Payload | Meaning |
|---|---|---|
| `agent:queued` | `source_id` | File accepted, waiting for marker slot |
| `agent:converting` | `source_id` | Marker actively converting |
| `agent:ingesting` | `source_id` | Ingest agent running |
| `agent:done` | `source_id` | Pipeline complete |

---

## 4. Resizable Panels (`frontend/src/components/Layout.tsx`)

### Library

Use `react-resizable-panels` — handles drag, keyboard accessibility, min/max constraints, and persistence. Install: `npm install react-resizable-panels`.

### Layout

Replace the current fixed-width flex layout with a `<PanelGroup direction="horizontal">` containing three `<Panel>` components separated by `<PanelResizeHandle>`:

| Panel | Default size | Min size |
|---|---|---|
| Sidebar (WikiPanel tree) | 15% | 10% |
| Wiki content | 55% | 25% |
| Chat | 30% | 15% |

`<PanelResizeHandle>` renders as a 4px divider with a hover highlight (`#58a6ff` to match the theme).

### Persistence

`<PanelGroup id="main-layout">` — `react-resizable-panels` uses the `id` to auto-persist sizes to localStorage. No manual persistence code needed.

### WikiPanel split

`WikiPanel` currently renders both the sidebar tree and the content area as a flex row internally. To make the sidebar independently resizable, the tree and content need to be separate panels in the top-level `PanelGroup`. This means:

- `WikiPanel` is split into `WikiSidebar` (tree + health button) and `WikiContent` (page viewer/editor)
- `Layout` renders: `<Panel><WikiSidebar /></Panel> | <Panel><WikiContent /></Panel> | <Panel><ChatPanel /></Panel>`
- `selectedSlug` state lifts from `WikiPanel` to `Layout` and is passed to both `WikiSidebar` and `WikiContent` as props

**Files changed:** `frontend/src/components/Layout.tsx`, `frontend/src/components/WikiPanel.tsx` (split into `WikiSidebar` + `WikiContent`), `package.json`

---

## 5. Chat Markdown + Clickable Wikilinks (`frontend/src/components/ChatPanel.tsx`)

### Markdown rendering

Add `react-markdown` + `remark-gfm` to `ChatPanel` (already installed — used in `WikiPanel`). Wrap each assistant message body in `<ReactMarkdown remarkPlugins={[remarkGfm]}>`.

### Wikilink rendering

`[[slug]]` is not standard markdown. Pre-process each message string before passing to ReactMarkdown:

```ts
const processWikilinks = (text: string) =>
  text.replace(/\[\[([^\]]+)\]\]/g, '[$1](wiki://$1)')
```

Then in ReactMarkdown's `components` prop, intercept links with `wiki://` protocol:

```ts
components={{
  a({ href, children }) {
    if (href?.startsWith('wiki://')) {
      const slug = href.slice(7)
      return <span onClick={() => onNavigate(slug)} style={{ color: '#58a6ff', cursor: 'pointer', textDecoration: 'underline' }}>{children}</span>
    }
    return <a href={href} target="_blank" rel="noreferrer">{children}</a>
  }
}}
```

### Navigation callback

`onNavigate(slug)` sets `selectedSlug` in Layout (lifted as part of the panel split in section 4) and scrolls/highlights the wiki panel to that page. `ChatPanel` receives `onNavigate: (slug: string) => void` as a prop.

**Files changed:** `frontend/src/components/ChatPanel.tsx`, `frontend/src/components/Layout.tsx`

---

## SSE event summary

| Event | Payload | Meaning |
|---|---|---|
| `agent:queued` | `source_id` | File accepted, waiting for marker slot |
| `agent:converting` | `source_id` | Marker actively converting |
| `agent:ingesting` | `source_id` | Ingest agent running |
| `agent:done` | `source_id` | Pipeline complete |

---

## Out of scope

- Persistent job queue (DB-backed) — overkill for local/self-hosted
- Upload cancellation
- Drag-and-drop file input
- Progress percentage within a single conversion (marker doesn't expose this)
- Panel collapse buttons (drag to minimum is sufficient)
