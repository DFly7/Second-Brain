import { useState, useEffect, useMemo } from 'react'
import type React from 'react'
import { Panel, Group as PanelGroup, Separator as PanelResizeHandle } from 'react-resizable-panels'
import WikiSidebar from './WikiSidebar'
import WikiContent from './WikiContent'
import ChatPanel from './ChatPanel'
import IngestModal from './IngestModal'
import ActivityLog from './ActivityLog'
import TopBar from './TopBar'
import { useSse } from '../hooks/useSse'
import { useIsMobile } from '../hooks/useIsMobile'
import { useQueryClient } from '@tanstack/react-query'
import {
  loadQueueState,
  saveQueueState,
  reduceQueue,
  type QueueItem,
  type QueueState,
} from '../state/ingestQueue'

export default function Layout() {
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

  const isMobile = useIsMobile()
  const [activeTab, setActiveTab] = useState<'pages' | 'content' | 'chat'>('content')

  function handleMobileSelect(slug: string) {
    setSelectedSlug(slug)
    if (isMobile) setActiveTab('content')
  }

  function handleMobileNavigate(slug: string) {
    setSelectedSlug(slug)
    if (isMobile) setActiveTab('content')
  }

  if (isMobile) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
        <TopBar agentStatus={agentStatus} onShowIngest={() => setShowIngest(true)} />

        {/* Activity row */}
        <div style={{
          display: 'flex',
          justifyContent: 'flex-end',
          padding: '4px 16px',
          background: '#161b22',
          borderBottom: '1px solid #30363d',
        }}>
          <button
            type="button"
            onClick={() => setShowActivity(!showActivity)}
            style={{
              padding: '2px 10px',
              background: '#21262d',
              border: '1px solid #30363d',
              borderRadius: 6,
              color: '#e6edf3',
              cursor: 'pointer',
              fontSize: 12,
            }}
          >
            Activity
          </button>
        </div>

        {/* Active panel */}
        <div style={{ flex: 1, overflow: 'hidden' }}>
          {activeTab === 'pages' && (
            <WikiSidebar
              selectedSlug={selectedSlug}
              highlightedSlug={highlightedSlug}
              onSelect={handleMobileSelect}
            />
          )}
          {activeTab === 'content' && (
            <WikiContent selectedSlug={selectedSlug} onNavigate={handleMobileNavigate} />
          )}
          {activeTab === 'chat' && (
            <ChatPanel onNavigate={handleMobileNavigate} activeSseEvent={chatSseEvent} />
          )}
        </div>

        {/* Bottom tab bar */}
        <div style={{
          display: 'flex',
          borderTop: '2px solid #30363d',
          background: '#161b22',
          flexShrink: 0,
        }}>
          {([
            { id: 'pages', label: '≡ Pages' },
            { id: 'content', label: '□ Content' },
            { id: 'chat', label: '◎ Chat' },
          ] as const).map(({ id, label }) => (
            <button
              key={id}
              type="button"
              onClick={() => setActiveTab(id)}
              style={{
                flex: 1,
                padding: '12px 0',
                border: 'none',
                borderTop: activeTab === id ? '2px solid #58a6ff' : '2px solid transparent',
                marginTop: -2,
                background: 'none',
                color: activeTab === id ? '#58a6ff' : '#6e7681',
                fontSize: 13,
                cursor: 'pointer',
                fontFamily: 'inherit',
              }}
            >
              {label}
            </button>
          ))}
        </div>

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
            onUpsertQueueItems={items => queueActions.upsertMany(items)}
            onPatchQueueById={(id, patch) =>
              setQueue(s => reduceQueue(s, { type: 'patch_by_id', id, patch }))
            }
          />
        )}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <TopBar agentStatus={agentStatus} onShowIngest={() => setShowIngest(true)} />
      <div
        style={{
          display: 'flex',
          justifyContent: 'flex-end',
          padding: '4px 16px',
          background: '#161b22',
          borderBottom: '1px solid #30363d',
        }}
      >
        <button
          type="button"
          onClick={() => setShowActivity(!showActivity)}
          style={{
            padding: '2px 10px',
            background: '#21262d',
            border: '1px solid #30363d',
            borderRadius: 6,
            color: '#e6edf3',
            cursor: 'pointer',
            fontSize: 12,
          }}
        >
          Activity
        </button>
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
          <ChatPanel onNavigate={setSelectedSlug} activeSseEvent={chatSseEvent} />
        </Panel>
      </PanelGroup>

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
          onUpsertQueueItems={items => queueActions.upsertMany(items)}
          onPatchQueueById={(id, patch) => setQueue(s => reduceQueue(s, { type: 'patch_by_id', id, patch }))}
        />
      )}
    </div>
  )
}

const resizeHandleStyle: React.CSSProperties = {
  width: 4,
  background: '#21262d',
  cursor: 'col-resize',
  flexShrink: 0,
  transition: 'background 0.15s',
}
