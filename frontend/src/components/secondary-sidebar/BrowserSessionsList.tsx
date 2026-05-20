import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { listBrowserChatSessions, type BrowserChatSession } from '@/api/client'
import { useSse } from '@/hooks/useSse'
import { SecondarySidebar } from './SecondarySidebar'

function sessionLabel(s: BrowserChatSession): string {
  const when = new Date(s.created_at).toLocaleString([], {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
  const status = s.status === 'active' ? 'Active' : 'Completed'
  return `${when} · ${status}`
}

function browserSessionHref(sessionId: string): string {
  return `/browser-chat?session=${encodeURIComponent(sessionId)}`
}

export function BrowserSessionsList() {
  const [filter, setFilter] = useState('')
  const [searchParams] = useSearchParams()
  const activeId = searchParams.get('session')
  const [sessions, setSessions] = useState<BrowserChatSession[]>([])

  const loadSessions = useCallback(() => {
    listBrowserChatSessions()
      .then(setSessions)
      .catch(() => setSessions([]))
  }, [])

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  useSse((data: unknown) => {
    const ev = data as Record<string, unknown>
    if (
      ev.event === 'browser_chat:action' ||
      ev.event === 'browser_chat:reply' ||
      ev.event === 'browser_chat:status'
    ) {
      loadSessions()
    }
  })

  const items = useMemo(
    () =>
      sessions.map((s) => ({
        id: s.id,
        name: sessionLabel(s),
        href: browserSessionHref(s.id),
      })),
    [sessions],
  )

  const filtered = filter
    ? items.filter((i) => i.name.toLowerCase().includes(filter.toLowerCase()))
    : items

  return (
    <SecondarySidebar title="Browser" search={filter} onSearchChange={setFilter}>
      <div className="p-1">
        {filtered.length === 0 && (
          <p className="px-2 py-3 text-xs text-muted-foreground">
            {sessions.length === 0 ? 'No browser sessions yet.' : 'No matches.'}
          </p>
        )}
        {filtered.map((i) => (
          <Link
            key={i.id}
            to={i.href}
            className={cn(
              'flex h-7 items-center rounded-sm px-2 text-[13px] text-muted-foreground hover:bg-muted hover:text-foreground',
              activeId === i.id && 'bg-muted text-foreground before:mr-1 before:h-4 before:w-0.5 before:rounded-r before:bg-primary',
            )}
          >
            <span className="truncate">{i.name}</span>
          </Link>
        ))}
      </div>
    </SecondarySidebar>
  )
}
