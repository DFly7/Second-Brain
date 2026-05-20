import { type ReactNode } from 'react'
import { Search } from 'lucide-react'
import { Button } from '@/components/ui/button'

type Crumb = { label: string; href?: string }

export function ContextBar({
  breadcrumbs = [],
  actions,
  onOpenPalette,
}: {
  breadcrumbs?: Crumb[]
  actions?: ReactNode
  onOpenPalette?: () => void
}) {
  return (
    <header className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-border bg-background px-4">
      <nav className="flex items-center gap-1 text-sm text-muted-foreground">
        {breadcrumbs.map((c, i) => (
          <span key={i} className="flex items-center gap-1">
            {i > 0 && <span className="text-muted-foreground/50">/</span>}
            {c.href ? (
              <a
                href={c.href}
                className="rounded-sm hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background"
              >
                {c.label}
              </a>
            ) : (
              <span className={i === breadcrumbs.length - 1 ? 'text-foreground' : ''}>{c.label}</span>
            )}
          </span>
        ))}
      </nav>
      <div className="flex items-center gap-1">
        {actions}
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-2 text-xs text-muted-foreground"
          aria-label="Open command palette"
          onClick={onOpenPalette}
        >
          <Search className="h-3.5 w-3.5" />
          <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">⌘K</span>
        </Button>
      </div>
    </header>
  )
}
