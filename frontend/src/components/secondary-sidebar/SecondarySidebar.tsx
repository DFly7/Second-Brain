import { type ReactNode } from 'react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Plus, Search } from 'lucide-react'

export function SecondarySidebar({
  title,
  primaryAction,
  onPrimaryAction,
  search,
  onSearchChange,
  children,
}: {
  title: string
  primaryAction?: string
  onPrimaryAction?: () => void
  search?: string
  onSearchChange?: (v: string) => void
  children: ReactNode
}) {
  return (
    <aside className="flex h-full flex-col border-r border-border bg-background">
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-border px-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</h2>
        {primaryAction && (
          <Button variant="ghost" size="sm" className="h-6 gap-1 px-2 text-xs" onClick={onPrimaryAction}>
            <Plus className="h-3 w-3" />
            {primaryAction}
          </Button>
        )}
      </div>
      {onSearchChange && (
        <div className="border-b border-border p-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search ?? ''}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder="Filter…"
              className="h-7 pl-7 text-xs"
            />
          </div>
        </div>
      )}
      <div className="flex-1 overflow-y-auto">{children}</div>
    </aside>
  )
}
