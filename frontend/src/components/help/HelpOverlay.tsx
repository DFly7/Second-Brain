import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { shortcuts } from './shortcuts'

export function HelpOverlay({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const groups = Array.from(new Set(shortcuts.map((s) => s.group)))
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader><DialogTitle>Keyboard shortcuts</DialogTitle></DialogHeader>
        <div className="space-y-6">
          {groups.map((g) => (
            <section key={g}>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{g}</h3>
              <div className="space-y-1">
                {shortcuts.filter((s) => s.group === g).map((s) => (
                  <div key={s.id} className="flex items-center justify-between text-sm">
                    <span>{s.description}</span>
                    <Badge variant="outline" className="font-mono">{s.keys}</Badge>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
