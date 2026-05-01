# Ingest Modal Overflow + Persistent Queue Panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure multi-file ingest never pushes the Upload/Start button off-screen, and add a reopenable “Queue” tab (persisted in localStorage) showing queued/in-progress/done ingest items.

**Architecture:** Introduce a small queue store module (`ingestQueue.ts`) with a reducer + localStorage hydrate/persist. `Layout.tsx` owns the queue state and a single SSE subscription that updates both the topbar status and the queue store. The right drawer (`ActivityLog`) becomes tabbed: `Activity | Queue`. `IngestModal` writes to the shared queue store and uses a scroll region + fixed footer actions.

**Tech Stack:** React 18, TypeScript, Vite, SSE (`createSSE`), localStorage; Vitest for small unit tests (new dev dependency).

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `frontend/package.json` | Add `vitest` + `test` script |
| Create | `frontend/src/state/ingestQueue.ts` | Queue types, reducer, localStorage hydrate/persist helpers |
| Create | `frontend/src/state/ingestQueue.test.ts` | Unit tests for reducer + persistence filtering |
| Modify | `frontend/src/components/Layout.tsx` | Own queue state; single SSE subscription updates queue; pass queue props |
| Modify | `frontend/src/components/ActivityLog.tsx` | Tabs: Activity + Queue; render queue items |
| Modify | `frontend/src/components/IngestModal.tsx` | Scroll-safe layout; write/read queue store instead of isolated modal state |

---

### Task 1: Add Vitest for small unit tests

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Add `vitest` and a `test` script**

Update `frontend/package.json`:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "test": "vitest"
  },
  "devDependencies": {
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.3",
    "vite": "^5.4.2",
    "vitest": "^2.1.8"
  }
}
```

- [ ] **Step 2: Install dependencies**

Run:

```bash
cd frontend && npm install
```

Expected: installs `vitest` and updates `package-lock.json`.

- [ ] **Step 3: Smoke-run Vitest**

Run:

```bash
cd frontend && npm test -- --run
```

Expected: exits 0 (no tests yet, or “No test files found” depending on defaults).

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "test: add vitest for frontend unit tests"
```

---

### Task 2: Implement the ingest queue store (pure + testable)

**Files:**
- Create: `frontend/src/state/ingestQueue.ts`
- Test: `frontend/src/state/ingestQueue.test.ts`

- [ ] **Step 1: Create the queue store module**

Create `frontend/src/state/ingestQueue.ts`:

```ts
export type QueueStatus =
  | 'pending'
  | 'uploading'
  | 'queued'
  | 'converting'
  | 'processing'
  | 'done'
  | 'error'

export interface QueueItem {
  id: string
  fileName: string
  fileSize: number
  createdAt: string // ISO
  status: QueueStatus
  sourceId?: string
  error?: string
}

export interface QueueState {
  items: QueueItem[]
}

export const INGEST_QUEUE_STORAGE_KEY = 'ingest_queue_v1'
export const INGEST_QUEUE_MAX_ITEMS = 200
export const INGEST_QUEUE_TTL_MS = 24 * 60 * 60 * 1000

type Action =
  | { type: 'upsert_many'; items: QueueItem[] }
  | { type: 'patch_by_id'; id: string; patch: Partial<QueueItem> }
  | { type: 'patch_by_source'; sourceId: string; patch: Partial<QueueItem> }
  | { type: 'prune'; nowMs: number }
  | { type: 'clear' }

function clampItems(items: QueueItem[]): QueueItem[] {
  if (items.length <= INGEST_QUEUE_MAX_ITEMS) return items
  // newest first by createdAt (ISO sortable)
  const sorted = [...items].sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1))
  return sorted.slice(0, INGEST_QUEUE_MAX_ITEMS)
}

export function reduceQueue(state: QueueState, action: Action): QueueState {
  if (action.type === 'clear') return { items: [] }

  if (action.type === 'upsert_many') {
    const byId = new Map(state.items.map(i => [i.id, i] as const))
    for (const item of action.items) byId.set(item.id, { ...byId.get(item.id), ...item })
    return { items: clampItems(Array.from(byId.values())) }
  }

  if (action.type === 'patch_by_id') {
    return {
      items: state.items.map(i => (i.id === action.id ? { ...i, ...action.patch } : i)),
    }
  }

  if (action.type === 'patch_by_source') {
    return {
      items: state.items.map(i =>
        i.sourceId === action.sourceId ? { ...i, ...action.patch } : i
      ),
    }
  }

  if (action.type === 'prune') {
    const cutoff = action.nowMs - INGEST_QUEUE_TTL_MS
    const keep = state.items.filter(i => {
      const t = Date.parse(i.createdAt)
      const expired = Number.isFinite(t) && t < cutoff
      const terminal = i.status === 'done' || i.status === 'error'
      return !(terminal && expired)
    })
    return { items: clampItems(keep) }
  }

  return state
}

export function loadQueueState(storage: Storage): QueueState {
  try {
    const raw = storage.getItem(INGEST_QUEUE_STORAGE_KEY)
    if (!raw) return { items: [] }
    const parsed = JSON.parse(raw) as QueueState
    if (!parsed || !Array.isArray(parsed.items)) return { items: [] }
    // minimal sanitization
    return { items: clampItems(parsed.items.filter(Boolean)) }
  } catch {
    return { items: [] }
  }
}

export function saveQueueState(storage: Storage, state: QueueState) {
  storage.setItem(INGEST_QUEUE_STORAGE_KEY, JSON.stringify(state))
}
```

