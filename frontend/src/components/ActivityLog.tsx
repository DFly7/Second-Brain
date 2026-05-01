import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getActivity } from '../api/client'
import type { QueueState, QueueStatus } from '../state/ingestQueue'

const EMPTY_QUEUE: QueueState = { items: [] }

const labels: Record<string, string> = {
  page_created: 'Page created',
  page_updated: 'Page updated',
  source_ingested: 'Source ingested',
  chat_ingested: 'Saved from chat',
  chat_message: 'Chat message',
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
  queue = EMPTY_QUEUE,
  onClearQueue = () => {},
}: {
  onClose: () => void
  queue?: QueueState
  onClearQueue?: () => void
}) {
  const [tab, setTab] = useState<'activity' | 'queue'>('activity')
  const { data: events = [] } = useQuery<{ id: string; event_type: string; payload: Record<string, unknown>; created_at: string }[]>({
    queryKey: ['activity'],
    queryFn: () => getActivity(),
    refetchInterval: 5000,
  })

  const queueSortedNewestFirst = [...queue.items].sort((a, b) =>
    a.createdAt < b.createdAt ? 1 : -1,
  )

  return (
    <div style={{ position: 'fixed', right: 0, top: 0, bottom: 0, width: 360, background: '#161b22',
      borderLeft: '1px solid #30363d', zIndex: 50, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '12px 16px', borderBottom: '1px solid #30363d', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ display: 'flex', gap: 4 }}>
            <button
              type="button"
              onClick={() => setTab('activity')}
              style={{
                padding: '4px 12px',
                background: tab === 'activity' ? '#238636' : '#21262d',
                border: '1px solid #30363d',
                borderRadius: 6,
                color: '#e6edf3',
                cursor: 'pointer',
                fontSize: 12,
              }}
            >
              activity
            </button>
            <button
              type="button"
              onClick={() => setTab('queue')}
              style={{
                padding: '4px 12px',
                background: tab === 'queue' ? '#238636' : '#21262d',
                border: '1px solid #30363d',
                borderRadius: 6,
                color: '#e6edf3',
                cursor: 'pointer',
                fontSize: 12,
              }}
            >
              queue
            </button>
          </div>
        </div>
        <button onClick={onClose} type="button" style={{ background: 'none', border: 'none', color: '#8b949e',
          cursor: 'pointer', fontSize: 18, flexShrink: 0 }}>×</button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        {tab === 'activity' && (
          <>
            {events.map((e: { id: string; event_type: string; payload: Record<string, unknown>; created_at: string }) => (
              <div key={e.id} style={{ marginBottom: 12, padding: '8px 12px', background: '#0d1117',
                borderRadius: 6, border: '1px solid #21262d' }}>
                <div style={{ fontSize: 12, color: '#3fb950', marginBottom: 4 }}>
                  {labels[e.event_type] || e.event_type}
                </div>
                <div style={{ fontSize: 11, color: '#8b949e' }}>
                  {e.payload.slug ? `[[${e.payload.slug}]]` : ''}
                  {e.payload.pages_touched ? ` → ${(e.payload.pages_touched as string[]).join(', ')}` : ''}
                </div>
                <div style={{ fontSize: 10, color: '#484f58', marginTop: 4 }}>
                  {new Date(e.created_at).toLocaleString()}
                </div>
              </div>
            ))}
            {events.length === 0 && (
              <div style={{ color: '#8b949e', fontSize: 13, textAlign: 'center', marginTop: 40 }}>
                No activity yet. Ingest something!
              </div>
            )}
          </>
        )}
        {tab === 'queue' && (
          <>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
              <button
                type="button"
                onClick={onClearQueue}
                style={{
                  padding: '6px 12px',
                  background: '#21262d',
                  border: '1px solid #30363d',
                  borderRadius: 6,
                  color: '#e6edf3',
                  cursor: 'pointer',
                  fontSize: 12,
                }}
              >
                Clear
              </button>
            </div>
            {queueSortedNewestFirst.map(item => (
              <div
                key={item.id}
                style={{
                  marginBottom: 12,
                  padding: '10px 12px',
                  background: '#0d1117',
                  borderRadius: 6,
                  border: '1px solid #21262d',
                  display: 'flex',
                  justifyContent: 'space-between',
                  gap: 8,
                  alignItems: 'flex-start',
                }}
              >
                <div style={{ overflow: 'hidden', flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: '#e6edf3', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {item.fileName}
                  </div>
                  <div style={{ fontSize: 10, color: '#484f58', marginTop: 4 }}>
                    {new Date(item.createdAt).toLocaleString()}
                  </div>
                </div>
                <span
                  style={{
                    fontSize: 11,
                    color: QUEUE_STATUS_COLOR[item.status] ?? '#8b949e',
                    flexShrink: 0,
                  }}
                >
                  {QUEUE_STATUS_LABEL[item.status]}
                </span>
              </div>
            ))}
            {queueSortedNewestFirst.length === 0 && (
              <div style={{ color: '#8b949e', fontSize: 13, textAlign: 'center', marginTop: 40 }}>
                No ingest queue items yet.
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
