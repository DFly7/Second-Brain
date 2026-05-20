import React, { useEffect, useRef, useState } from 'react'
import { MoreHorizontal, Play, Plus, Square } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/EmptyState'
import { ListSkeleton } from '@/components/ListSkeleton'
import { cn } from '@/lib/utils'
import { toast } from '@/lib/toast'
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

const ACTION_ICON: Record<string, string> = {
  navigate: '🧭',
  click: '🖱',
  type: '⌨️',
  scroll: '↕️',
  read: '📖',
  screenshot: '📸',
  wiki_write: '✍️',
}

function statusBadgeClass(status: string): string {
  if (status === 'completed') return 'border-green-500/30 bg-green-500/10 text-green-500'
  if (status === 'failed') return 'border-destructive/30 bg-destructive/10 text-destructive'
  if (status === 'running' || status === 'stopping') return 'border-blue-500/30 bg-blue-500/10 text-blue-500'
  return 'border-amber-500/30 bg-amber-500/10 text-amber-500'
}

function formatDuration(run: AutomationRun): string {
  if (!run.completed_at) return '—'
  const ms = new Date(run.completed_at).getTime() - new Date(run.created_at).getTime()
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${s % 60}s`
}

function isActiveStatus(status: string) {
  return status === 'running' || status === 'stopping'
}

export default function AutomationsPage() {
  const [pageState, setPageState] = useState<PageState>('idle')
  const [runs, setRuns] = useState<AutomationRun[]>([])
  const [runsLoading, setRunsLoading] = useState(true)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [activeGoal, setActiveGoal] = useState('')
  const [actions, setActions] = useState<AutomationAction[]>([])
  const [currentUrl, setCurrentUrl] = useState('')
  const [novncUrl, setNovncUrl] = useState<string | null>(null)
  const [goal, setGoal] = useState('')
  const [newRunOpen, setNewRunOpen] = useState(false)
  const [actionsRunId, setActionsRunId] = useState<string | null>(null)
  const actionsEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setRunsLoading(true)
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
      .finally(() => setRunsLoading(false))
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
    const trimmed = goal.trim()
    try {
      const { run_id } = await startAutomationRun(trimmed)
      setActiveRunId(run_id)
      setActiveGoal(trimmed)
      setActions([])
      setCurrentUrl('')
      setPageState('running')
      setGoal('')
      setNewRunOpen(false)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      toast.error(msg.includes('409') ? 'An automation is already in progress.' : 'Failed to start.')
    }
  }

  async function handleStop() {
    if (!activeRunId) return
    await stopAutomationRun(activeRunId)
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
      toast.error('Could not load recording.')
    }
  }

  const pageContent = pageState === 'running' ? (
    <div className="flex min-h-0 flex-1 overflow-hidden bg-background">
      <div className="flex w-[300px] shrink-0 flex-col border-r border-border bg-card">
        <div className="border-b border-border px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Goal
        </div>
        <div className="flex flex-1 flex-col gap-3 p-4">
          <div className="rounded-lg border border-border bg-muted/50 p-3 text-[13px] leading-normal text-foreground">
            {activeGoal || 'Running…'}
          </div>
          <div className="flex w-fit items-center gap-2 rounded-full border border-blue-500/30 bg-blue-500/10 px-3 py-1">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-500" />
            <span className="text-[11px] text-blue-500">Running — {actions.length} actions</span>
          </div>
        </div>
        <div className="border-t border-border p-3">
          <Button
            type="button"
            variant="outline"
            className="w-full border-destructive/40 bg-destructive/10 text-destructive hover:bg-destructive/15 hover:text-destructive"
            onClick={handleStop}
          >
            <Square className="mr-2 h-3.5 w-3.5" />
            Stop Agent
          </Button>
        </div>
      </div>

      <div className="flex min-w-0 flex-1 flex-col bg-background">
        <div className="flex shrink-0 items-center gap-2.5 border-b border-border bg-card px-3 py-2">
          <div className="flex gap-1">
            <span className="h-2.5 w-2.5 rounded-full bg-destructive" />
            <span className="h-2.5 w-2.5 rounded-full bg-amber-400" />
            <span className="h-2.5 w-2.5 rounded-full bg-green-500" />
          </div>
          <div className="min-w-0 flex-1 truncate rounded-md border border-border bg-background px-3 py-1 text-xs text-muted-foreground">
            {currentUrl || 'Starting browser…'}
          </div>
          <div className="flex shrink-0 items-center gap-1.5 rounded-full border border-green-500/30 bg-green-500/10 px-2 py-0.5 text-[11px] text-green-500">
            <span className="h-1 w-1 animate-pulse rounded-full bg-green-500" />
            LIVE
          </div>
        </div>
        <div className="flex-1 overflow-hidden bg-black">
          {novncUrl ? (
            <iframe
              src={novncUrl}
              className="block h-full w-full border-0"
              title="Live browser"
            />
          ) : (
            <div className="flex h-full items-center justify-center text-[13px] text-muted-foreground">
              Connecting to browser…
            </div>
          )}
        </div>
      </div>

      <div className="flex w-[260px] shrink-0 flex-col border-l border-border bg-card">
        <div className="border-b border-border px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Activity
        </div>
        <div className="flex flex-1 flex-col gap-1.5 overflow-y-auto p-2.5">
          {actions.length === 0 && (
            <p className="mt-5 text-center text-xs italic text-muted-foreground">
              Waiting for agent…
            </p>
          )}
          {actions.map((action, i) => (
            <div
              key={action.id}
              className={cn(
                'flex gap-2 rounded-md border px-2.5 py-1.5 text-xs',
                i === actions.length - 1
                  ? 'border-blue-500/40 bg-blue-500/10'
                  : 'border-border bg-muted/50'
              )}
            >
              <span>{ACTION_ICON[action.type] ?? '•'}</span>
              <span
                className={cn(
                  'flex-1 leading-snug',
                  action.type === 'wiki_write' ? 'text-green-500' : 'text-foreground'
                )}
              >
                {action.detail}
              </span>
            </div>
          ))}
          <div ref={actionsEndRef} />
        </div>
      </div>
    </div>
  ) : (
    <div className="flex-1 overflow-y-auto bg-background p-6">
      <div className="mx-auto flex max-w-4xl flex-col gap-4">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-lg font-semibold text-foreground">Automations</h2>
          <Button type="button" onClick={() => setNewRunOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            New run
          </Button>
        </div>

        {runsLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-3/4" />
          </div>
        ) : runs.length === 0 ? (
          <EmptyState
            title="No automation runs yet"
            description='Start one with "New run".'
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Goal</TableHead>
                <TableHead className="w-[120px]">Status</TableHead>
                <TableHead className="w-[100px]">Duration</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.map(run => (
                <TableRow key={run.id}>
                  <TableCell className="max-w-0">
                    <span className="block truncate font-medium">{run.goal}</span>
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="outline"
                      className={cn('capitalize', statusBadgeClass(run.status))}
                    >
                      {run.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDuration(run)}
                  </TableCell>
                  <TableCell>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-7 w-7" aria-label="Run actions">
                          <MoreHorizontal className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => setActionsRunId(run.id)}>
                          View action log
                        </DropdownMenuItem>
                        {run.recording_url && !isActiveStatus(run.status) && (
                          <DropdownMenuItem onClick={() => handleWatch(run.id)}>
                            <Play className="mr-2 h-4 w-4" />
                            Watch recording
                          </DropdownMenuItem>
                        )}
                        {isActiveStatus(run.status) && (
                          <DropdownMenuItem
                            className="text-destructive focus:text-destructive"
                            onClick={() => handleForceStop(run.id)}
                          >
                            <Square className="mr-2 h-4 w-4" />
                            Force stop
                          </DropdownMenuItem>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  )

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex min-h-0 flex-1 overflow-hidden">{pageContent}</div>

      <Dialog open={newRunOpen} onOpenChange={setNewRunOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>New automation run</DialogTitle>
            <DialogDescription>
              Give the browser agent a goal. It will browse the web and can save findings to your wiki.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={goal}
            onChange={e => setGoal(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleStart()
            }}
            placeholder="e.g. Research the top 5 note-taking apps and save a comparison to tools/note-apps"
            rows={4}
            className="resize-none text-[13px] leading-normal"
          />
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setNewRunOpen(false)}>
              Cancel
            </Button>
            <Button type="button" onClick={handleStart} disabled={!goal.trim()}>
              Run
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ActionLogDialog runId={actionsRunId} onClose={() => setActionsRunId(null)} />
    </div>
  )
}

function ActionLogDialog({
  runId,
  onClose,
}: {
  runId: string | null
  onClose: () => void
}) {
  const [actions, setActions] = useState<AutomationAction[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!runId) {
      setActions([])
      return
    }
    setLoading(true)
    getAutomationRun(runId)
      .then(data => setActions(data.actions))
      .catch(() => setActions([]))
      .finally(() => setLoading(false))
  }, [runId])

  return (
    <Dialog open={runId !== null} onOpenChange={open => !open && onClose()}>
      <DialogContent className="flex max-h-[80vh] max-w-2xl flex-col">
        <DialogHeader>
          <DialogTitle>Action log</DialogTitle>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {loading && (
            <p className="text-sm italic text-muted-foreground">Loading…</p>
          )}
          {!loading && actions.length === 0 && (
            <p className="text-sm italic text-muted-foreground">No actions recorded.</p>
          )}
          <div className="flex flex-col gap-2">
            {actions.map(a => (
              <div key={a.id} className="flex gap-2.5 text-xs">
                <span className="w-11 shrink-0 text-muted-foreground">
                  {new Date(a.timestamp).toLocaleTimeString([], {
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </span>
                <span>{ACTION_ICON[a.type] ?? '•'}</span>
                <span
                  className={cn(
                    'flex-1 leading-snug',
                    a.type === 'wiki_write' ? 'text-green-500' : 'text-muted-foreground'
                  )}
                >
                  {a.detail}
                </span>
              </div>
            ))}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