- [ ] **Step 2: Write failing unit tests for reducer behavior**

Create `frontend/src/state/ingestQueue.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { reduceQueue, type QueueState } from './ingestQueue'

function mkState(status: 'done' | 'queued', createdAt: string): QueueState {
  return {
    items: [
      {
        id: 'a',
        fileName: 'a.pdf',
        fileSize: 123,
        createdAt,
        status,
        sourceId: 'src-a',
      },
    ],
  }
}

describe('reduceQueue', () => {
  it('patches by sourceId', () => {
    const s0 = mkState('queued', new Date().toISOString())
    const s1 = reduceQueue(s0, { type: 'patch_by_source', sourceId: 'src-a', patch: { status: 'done' } })
    expect(s1.items[0].status).toBe('done')
  })

  it('keeps non-terminal items even if old', () => {
    const old = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString()
    const s0 = mkState('queued', old)
    const s1 = reduceQueue(s0, { type: 'prune', nowMs: Date.now() })
    expect(s1.items).toHaveLength(1)
    expect(s1.items[0].status).toBe('queued')
  })
})
```

- [ ] **Step 3: Run tests**

Run:

```bash
cd frontend && npm test -- --run
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/state/ingestQueue.ts frontend/src/state/ingestQueue.test.ts
git commit -m "feat: add ingest queue reducer with localStorage persistence"
```

---

### Task 3: Lift ingest queue state to `Layout` and update via SSE

**Files:**
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: Add queue state + persistence loop**

In `frontend/src/components/Layout.tsx`, add:

```tsx
import { useMemo } from 'react'
import {
  loadQueueState,
  saveQueueState,
  reduceQueue,
  type QueueItem,
  type QueueState,
} from '../state/ingestQueue'
```

Initialize state (near other `useState` hooks):

```tsx
  const [queue, setQueue] = useState<QueueState>(() => loadQueueState(window.localStorage))
```

Persist on change:

```tsx
  useEffect(() => {
    saveQueueState(window.localStorage, queue)
  }, [queue])
```

Queue action helpers:

```tsx
  const queueActions = useMemo(() => ({
    upsertMany(items: QueueItem[]) {
      setQueue(s => reduceQueue(s, { type: 'upsert_many', items }))
    },
    patchBySource(sourceId: string, patch: Partial<QueueItem>) {
      setQueue(s => reduceQueue(s, { type: 'patch_by_source', sourceId, patch }))
    },
    prune() {
      setQueue(s => reduceQueue(s, { type: 'prune', nowMs: Date.now() }))
    },
    clear() {
      setQueue(s => reduceQueue(s, { type: 'clear' }))
    },
  }), [])
```

Add a low-frequency prune (e.g. on mount and every minute):

```tsx
  useEffect(() => {
    queueActions.prune()
    const t = setInterval(() => queueActions.prune(), 60_000)
    return () => clearInterval(t)
  }, [queueActions])
```

- [ ] **Step 2: Update SSE handler to patch queue items**

Inside the existing `createSSE` callback in `Layout.tsx`, add mapping:

```tsx
      const STATUS_MAP: Partial<Record<string, QueueItem['status']>> = {
        'agent:queued': 'queued',
        'agent:converting': 'converting',
        'agent:ingesting': 'processing',
        'agent:done': 'done',
      }
      const queueStatus = STATUS_MAP[event.event]
      if (queueStatus && event.source_id) {
        queueActions.patchBySource(event.source_id, { status: queueStatus })
      }
```

Keep the existing `agentStatus` banner behavior as-is.

- [ ] **Step 3: Pass queue props into `ActivityLog` and `IngestModal`**

Update the render calls:

```tsx
      {showActivity && (
        <ActivityLog
          onClose={() => setShowActivity(false)}
          queue={queue}
          onClearQueue={() => queueActions.clear()}
        />
      )}
      {showIngest && (
        <IngestModal
          onClose={() => setShowIngest(false)}
          queue={queue}
          onUpsertQueueItems={(items) => queueActions.upsertMany(items)}
          onPatchQueueBySource={(sourceId, patch) => queueActions.patchBySource(sourceId, patch)}
          onPatchQueueById={(id, patch) => setQueue(s => reduceQueue(s, { type: 'patch_by_id', id, patch }))}
        />
      )}
```

