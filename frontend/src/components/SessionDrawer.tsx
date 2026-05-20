import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface Session { id: string; created_at: string }

interface SessionDrawerProps {
  open: boolean
  sessions: Session[]
  loadError: boolean
  activeSessionId: string | undefined
  onSelect: (id: string) => void
  onNewChat: () => void
  onClose: () => void
}

function formatSessionDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export default function SessionDrawer({
  open,
  sessions,
  loadError,
  activeSessionId,
  onSelect,
  onNewChat,
  onClose,
}: SessionDrawerProps) {
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="flex w-96 flex-col gap-0 p-0 sm:max-w-none">
        <SheetHeader className="border-b px-6 py-4 text-left">
          <SheetTitle>Sessions</SheetTitle>
        </SheetHeader>
        <div className="border-b px-4 py-3">
          <Button className="w-full justify-start" onClick={onNewChat}>
            + New Chat
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {loadError && (
            <p className="px-2 py-2 text-xs text-destructive">Failed to load history</p>
          )}
          {!loadError && sessions.length === 0 && (
            <p className="px-2 py-2 text-xs text-muted-foreground">No previous chats</p>
          )}
          {sessions.map((s) => (
            <Button
              key={s.id}
              variant="ghost"
              className={cn(
                'mb-0.5 h-auto w-full justify-start px-3 py-2 text-xs font-normal',
                s.id === activeSessionId && 'bg-accent text-accent-foreground',
              )}
              onClick={() => onSelect(s.id)}
            >
              {formatSessionDate(s.created_at)}
            </Button>
          ))}
        </div>
      </SheetContent>
    </Sheet>
  )
}
