import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useSse } from '@/hooks/useSse'
import {
  loadQueueState,
  reduceQueue,
  saveQueueState,
  type QueueItem,
  type QueueState,
} from '@/state/ingestQueue'

export type ShellStateContextValue = {
  selectedSlug: string | null
  highlightedSlug: string | null
  agentStatus: string | null
  showActivity: boolean
  setShowActivity: (open: boolean) => void
  showIngest: boolean
  setShowIngest: (open: boolean) => void
  queue: QueueState
  queueActions: {
    upsertMany: (items: QueueItem[]) => void
    patchBySource: (sourceId: string, patch: Partial<QueueItem>) => void
    patchById: (id: string, patch: Partial<QueueItem>) => void
    prune: () => void
    clear: () => void
  }
  chatSseEvent: { event: string; slug?: string } | null
  onSelectSlug: (slug: string) => void
}

const ShellStateContext = createContext<ShellStateContextValue | null>(null)

export function ShellStateProvider({ children }: { children: ReactNode }) {
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null)
  const [highlightedSlug, setHighlightedSlug] = useState<string | null>(null)
  const [agentStatus, setAgentStatus] = useState<string | null>(null)
  const [showActivity, setShowActivity] = useState(false)
  const [showIngest, setShowIngest] = useState(false)
  const [queue, setQueue] = useState<QueueState>(() => loadQueueState(window.localStorage))
  const [chatSseEvent, setChatSseEvent] = useState<{ event: string; slug?: string } | null>(null)
  const qc = useQueryClient()

  useEffect(() => {
    saveQueueState(window.localStorage, queue)
  }, [queue])

  const queueActions = useMemo(
    () => ({
      upsertMany(items: QueueItem[]) {
        setQueue(s => reduceQueue(s, { type: 'upsert_many', items }))
      },
      patchBySource(sourceId: string, patch: Partial<QueueItem>) {
        setQueue(s => reduceQueue(s, { type: 'patch_by_source', sourceId, patch }))
      },
      patchById(id: string, patch: Partial<QueueItem>) {
        setQueue(s => reduceQueue(s, { type: 'patch_by_id', id, patch }))
      },
      prune() {
        setQueue(s => reduceQueue(s, { type: 'prune', nowMs: Date.now() }))
      },
      clear() {
        setQueue(s => reduceQueue(s, { type: 'clear' }))
      },
    }),
    [],
  )

  useEffect(() => {
    queueActions.prune()
    const t = setInterval(() => queueActions.prune(), 60_000)
    return () => clearInterval(t)
  }, [queueActions])

  useSse((data: unknown) => {
    const event = data as {
      event: string
      slug?: string
      source_id?: string
      filename?: string
      pages_touched?: string[]
      context?: string
    }
    if (event.context === 'chat') {
      if (event.event === 'agent:done') {
        qc.invalidateQueries({ queryKey: ['pages'] })
        qc.invalidateQueries({ queryKey: ['activity'] })
      } else {
        setChatSseEvent({ event: event.event, slug: event.slug })
      }
      return
    }
    const STATUS_MAP: Partial<Record<string, QueueItem['status']>> = {
      'agent:queued': 'queued',
      'agent:converting': 'converting',
      'agent:ingesting': 'processing',
      'agent:done': 'done',
      'agent:error': 'error',
    }
    const queueStatus = STATUS_MAP[event.event]
    if (queueStatus && event.source_id) {
      queueActions.patchBySource(event.source_id, { status: queueStatus })
    }
    if (event.event === 'agent:error') {
      setHighlightedSlug(null)
      setAgentStatus(null)
    }
    if (event.event === 'agent:queued') {
      const label = event.filename ?? (event.source_id ? `source ${event.source_id.slice(0, 8)}…` : null)
      setAgentStatus(label ? `Queued ${label}…` : 'Queued…')
    } else if (event.event === 'agent:converting') {
      const label = event.filename ?? (event.source_id ? `source ${event.source_id.slice(0, 8)}…` : null)
      setAgentStatus(label ? `Converting ${label}…` : 'Converting document…')
    } else if (event.event === 'agent:ingesting') {
      const label = event.filename ?? (event.source_id ? `source ${event.source_id.slice(0, 8)}…` : null)
      setAgentStatus(label ? `Updating wiki from ${label}…` : 'Updating wiki from ingested source…')
    } else if (event.event === 'agent:reading') {
      setHighlightedSlug(event.slug || null)
      setAgentStatus(`Reading ${event.slug}…`)
    } else if (event.event === 'agent:writing') {
      setHighlightedSlug(event.slug || null)
      setAgentStatus(`Writing ${event.slug}…`)
    } else if (event.event === 'agent:moving') {
      const e = event as { event: string; from?: string; to?: string }
      setHighlightedSlug(e.to || null)
      setAgentStatus(e.from && e.to ? `Moving ${e.from} → ${e.to}…` : 'Moving page…')
    } else if (event.event === 'agent:deleting') {
      setHighlightedSlug(null)
      setAgentStatus(event.slug ? `Deleting ${event.slug}…` : 'Deleting page…')
    } else if (event.event === 'agent:moved_folder') {
      const e = event as { event: string; from?: string; to?: string; count?: number }
      setHighlightedSlug(null)
      setAgentStatus(
        e.from && e.to
          ? `Moved ${e.count ?? '?'} pages: ${e.from} → ${e.to}`
          : 'Folder move complete',
      )
    } else if (event.event === 'agent:done') {
      setHighlightedSlug(null)
      setAgentStatus(null)
      qc.invalidateQueries({ queryKey: ['pages'] })
      qc.invalidateQueries({ queryKey: ['activity'] })
    }
  })

  const onSelectSlug = useCallback((slug: string) => {
    setSelectedSlug(slug)
  }, [])

  const value = useMemo<ShellStateContextValue>(
    () => ({
      selectedSlug,
      highlightedSlug,
      agentStatus,
      showActivity,
      setShowActivity,
      showIngest,
      setShowIngest,
      queue,
      queueActions,
      chatSseEvent,
      onSelectSlug,
    }),
    [
      selectedSlug,
      highlightedSlug,
      agentStatus,
      showActivity,
      showIngest,
      queue,
      queueActions,
      chatSseEvent,
      onSelectSlug,
    ],
  )

  return <ShellStateContext.Provider value={value}>{children}</ShellStateContext.Provider>
}

export function useShellState(): ShellStateContextValue {
  const ctx = useContext(ShellStateContext)
  if (!ctx) throw new Error('useShellState must be used within ShellStateProvider')
  return ctx
}
