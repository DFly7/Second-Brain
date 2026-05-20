import { useEffect, useRef, useState } from 'react'
import type React from 'react'
import { ingestText, ingestUrl, ingestFile } from '../api/client'
import { useQueryClient } from '@tanstack/react-query'
import type { QueueItem, QueueState, QueueStatus } from '../state/ingestQueue'
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'
import { toast } from '@/lib/toast'

const STATUS_LABEL: Record<QueueStatus, string> = {
  pending: 'Pending',
  uploading: 'Uploading…',
  queued: 'Queued…',
  converting: 'Converting…',
  processing: 'Processing…',
  done: 'Done ✓',
  error: 'Error ✗',
}

const STATUS_CLASS: Record<QueueStatus, string> = {
  pending: 'text-muted-foreground',
  uploading: 'text-blue-500',
  queued: 'text-purple-500',
  converting: 'text-amber-500',
  processing: 'text-amber-500',
  done: 'text-green-500',
  error: 'text-destructive',
}

type IngestModalProps = {
  onClose: () => void
  queue: QueueState
  onUpsertQueueItems: (items: QueueItem[]) => void
  onPatchQueueById: (id: string, patch: Partial<QueueItem>) => void
}

export default function IngestModal(props: IngestModalProps) {
  const { onClose, queue, onUpsertQueueItems, onPatchQueueById } = props
  const [tab, setTab] = useState<'text' | 'url' | 'file'>('text')
  const [text, setText] = useState('')
  const [url, setUrl] = useState('')
  const [orderedFileIds, setOrderedFileIds] = useState<string[]>([])
  const filesByIdRef = useRef<Map<string, File>>(new Map())
  const [uploading, setUploading] = useState(false)
  const [textUrlSubmitting, setTextUrlSubmitting] = useState(false)
  const onCloseRef = useRef(onClose)
  const qc = useQueryClient()

  onCloseRef.current = onClose

  useEffect(() => {
    if (orderedFileIds.length === 0) return
    const allTerminal = orderedFileIds.every(id => {
      const item = queue.items.find(i => i.id === id)
      return item && (item.status === 'done' || item.status === 'error')
    })
    if (!allTerminal) return
    qc.invalidateQueries({ queryKey: ['pages'] })
    const timer = setTimeout(() => onCloseRef.current(), 2000)
    return () => clearTimeout(timer)
  }, [orderedFileIds, queue, qc])

  async function submitTextOrUrl() {
    if (textUrlSubmitting) return
    setTextUrlSubmitting(true)
    try {
      if (tab === 'text') await ingestText(text)
      else if (tab === 'url') await ingestUrl(url)
      toast.success('Ingested! Agent is updating your wiki.')
      qc.invalidateQueries({ queryKey: ['activity'] })
      setTimeout(() => onCloseRef.current(), 1500)
    } catch {
      toast.error('Failed — check the console.')
    } finally {
      setTextUrlSubmitting(false)
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || [])
    const ids = files.map(() => crypto.randomUUID())
    const map = new Map<string, File>()
    files.forEach((file, i) => map.set(ids[i], file))
    filesByIdRef.current = map
    setOrderedFileIds(ids)
    onUpsertQueueItems(
      files.map((file, i) => ({
        id: ids[i],
        fileName: file.name,
        fileSize: file.size,
        createdAt: new Date().toISOString(),
        status: 'pending',
      })),
    )
  }

  async function uploadAll() {
    if (uploading || orderedFileIds.length === 0) return
    setUploading(true)
    for (const id of orderedFileIds) {
      onPatchQueueById(id, { status: 'uploading' })
      const file = filesByIdRef.current.get(id)
      if (!file) continue
      try {
        const resp = await ingestFile(file)
        onPatchQueueById(id, { sourceId: resp.source_id, status: 'queued' })
      } catch {
        onPatchQueueById(id, { status: 'error', error: 'Upload failed' })
      }
    }
    setUploading(false)
  }

  return (
    <Dialog open onOpenChange={open => !open && onClose()}>
      <DialogContent className="flex max-h-[90vh] max-w-lg flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="px-6 pt-6">
          <DialogTitle>Ingest</DialogTitle>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-4">
          <Tabs
            value={tab}
            onValueChange={v => setTab(v as 'text' | 'url' | 'file')}
          >
            <TabsList className="mb-4 w-full">
              {(['text', 'url', 'file'] as const).map(t => (
                <TabsTrigger key={t} value={t} className="flex-1 capitalize">
                  {t}
                </TabsTrigger>
              ))}
            </TabsList>

            <TabsContent value="text">
              <Textarea
                value={text}
                onChange={e => setText(e.target.value)}
                placeholder="Paste any text, note, or idea…"
                rows={6}
              />
            </TabsContent>

            <TabsContent value="url">
              <Input
                value={url}
                onChange={e => setUrl(e.target.value)}
                placeholder="https://…"
              />
            </TabsContent>

            <TabsContent value="file">
              <Input
                type="file"
                multiple
                accept=".pdf,.docx,.md,.markdown,.txt,.png,.jpg,.jpeg,.webp"
                onChange={handleFileChange}
                className="mb-3"
              />
              {orderedFileIds.length > 0 && (
                <div className="flex flex-col gap-1.5">
                  {orderedFileIds.map(fid => {
                    const entry = queue.items.find(i => i.id === fid)
                    const qs: QueueStatus = entry?.status ?? 'pending'
                    const name =
                      entry?.fileName ??
                      filesByIdRef.current.get(fid)?.name ??
                      fid
                    return (
                      <div
                        key={fid}
                        className="flex items-center justify-between rounded-md border bg-muted/30 px-2.5 py-1.5"
                      >
                        <span className="max-w-[320px] truncate text-xs">
                          {name}
                        </span>
                        <span
                          className={cn(
                            'ml-2 shrink-0 text-[11px]',
                            STATUS_CLASS[qs],
                          )}
                        >
                          {STATUS_LABEL[qs]}
                        </span>
                      </div>
                    )
                  })}
                </div>
              )}
            </TabsContent>
          </Tabs>
        </div>

        <DialogFooter className="shrink-0 border-t px-6 py-4 sm:justify-stretch">
          {tab === 'file' ? (
            orderedFileIds.length > 0 ? (
              <Button
                type="button"
                className="w-full"
                onClick={() => void uploadAll()}
                disabled={uploading}
              >
                {uploading
                  ? 'Uploading…'
                  : `Upload ${orderedFileIds.length} file${orderedFileIds.length !== 1 ? 's' : ''}`}
              </Button>
            ) : null
          ) : (
            <Button
              type="button"
              className="w-full"
              onClick={() => void submitTextOrUrl()}
              disabled={textUrlSubmitting}
            >
              Ingest
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
