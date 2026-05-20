import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getActivity } from '../api/client'
import type { QueueState, QueueStatus } from '../state/ingestQueue'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
} from '@/components/ui/sheet'

const labels: Record<string, string> = {
  page_created: 'Page created',
  page_updated: 'Page updated',
  page_deleted: 'Page deleted',
  source_ingested: 'Source ingested',
  chat_ingested: 'Saved from chat',
  chat_message: 'Chat message',
}

const CHANGE_EVENTS = new Set(['page_created', 'page_updated', 'page_deleted'])

const CHANGE_ACTION_LABEL: Record<string, string> = {
  page_created: 'Created',
  page_updated: 'Updated',
  page_deleted: 'Deleted',
}

const CHANGE_ACTION_COLOR: Record<string, string> = {
  page_created: '#3fb950',
  page_updated: '#58a6ff',
  page_deleted: '#f85149',
}

const QUEUE_STATUS_LABEL: Record<QueueStatus, string> = {
  pending: 'Pending',
  uploading: 'Uploading…',
  queued: 'Queued…',
  converting: 'Converting…',
  processing: 'Processing…',
  done: 'Done',
  error: 'Error',
}

const QUEUE_STATUS_COLOR: Record<QueueStatus, string> = {
  pending: '#8b949e',
  uploading: '#58a6ff',
  queued: '#a371f7',
  converting: '#d29922',
  processing: '#d29922',
  done: '#3fb950',
  error: '#f85149',
}

export default function ActivityLog({
  onClose,
  queue,
  onClearQueue,
}: {
  onClose: () => void
  queue: QueueState
  onClearQueue: () => void
}) {
  const [tab, setTab] = useState<'activity' | 'changes' | 'queue'>('activity')
  const { data: events = [] } = useQuery<{ id: string; event_type: string; payload: Record<string, unknown>; created_at: string }[]>({
    queryKey: ['activity'],
    queryFn: () => getActivity(),
    refetchInterval: 5000,
  })

  const changeEvents = events.filter(e => CHANGE_EVENTS.has(e.event_type))

  const queueSortedNewestFirst = [...queue.items].sort((a, b) =>
    a.createdAt < b.createdAt ? 1 : -1,
  )

  const tabBtn = (id: typeof tab, label: string) => (
    <Button
      type="button"
      variant={tab === id ? 'default' : 'outline'}
      size="sm"
      className="h-7 text-xs"
      onClick={() => setTab(id)}
    >
      {label}
    </Button>
  )

  return (
    <Sheet open onOpenChange={(isOpen) => { if (!isOpen) onClose() }}>
      <SheetContent
        side="right"
        className="flex h-full w-[28rem] max-w-none flex-col gap-0 p-0 sm:max-w-none"
      >
        <div className="flex items-center gap-2 border-b border-border px-4 py-3 pr-12">
          {tabBtn('activity', 'Activity')}
          {tabBtn('changes', 'Changes')}
          {tabBtn('queue', 'Queue')}
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          {tab === 'activity' && (
            <>
              {events.map(e => (
                <div key={e.id} className="mb-3 rounded-md border border-border bg-card p-3">
                  <div className="mb-1 text-xs text-[#3fb950]">
                    {labels[e.event_type] || e.event_type}
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    {e.payload.slug ? `[[${e.payload.slug}]]` : ''}
                    {e.payload.pages_touched ? ` → ${(e.payload.pages_touched as string[]).join(', ')}` : ''}
                  </div>
                  <div className="mt-1 text-[10px] text-muted-foreground/70">
                    {new Date(e.created_at).toLocaleString()}
                  </div>
                </div>
              ))}
              {events.length === 0 && (
                <div className="mt-10 text-center text-sm text-muted-foreground">
                  No activity yet. Ingest something!
                </div>
              )}
            </>
          )}
          {tab === 'changes' && (
            <>
              {changeEvents.map(e => (
                <div key={e.id} className="mb-3 rounded-md border border-border bg-card p-3">
                  <div
                    className="mb-1 text-xs"
                    style={{ color: CHANGE_ACTION_COLOR[e.event_type] ?? '#8b949e' }}
                  >
                    {CHANGE_ACTION_LABEL[e.event_type] ?? e.event_type}
                  </div>
                  <div className="font-mono text-[11px] text-muted-foreground">
                    {e.payload.slug ? `[[${e.payload.slug}]]` : '—'}
                  </div>
                  <div className="mt-1 text-[10px] text-muted-foreground/70">
                    {new Date(e.created_at).toLocaleString()}
                  </div>
                </div>
              ))}
              {changeEvents.length === 0 && (
                <div className="mt-10 text-center text-sm text-muted-foreground">
                  No wiki changes yet.
                </div>
              )}
            </>
          )}
          {tab === 'queue' && (
            <>
              <div className="mb-3 flex justify-end">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs"
                  onClick={onClearQueue}
                >
                  Clear
                </Button>
              </div>
              {queueSortedNewestFirst.map(item => (
                <div
                  key={item.id}
                  className="mb-3 flex items-start justify-between gap-2 rounded-md border border-border bg-card p-3"
                >
                  <div className="min-w-0 flex-1 overflow-hidden">
                    <div className="truncate text-xs text-foreground">
                      {item.fileName}
                    </div>
                    <div className="mt-1 text-[10px] text-muted-foreground/70">
                      {new Date(item.createdAt).toLocaleString()}
                    </div>
                  </div>
                  <span
                    className="shrink-0 text-[11px]"
                    style={{ color: QUEUE_STATUS_COLOR[item.status] ?? '#8b949e' }}
                  >
                    {QUEUE_STATUS_LABEL[item.status]}
                  </span>
                </div>
              ))}
              {queueSortedNewestFirst.length === 0 && (
                <div className="mt-10 text-center text-sm text-muted-foreground">
                  No ingest queue items yet.
                </div>
              )}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
