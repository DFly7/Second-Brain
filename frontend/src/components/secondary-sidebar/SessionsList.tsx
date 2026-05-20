import { useCallback, useEffect, useMemo, useState } from 'react'
import { cn } from '@/lib/utils'
import { listSessions } from '@/api/client'
import { SecondarySidebar } from './SecondarySidebar'

const SESSION_KEY = 'chat_session_id'
const SELECT_SESSION_EVENT = 'chat:select-session'

interface Session {
  id: string
  created_at: string
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

function dateGroupLabel(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const day = startOfDay(d)
  if (day === startOfDay(now)) return 'Today'
  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  if (day === startOfDay(yesterday)) return 'Yesterday'
  return d.toLocaleDateString(undefined, {
    weekday: 'long',
    month: 'short',
    day: 'numeric',
  })
}

function sessionTimeLabel(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function groupByDate(sessions: Session[]): [string, Session[]][] {
  const order: string[] = []
  const map = new Map<string, Session[]>()
  for (const s of sessions) {
    const label = dateGroupLabel(s.created_at)
    if (!map.has(label)) {
      map.set(label, [])
      order.push(label)
    }
    map.get(label)!.push(s)
  }
  return order.map((label) => [label, map.get(label)!])
}

function selectChatSession(id: string) {
  localStorage.setItem(SESSION_KEY, id)
  window.dispatchEvent(new CustomEvent(SELECT_SESSION_EVENT, { detail: { id } }))
}

export function SessionsList() {
  const [filter, setFilter] = useState('')
  const [sessions, setSessions] = useState<Session[]>([])
  const [loadError, setLoadError] = useState(false)
  const [activeId, setActiveId] = useState<string | undefined>(
    () => localStorage.getItem(SESSION_KEY) ?? undefined,
  )

  const loadSessions = useCallback(() => {
    listSessions()
      .then((data) => {
        setSessions(data)
        setLoadError(false)
      })
      .catch(() => {
        setSessions([])
        setLoadError(true)
      })
  }, [])

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  useEffect(() => {
    const onSelect = (e: Event) => {
      const id = (e as CustomEvent<{ id: string }>).detail?.id
      if (id) setActiveId(id)
    }
    const onStorage = () => {
      setActiveId(localStorage.getItem(SESSION_KEY) ?? undefined)
    }
    window.addEventListener(SELECT_SESSION_EVENT, onSelect)
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener(SELECT_SESSION_EVENT, onSelect)
      window.removeEventListener('storage', onStorage)
    }
  }, [])

  const filtered = useMemo(() => {
    if (!filter) return sessions
    const q = filter.toLowerCase()
    return sessions.filter((s) => {
      const label = `${dateGroupLabel(s.created_at)} ${sessionTimeLabel(s.created_at)}`
      return label.toLowerCase().includes(q)
    })
  }, [sessions, filter])

  const groups = useMemo(() => groupByDate(filtered), [filtered])

  return (
    <SecondarySidebar title="Sessions" search={filter} onSearchChange={setFilter}>
      <div className="p-1">
        {loadError && (
          <p className="px-2 py-3 text-xs text-destructive">Failed to load sessions.</p>
        )}
        {!loadError && sessions.length === 0 && (
          <p className="px-2 py-3 text-xs text-muted-foreground">No previous chats.</p>
        )}
        {!loadError && sessions.length > 0 && filtered.length === 0 && (
          <p className="px-2 py-3 text-xs text-muted-foreground">No matches.</p>
        )}
        {groups.map(([label, group]) => (
          <div key={label} className="mb-1">
            <div className="px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
              {label}
            </div>
            {group.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => selectChatSession(s.id)}
                className={cn(
                  'flex h-7 w-full items-center rounded-sm px-2 text-left text-[13px] text-muted-foreground hover:bg-muted hover:text-foreground',
                  activeId === s.id && 'bg-muted text-foreground before:mr-1 before:h-4 before:w-0.5 before:rounded-r before:bg-primary',
                )}
              >
                <span className="truncate">{sessionTimeLabel(s.created_at)}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
    </SecondarySidebar>
  )
}
