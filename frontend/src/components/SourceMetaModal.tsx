import { useState, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { SourceItem } from '../api/client'
import { patchSource } from '../api/client'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/lib/toast'

interface SourceMetaModalProps {
  source: SourceItem
  onClose: () => void
}

export default function SourceMetaModal({ source, onClose }: SourceMetaModalProps) {
  const [title, setTitle] = useState(source.title ?? '')
  const [description, setDescription] = useState(source.description ?? '')
  const [saving, setSaving] = useState(false)
  const qc = useQueryClient()

  useEffect(() => {
    setTitle(source.title ?? '')
    setDescription(source.description ?? '')
  }, [source.id])

  async function handleSave() {
    setSaving(true)
    try {
      await patchSource(source.id, { title: title || undefined, description: description || undefined })
      qc.invalidateQueries({ queryKey: ['sources'] })
      toast.success('Saved')
      onClose()
    } catch {
      toast.error('Failed to save. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>File info</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <label className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Title
            </label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="File title"
            />
          </div>

          <div className="space-y-2">
            <label className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Description
            </label>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="One sentence summary"
              rows={3}
            />
          </div>

          <div className="space-y-2 border-t border-border pt-4">
            {source.filename && (
              <MetaRow label="Original filename" value={source.filename} />
            )}
            <MetaRow label="Type" value={source.kind.toUpperCase()} />
            <MetaRow label="Status" value={source.status} />
            <MetaRow label="Ingested" value={new Date(source.created_at).toLocaleString()} />
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => void handleSave()} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2 text-xs">
      <span className="min-w-[120px] shrink-0 text-muted-foreground">{label}</span>
      <span className="truncate text-muted-foreground">{value}</span>
    </div>
  )
}
