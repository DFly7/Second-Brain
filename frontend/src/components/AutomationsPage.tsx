import React, { useEffect, useRef, useState } from 'react'
import {
  type AutomationAction,
  type AutomationRun,
  getAutomationRun,
  getAutomationRuns,
  getNovncUrl,
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
    getAutomationRuns().then(setRuns).catch(() => {})
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
      if (status !== 'running') {
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
    setPageState('idle')
    setActiveRunId(null)
    setActiveGoal('')
    getAutomationRuns().then(setRuns).catch(() => {})
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
    if (status === 'running') return '#58a6ff'
    return '#d29922'
  }

  const ACTION_ICON: Record<string, string> = {
    navigate: '🧭',
    click: '🖱',
    type: '⌨️',
    scroll: '↕️',
    read: '📖',
    screenshot: '📸',
    wiki_write: '✍️',
  }

  if (pageState === 'running') {
    return (
      <motion.div style={{ display: 'flex', height: '100%', overflow: 'hidden', background: '#0d1117' }}>
        {/* Left panel */}
        <motion.div style={{
          width: 300,
          background: '#161b22',
          borderRight: '1px solid #30363d',
          display: 'flex',
          flexDirection: 'column',
          flexShrink: 0,
        }}>
          <motion.div style={{ padding: '12px 16px', borderBottom: '1px solid #30363d', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.8px', color: '#8b949e' }}>
            Goal
          </motion.div>
          <motion.div style={{ flex: 1, padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
            <motion.div style={{ fontSize: 13, color: '#e6edf3', lineHeight: 1.5, background: '#21262d', border: '1px solid #30363d', borderRadius: 8, padding: '10px 12px' }}>
              {activeGoal || 'Running…'}
            </motion.div>
            <motion.div style={{ display: 'flex', alignItems: 'center', gap: 8, background: '#388bfd18', border: '1px solid #388bfd40', borderRadius: 20, padding: '4px 12px', width: 'fit-content' }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#58a6ff', display: 'inline-block', animation: 'pulse 1.5s ease-in-out infinite' }} />
              <span style={{ fontSize: 11, color: '#58a6ff' }}>Running — {actions.length} actions</span>
            </motion.div>
          </motion.div>
          <motion.div style={{ padding: 12, borderTop: '1px solid #30363d' }}>
            <button
              type="button"
              onClick={handleStop}
              style={{ width: '100%', padding: 8, background: '#f8514918', border: '1px solid #f8514940', borderRadius: 7, color: '#f85149', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}
            >
              ⏹ Stop Agent
            </button>
          </motion.div>
        </motion.div>

        {/* Center: browser */}
        <motion.div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#0d1117', minWidth: 0 }}>
          <motion.div style={{ background: '#161b22', borderBottom: '1px solid #30363d', padding: '8px 12px', display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
            <motion.div style={{ display: 'flex', gap: 4 }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#f85149', display: 'inline-block' }} />
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#ffbd2e', display: 'inline-block' }} />
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#3fb950', display: 'inline-block' }} />
            </motion.div>
            <motion.div style={{ flex: 1, background: '#0d1117', border: '1px solid #30363d', borderRadius: 6, padding: '4px 12px', fontSize: 12, color: '#8b949e', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {currentUrl || 'Starting browser…'}
            </motion.div>
            <motion.div style={{ display: 'flex', alignItems: 'center', gap: 5, background: '#3fb95012', border: '1px solid #3fb95030', padding: '3px 8px', borderRadius: 20, fontSize: 11, color: '#3fb950', flexShrink: 0 }}>
              <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#3fb950', display: 'inline-block', animation: 'pulse 1.5s ease-in-out infinite' }} />
              LIVE
            </motion.div>
          </motion.div>
          <motion.div style={{ flex: 1, overflow: 'hidden', background: '#000' }}>
            {novncUrl ? (
              <iframe
                src={novncUrl}
                style={{ width: '100%', height: '100%', border: 'none', display: 'block' }}
                title="Live browser"
              />
            ) : (
              <motion.div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#8b949e', fontSize: 13 }}>
                Connecting to browser…
              </motion.div>
            )}
          </motion.div>
        </motion.div>

        {/* Right panel: activity */}
        <motion.div style={{
          width: 260,
          background: '#161b22',
          borderLeft: '1px solid #30363d',
          display: 'flex',
          flexDirection: 'column',
          flexShrink: 0,
        }}>
          <motion.div style={{ padding: '12px 16px', borderBottom: '1px solid #30363d', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.8px', color: '#8b949e' }}>
            Activity
          </motion.div>
          <motion.div style={{ flex: 1, overflowY: 'auto', padding: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {actions.length === 0 && (
              <motion.div style={{ color: '#8b949e', fontSize: 12, fontStyle: 'italic', textAlign: 'center', marginTop: 20 }}>
                Waiting for agent…
              </motion.div>
            )}
            {actions.map((action, i) => (
              <motion.div key={action.id} style={{
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
              </motion.div>
            ))}
            <div ref={actionsEndRef} />
          </motion.div>
        </motion.div>

        <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }`}</style>
      </motion.div>
    )
  }

  // Idle: history view
  return (
    <motion.div style={{ flex: 1, overflowY: 'auto', background: '#0d1117', padding: 24 }}>
      <motion.div style={{ maxWidth: 720, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: '#e6edf3', margin: '0 0 8px' }}>Automations</h2>

        {/* New run */}
        <motion.div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 10, padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <textarea
            value={goal}
            onChange={e => setGoal(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleStart() }}
            placeholder="Give the agent a goal, e.g. 'Research the top 5 note-taking apps and save a comparison to tools/note-apps'"
            rows={3}
            style={{
              width: '100%',
              background: '#0d1117',
              border: '1px solid #30363d',
              borderRadius: 8,
              padding: '10px 12px',
              color: '#e6edf3',
              fontSize: 13,
              resize: 'none',
              outline: 'none',
              fontFamily: 'inherit',
              lineHeight: 1.5,
              boxSizing: 'border-box',
            }}
          />
          <motion.div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 12 }}>
            {startError && (
              <span style={{ fontSize: 12, color: '#f85149' }}>{startError}</span>
            )}
            <button
              type="button"
              onClick={handleStart}
              disabled={!goal.trim()}
              style={{
                padding: '8px 20px',
                background: goal.trim() ? '#238636' : '#21262d',
                border: `1px solid ${goal.trim() ? '#2ea043' : '#30363d'}`,
                borderRadius: 7,
                color: goal.trim() ? '#ffffff' : '#8b949e',
                fontSize: 13,
                fontWeight: 600,
                cursor: goal.trim() ? 'pointer' : 'default',
              }}
            >
              Run
            </button>
          </motion.div>
        </motion.div>

        {/* Run history */}
        {runs.map(run => (
          <motion.div key={run.id} style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 10, overflow: 'hidden' }}>
            <motion.div style={{ padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: statusDot(run.status), display: 'inline-block', flexShrink: 0 }} />
              <motion.div style={{ flex: 1, minWidth: 0 }}>
                <motion.div style={{ fontSize: 13, color: '#e6edf3', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {run.goal}
                </motion.div>
                <motion.div style={{ fontSize: 11, color: '#8b949e', marginTop: 2 }}>
                  {run.status.charAt(0).toUpperCase() + run.status.slice(1)}
                  {run.completed_at && ` · ${formatDuration(run)}`}
                </motion.div>
              </motion.div>
              <motion.div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                {run.recording_url && (
                  <button
                    type="button"
                    onClick={() => window.open(`/api/automations/runs/${run.id}/recording`, '_blank')}
                    style={smallBtn}
                  >
                    ▶ Watch
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setExpandedRunId(expandedRunId === run.id ? null : run.id)}
                  style={smallBtn}
                >
                  Actions {expandedRunId === run.id ? '▴' : '▾'}
                </button>
              </motion.div>
            </motion.div>
            {expandedRunId === run.id && (
              <ExpandedActions runId={run.id} />
            )}
          </motion.div>
        ))}

        {runs.length === 0 && (
          <motion.div style={{ textAlign: 'center', color: '#8b949e', fontSize: 13, marginTop: 32 }}>
            No automation runs yet. Write a goal above to get started.
          </motion.div>
        )}
      </motion.div>
    </motion.div>
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
    <motion.div style={{ borderTop: '1px solid #30363d', background: '#0d1117', padding: '10px 16px', display: 'flex', flexDirection: 'column', gap: 5 }}>
      <motion.div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.6px', color: '#8b949e', marginBottom: 4 }}>
        Action Log
      </motion.div>
      {actions.slice(0, 20).map(a => (
        <motion.div key={a.id} style={{ display: 'flex', gap: 10, fontSize: 12 }}>
          <span style={{ color: '#8b949e', width: 42, flexShrink: 0 }}>
            {new Date(a.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
          <span>{ACTION_ICON[a.type] ?? '•'}</span>
          <span style={{ color: a.type === 'wiki_write' ? '#3fb950' : '#8b949e' }}>{a.detail}</span>
        </motion.div>
      ))}
      {actions.length > 20 && (
        <motion.div style={{ fontSize: 11, color: '#8b949e', fontStyle: 'italic' }}>+ {actions.length - 20} more actions</motion.div>
      )}
      {actions.length === 0 && (
        <motion.div style={{ fontSize: 12, color: '#8b949e', fontStyle: 'italic' }}>Loading…</motion.div>
      )}
    </motion.div>
  )
}

const smallBtn: React.CSSProperties = {
  padding: '4px 10px',
  background: '#21262d',
  border: '1px solid #30363d',
  borderRadius: 6,
  color: '#8b949e',
  fontSize: 11,
  cursor: 'pointer',
}
