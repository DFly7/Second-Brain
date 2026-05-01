import { useState, useEffect } from 'react'
import type React from 'react'
import { Panel, Group as PanelGroup, Separator as PanelResizeHandle } from 'react-resizable-panels'
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
        pages_touched?: string[]
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
      <PanelGroup orientation="horizontal" style={{ flex: 1, overflow: 'hidden' }}>
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
