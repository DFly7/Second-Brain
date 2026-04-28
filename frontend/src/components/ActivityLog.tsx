import { useQuery } from '@tanstack/react-query'
import { getActivity } from '../api/client'

const labels: Record<string, string> = {
  page_created: 'Page created',
  page_updated: 'Page updated',
  source_ingested: 'Source ingested',
  chat_ingested: 'Saved from chat',
  chat_message: 'Chat message',
}

export default function ActivityLog({ onClose }: { onClose: () => void }) {
  const { data: events = [] } = useQuery<{ id: string; event_type: string; payload: Record<string, unknown>; created_at: string }[]>({
    queryKey: ['activity'],
    queryFn: () => getActivity(),
    refetchInterval: 5000
  })

  return (
    <div style={{ position: 'fixed', right: 0, top: 0, bottom: 0, width: 360, background: '#161b22',
      borderLeft: '1px solid #30363d', zIndex: 50, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '12px 16px', borderBottom: '1px solid #30363d' }}>
        <span style={{ fontWeight: 600, fontSize: 14, color: '#e6edf3' }}>Activity</span>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#8b949e',
          cursor: 'pointer', fontSize: 18 }}>×</button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
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
      </div>
    </div>
  )
}
