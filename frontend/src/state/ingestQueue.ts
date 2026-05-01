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
