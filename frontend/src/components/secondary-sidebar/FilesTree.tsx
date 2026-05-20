import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { useSources } from '@/hooks/useSources'
import { EmptyState } from '@/components/EmptyState'
import { ListSkeleton } from '@/components/ListSkeleton'
import { SecondarySidebar } from './SecondarySidebar'

function sourceLabel(
  source: { title: string | null; kind: string; id: string },
): string {
  return source.title ?? `${source.kind} · ${source.id.slice(0, 8).toUpperCase()}`
}

function filesHref(sourceId: string): string {
  return `/files?source=${encodeURIComponent(sourceId)}`
}

export function FilesTree() {
  const [filter, setFilter] = useState('')
  const [searchParams] = useSearchParams()
  const activeId = searchParams.get('source')
  const { data: sources, isPending: loading } = useSources()

  const items = useMemo(
    () =>
      (sources ?? []).map((s) => ({
        id: s.id,
        name: sourceLabel(s),
        href: filesHref(s.id),
      })),
    [sources],
  )

  const filtered = filter
    ? items.filter((i) => i.name.toLowerCase().includes(filter.toLowerCase()))
    : items

  return (
    <SecondarySidebar title="Files" search={filter} onSearchChange={setFilter}>
      <div className="p-1">
        {loading && <ListSkeleton />}
        {!loading && filtered.length === 0 && (
          <EmptyState
            className="min-h-[6rem] p-4"
            title={(sources ?? []).length === 0 ? 'No files yet' : 'No matches'}
            description={
              (sources ?? []).length === 0
                ? 'Upload documents from the ingest panel.'
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
                'flex h-7 items-center rounded-sm px-2 text-[13px] text-muted-foreground hover:bg-muted hover:text-foreground',
                activeId === i.id &&
                  'bg-muted text-foreground before:mr-1 before:h-4 before:w-0.5 before:rounded-r before:bg-primary',
              )}
            >
              <span className="truncate">{i.name}</span>
            </Link>
          ))}
      </div>
    </SecondarySidebar>
  )
}