This intentionally avoids introducing a global context; `Layout` remains the single source of truth.

- [ ] **Step 4: Typecheck**

Run:

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Layout.tsx
git commit -m "feat: persist ingest queue in layout and update via SSE"
```

---

### Task 4: Add `Queue` tab to `ActivityLog`

**Files:**
- Modify: `frontend/src/components/ActivityLog.tsx`

- [ ] **Step 1: Add props and tab state**

Update component signature:

```tsx
export default function ActivityLog({
  onClose,
  queue,
  onClearQueue,
}: {
  onClose: () => void
  queue: { items: { id: string; fileName: string; fileSize: number; createdAt: string; status: string; sourceId?: string }[] }
  onClearQueue: () => void
}) {
```

Add:

```tsx
  const [tab, setTab] = useState<'activity' | 'queue'>('activity')
```

Add header tabs (next to title) with simple buttons matching existing style.

- [ ] **Step 2: Render queue list**

When `tab === 'queue'`, render:
- newest first (by `createdAt`)
- file name + status + timestamp
- a “Clear” button (calls `onClearQueue`)

Example queue row layout:

```tsx
<div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
  <div style={{ overflow: 'hidden' }}>
    <div style={{ fontSize: 12, color: '#e6edf3', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
      {item.fileName}
    </div>
    <div style={{ fontSize: 10, color: '#484f58' }}>{new Date(item.createdAt).toLocaleString()}</div>
  </div>
  <div style={{ fontSize: 11, color: '#8b949e', flexShrink: 0 }}>{item.status}</div>
</div>
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ActivityLog.tsx
git commit -m "feat: add queue tab to activity drawer"
```

---

### Task 5: Make `IngestModal` scroll-safe and use the shared queue store

**Files:**
- Modify: `frontend/src/components/IngestModal.tsx`

- [ ] **Step 1: Add queue props**

Update component signature:

```tsx
export default function IngestModal({
  onClose,
  queue,
  onUpsertQueueItems,
  onPatchQueueById,
}: {
  onClose: () => void
  queue: { items: { id: string; fileName: string; fileSize: number; createdAt: string; status: string; sourceId?: string }[] }
  onUpsertQueueItems: (items: { id: string; fileName: string; fileSize: number; createdAt: string; status: any; sourceId?: string }[]) => void
  onPatchQueueById: (id: string, patch: Record<string, unknown>) => void
}) {
```

Leave the Text/URL path as-is.

- [ ] **Step 2: On file selection, upsert queue items**

In `handleFileChange`, instead of `setFileEntries(...)`, create queue items:

```tsx
const now = new Date().toISOString()
onUpsertQueueItems(files.map(file => ({
  id: crypto.randomUUID(),
  fileName: file.name,
  fileSize: file.size,
  createdAt: now,
  status: 'pending',
})))
```

Also store the `File` objects locally for upload (keep a local map `id -> File` inside the modal; do not persist File objects to localStorage).

- [ ] **Step 3: Upload flow patches queue status**

When uploading each file:
- patch by id: `uploading`
- after `ingestFile` response: patch by id with `sourceId` and `queued`
- on catch: patch by id with `error`

- [ ] **Step 4: Make the modal card height-bounded with a scroll region**

Change modal card container styles to:

```tsx
<div style={{
  background: '#161b22',
  border: '1px solid #30363d',
  borderRadius: 12,
  padding: 24,
  width: 480,
  maxWidth: '90vw',
  maxHeight: '90vh',
  display: 'flex',
  flexDirection: 'column',
}}>
```

Wrap the variable content in a scroll container:

```tsx
<div style={{ overflowY: 'auto', paddingRight: 4 }}>
  {/* tabs + inputs + file list */}
</div>
<div style={{ flexShrink: 0, marginTop: 12 }}>
  {/* upload button / ingest button / status */}
</div>
```

This guarantees the Upload/Start button remains reachable.

- [ ] **Step 5: Manual test**

1. Open `+ Ingest` → File tab
2. Select 50+ files
3. Verify:
   - file list scrolls within the modal
   - Upload button remains visible and clickable
4. Start upload, then close the modal
5. Open `Activity` drawer → switch to `Queue` tab
6. Verify statuses update live during SSE events and persist across refresh

- [ ] **Step 6: Typecheck + tests**

```bash
cd frontend && npx tsc --noEmit
cd frontend && npm test -- --run
```

Expected: no errors; tests pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/IngestModal.tsx
git commit -m "fix: keep ingest upload button visible and persist queue view"
```

---

## Self-Review Checklist

- [ ] **Spec coverage:** Modal file list scrolls; primary action always reachable; Queue tab exists; queue persists via localStorage; SSE updates queue via Layout-level subscription
- [ ] **No placeholders:** All steps have exact code and commands
- [ ] **Type consistency:** `QueueItem.status` values match SSE mapping and UI labels
- [ ] **No File objects in storage:** Only metadata persisted; `File` kept in modal memory only

