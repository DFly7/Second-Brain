# Design: Ingest Queue, Recursive Tree, Multi-file Upload

Date: 2026-05-01

## Overview

Three coordinated improvements to the ingestion pipeline and UI:

1. **API-level marker concurrency semaphore** — prevents OOM from bulk uploads hitting marker simultaneously
2. **Recursive infinite-depth folder tree** — sidebar currently only handles 1 level of slug nesting
3. **Multi-file upload with per-file pipeline status** — modal currently accepts one file at a time with no per-file visibility

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

## Out of scope

- Persistent job queue (DB-backed) — overkill for local/self-hosted
- Upload cancellation
- Drag-and-drop file input
- Progress percentage within a single conversion (marker doesn't expose this)
