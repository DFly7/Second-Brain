import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { getAutomationRuns, type AutomationRun } from '@/api/client'
import { useSse } from '@/hooks/useSse'
import { EmptyState } from '@/components/EmptyState'
import { ListSkeleton } from '@/components/ListSkeleton'
import { SecondarySidebar } from './SecondarySidebar'

export function AutomationsList() {
  const [filter, setFilter] = useState('')
  const { pathname } = useLocation()
  const [runs, setRuns] = useState<AutomationRun[]>([])
  const [loading, setLoading] = useState(true)

  const loadRuns = useCallback(() => {
    setLoading(true)
    getAutomationRuns()
      .then(setRuns)
      .catch(() => setRuns([]))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    loadRuns()
  }, [loadRuns])

  useSse((data: unknown) => {
    const ev = data as Record<string, unknown>
    if (ev.event === 'automation:status' || ev.event === 'automation:action') {
      loadRuns()
    }
  })

  const items = useMemo(
    () =>
      runs.map((r) => ({
        id: r.id,
        name: r.goal,
        href: '/automations',
        status: r.status,
      })),
    [runs],
  )

  const filtered = filter
    ? items.filter(
        (i) =>
          i.name.toLowerCase().includes(filter.toLowerCase()) ||
          i.status.toLowerCase().includes(filter.toLowerCase()),
      )
    : items

  return (
    <SecondarySidebar title="Automations" search={filter} onSearchChange={setFilter}>
      <div className="p-1">
        {loading && <ListSkeleton />}
        {!loading && filtered.length === 0 && (
          <EmptyState
            className="min-h-[6rem] p-4"
            title={runs.length === 0 ? 'No automation runs yet' : 'No matches'}
            description={
              runs.length === 0
                ? 'Start a run from the Automations page.'
                : 'Try a different search term.'
            }
          />
        )}
        {!loading &&
          filtered.map((i) => (
            <Link
              key={i.id}
              to={i.href}
              className={cn(
                'flex h-7 items-center gap-2 rounded-sm px-2 text-[13px] text-muted-foreground hover:bg-muted hover:text-foreground',
                pathname === i.href && 'bg-muted text-foreground',
              )}
            >
              <span className="min-w-0 flex-1 truncate">{i.name}</span>
              <span className="shrink-0 text-[10px] capitalize opacity-60">{i.status}</span>
            </Link>
          ))}
      </div>
    </SecondarySidebar>
  )
}
