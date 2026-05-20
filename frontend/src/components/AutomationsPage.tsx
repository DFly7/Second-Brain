import React, { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import {
  type AutomationAction,
  type AutomationRun,
  getAutomationRun,
  getAutomationRuns,
  getNovncUrl,
  openAutomationRecording,
  startAutomationRun,
  stopAutomationRun,
} from '../api/client'
import { useSse } from '../hooks/useSse'

type PageState = 'idle' | 'running'

export default function AutomationsPage() {
  const [pageState, setPageState] = useState<PageState>('idle')
  const [runs, setRuns] = useState<AutomationRun[]>([])
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [activeGoal, setActiveGoal] = useState('')
  const [actions, setActions] = useState<AutomationAction[]>([])
  const [currentUrl, setCurrentUrl] = useState('')
  const [novncUrl, setNovncUrl] = useState<string | null>(null)
  const [goal, setGoal] = useState('')
  const [startError, setStartError] = useState<string | null>(null)
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)
  const actionsEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    getAutomationRuns()
      .then(fetched => {
        setRuns(fetched)
        const active = fetched.find(r => r.status === 'running' || r.status === 'stopping')
        if (active) {
          setActiveRunId(active.id)
          setActiveGoal(active.goal)
          setPageState('running')
        }
      })
      .catch(() => {})
    getNovncUrl().then(setNovncUrl).catch(() => {})
  }, [])

  useEffect(() => {
    actionsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [actions])

  useSse((data: unknown) => {
    const ev = data as Record<string, unknown>
    if (ev.event === 'automation:action') {
      const action = {
        id: String(Date.now()),
        type: String(ev.type ?? ''),
        detail: String(ev.detail ?? ''),
        timestamp: new Date().toISOString(),
      }
      setActions(prev => [...prev, action])
      if (ev.type === 'navigate') setCurrentUrl(String(ev.detail ?? '').replace('Navigated to ', ''))
    }
    if (ev.event === 'automation:status') {
      const status = String(ev.status ?? '')
      if (status !== 'running' && status !== 'stopping') {
        setPageState('idle')
        setActiveRunId(null)
        setActiveGoal('')
        getAutomationRuns().then(setRuns).catch(() => {})
      }
    }
  })

  async function handleStart() {
    if (!goal.trim()) return
    setStartError(null)
    const trimmed = goal.trim()
    try {
      const { run_id } = await startAutomationRun(trimmed)
      setActiveRunId(run_id)
      setActiveGoal(trimmed)
      setActions([])
      setCurrentUrl('')
      setPageState('running')
      setGoal('')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setStartError(msg.includes('409') ? 'An automation is already in progress.' : 'Failed to start.')
    }
  }

  async function handleStop() {
    if (!activeRunId) return
    await stopAutomationRun(activeRunId)
    // Stay on running view until agent finishes teardown (SSE automation:status).
    getAutomationRuns().then(setRuns).catch(() => {})
  }

  async function handleForceStop(runId: string) {
    await stopAutomationRun(runId)
    getAutomationRuns().then(setRuns).catch(() => {})
  }

  async function handleWatch(runId: string) {
    try {
      await openAutomationRecording(runId)
    } catch {
      setStartError('Could not load recording.')
    }
  }

  function formatDuration(run: AutomationRun): string {
    if (!run.completed_at) return ''
    const ms = new Date(run.completed_at).getTime() - new Date(run.created_at).getTime()
    const s = Math.round(ms / 1000)
    if (s < 60) return `${s}s`
    return `${Math.floor(s / 60)}m ${s % 60}s`
  }

  function statusDot(status: string): string {
    if (status === 'completed') return '#3fb950'
    if (status === 'failed') return '#f85149'
    if (status === 'running' || status === 'stopping') return '#58a6ff'
    return '#d29922'
  }

  const isActiveStatus = (status: string) => status === 'running' || status === 'stopping'

  const ACTION_ICON: Record<string, string> = {
    navigate: '🧭',
    click: '🖱',
    type: '⌨️',
    scroll: '↕️',
    read: '📖',
    screenshot: '📸',
    wiki_write: '✍️',
  }

  const pageContent = pageState === 'running' ? (
      <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden', background: '#0d1117' }}>
        {/* Left panel */}
        <div style={{
          width: 300,
          background: '#161b22',
          borderRight: '1px solid #30363d',
          display: 'flex',
          flexDirection: 'column',
          flexShrink: 0,
        }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid #30363d', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.8px', color: '#8b949e' }}>
            Goal
          </div>
          <div style={{ flex: 1, padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ fontSize: 13, color: '#e6edf3', lineHeight: 1.5, background: '#21262d', border: '1px solid #30363d', borderRadius: 8, padding: '10px 12px' }}>
              {activeGoal || 'Running…'}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: '#388bfd18', border: '1px solid #388bfd40', borderRadius: 20, padding: '4px 12px', width: 'fit-content' }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#58a6ff', display: 'inline-block', animation: 'pulse 1.5s ease-in-out infinite' }} />
              <span style={{ fontSize: 11, color: '#58a6ff' }}>Running — {actions.length} actions</span>
            </div>
          </div>
          <div style={{ padding: 12, borderTop: '1px solid #30363d' }}>
            <Button
              type="button"
              variant="outline"
              className="w-full border-destructive/40 bg-destructive/10 text-destructive hover:bg-destructive/15 hover:text-destructive"
              onClick={handleStop}
            >
              ⏹ Stop Agent
            </Button>
          </div>
        </div>

        {/* Center: browser */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#0d1117', minWidth: 0 }}>
          <div style={{ background: '#161b22', borderBottom: '1px solid #30363d', padding: '8px 12px', display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
            <div style={{ display: 'flex', gap: 4 }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#f85149', display: 'inline-block' }} />
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#ffbd2e', display: 'inline-block' }} />
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#3fb950', display: 'inline-block' }} />
            </div>
            <div style={{ flex: 1, background: '#0d1117', border: '1px solid #30363d', borderRadius: 6, padding: '4px 12px', fontSize: 12, color: '#8b949e', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {currentUrl || 'Starting browser…'}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, background: '#3fb95012', border: '1px solid #3fb95030', padding: '3px 8px', borderRadius: 20, fontSize: 11, color: '#3fb950', flexShrink: 0 }}>
              <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#3fb950', display: 'inline-block', animation: 'pulse 1.5s ease-in-out infinite' }} />
              LIVE
            </div>
          </div>
          <div style={{ flex: 1, overflow: 'hidden', background: '#000' }}>
            {novncUrl ? (
              <iframe
                src={novncUrl}
                style={{ width: '100%', height: '100%', border: 'none', display: 'block' }}
                title="Live browser"
              />
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#8b949e', fontSize: 13 }}>
                Connecting to browser…
              </div>
            )}
          </div>
        </div>

        {/* Right panel: activity */}
        <div style={{
          width: 260,
          background: '#161b22',
          borderLeft: '1px solid #30363d',
          display: 'flex',
          flexDirection: 'column',
          flexShrink: 0,
        }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid #30363d', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.8px', color: '#8b949e' }}>
            Activity
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {actions.length === 0 && (
              <div style={{ color: '#8b949e', fontSize: 12, fontStyle: 'italic', textAlign: 'center', marginTop: 20 }}>
                Waiting for agent…
              </div>
            )}
            {actions.map((action, i) => (
              <div key={action.id} style={{
                display: 'flex',
                gap: 8,
                padding: '7px 10px',
                background: i === actions.length - 1 ? '#388bfd10' : '#21262d',
                border: `1px solid ${i === actions.length - 1 ? '#388bfd40' : '#30363d'}`,
                borderRadius: 7,
                fontSize: 12,
              }}>
                <span>{ACTION_ICON[action.type] ?? '•'}</span>
                <span style={{ color: action.type === 'wiki_write' ? '#3fb950' : '#c9d1d9', flex: 1, lineHeight: 1.4 }}>
                  {action.detail}
                </span>
              </div>
            ))}
            <div ref={actionsEndRef} />
          </div>
        </div>

        <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }`}</style>
      </div>
  ) : (
    <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', background: '#0d1117', padding: 24 }}>
      <div style={{ maxWidth: 720, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: '#e6edf3', margin: '0 0 8px' }}>Automations</h2>

        {/* New run */}
        <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 10, padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <Textarea
            value={goal}
            onChange={e => setGoal(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleStart() }}
            placeholder="Give the agent a goal, e.g. 'Research the top 5 note-taking apps and save a comparison to tools/note-apps'"
            rows={3}
            className="resize-none text-[13px] leading-normal"
          />
          <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 12 }}>
            {startError && (
              <span style={{ fontSize: 12, color: '#f85149' }}>{startError}</span>
            )}
            <Button
              type="button"
              onClick={handleStart}
              disabled={!goal.trim()}
            >
              Run
            </Button>
          </div>
        </div>

        {/* Run history */}
        {runs.map(run => (
          <div key={run.id} style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 10, overflow: 'hidden' }}>
            <div style={{ padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: statusDot(run.status), display: 'inline-block', flexShrink: 0 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, color: '#e6edf3', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {run.goal}
                </div>
                <div style={{ fontSize: 11, color: '#8b949e', marginTop: 2 }}>
                  {run.status.charAt(0).toUpperCase() + run.status.slice(1)}
                  {run.completed_at && ` · ${formatDuration(run)}`}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                {isActiveStatus(run.status) && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 border-destructive/40 text-destructive hover:text-destructive"
                    onClick={() => handleForceStop(run.id)}
                  >
                    Force stop
                  </Button>
                )}
                {run.recording_url && !isActiveStatus(run.status) && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs"
                    onClick={() => handleWatch(run.id)}
                  >
                    ▶ Watch
                  </Button>
                )}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs"
                  onClick={() => setExpandedRunId(expandedRunId === run.id ? null : run.id)}
                >
                  Actions {expandedRunId === run.id ? '▴' : '▾'}
                </Button>
              </div>
            </div>
            {expandedRunId === run.id && (
              <ExpandedActions runId={run.id} />
            )}
          </div>
        ))}

        {runs.length === 0 && (
          <div style={{ textAlign: 'center', color: '#8b949e', fontSize: 13, marginTop: 32 }}>
            No automation runs yet. Write a goal above to get started.
          </div>
        )}
      </div>
    </div>
  )

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {pageContent}
      </div>
    </div>
  )
}

function ExpandedActions({ runId }: { runId: string }) {
  const [actions, setActions] = useState<AutomationAction[]>([])

  useEffect(() => {
    getAutomationRun(runId).then(data => setActions(data.actions)).catch(() => {})
  }, [runId])

  const ACTION_ICON: Record<string, string> = {
    navigate: '🧭', click: '🖱', type: '⌨️', scroll: '↕️',
    read: '📖', screenshot: '📸', wiki_write: '✍️',
  }

  return (
    <div style={{ borderTop: '1px solid #30363d', background: '#0d1117', padding: '10px 16px', display: 'flex', flexDirection: 'column', gap: 5 }}>
      <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.6px', color: '#8b949e', marginBottom: 4 }}>
        Action Log
      </div>
      <div style={{ overflowY: 'auto', maxHeight: 300, display: 'flex', flexDirection: 'column', gap: 5 }}>
        {actions.map(a => (
          <div key={a.id} style={{ display: 'flex', gap: 10, fontSize: 12 }}>
            <span style={{ color: '#8b949e', width: 42, flexShrink: 0 }}>
              {new Date(a.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
            <span>{ACTION_ICON[a.type] ?? '•'}</span>
            <span style={{ color: a.type === 'wiki_write' ? '#3fb950' : '#8b949e' }}>{a.detail}</span>
          </div>
        ))}
        {actions.length === 0 && (
          <div style={{ fontSize: 12, color: '#8b949e', fontStyle: 'italic' }}>Loading…</div>
        )}
      </div>
    </div>
  )
}

