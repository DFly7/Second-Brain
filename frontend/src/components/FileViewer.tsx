import { useState, useEffect } from 'react'
import type React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { fetchSourceFile, fetchSourceImage } from '../api/client'
import { useSourceMarkdown } from '../hooks/useSources'
import type { SourceItem } from '../hooks/useSources'

const IMAGE_KINDS = ['png', 'jpg', 'jpeg', 'webp']
const NO_FILE_KINDS = ['url', 'text', 'md', 'markdown', 'txt']

interface FileViewerProps {
  source: SourceItem | null
  onClose?: () => void
  /** @deprecated use onClose */
  onBack?: () => void
  /** Render inline (no dialog wrapper) — use when embedding in a panel */
  inline?: boolean
}

export default function FileViewer({ source, onClose, onBack, inline }: FileViewerProps) {
  const handleClose = onClose ?? onBack
  const defaultView = (s: SourceItem | null) =>
    s?.has_markdown ? 'markdown' : 'original'

  const [view, setView] = useState<'original' | 'markdown'>(() => defaultView(source))
  const [blobUrl, setBlobUrl] = useState<string | null>(null)

  useEffect(() => {
    setView(defaultView(source))
    setBlobUrl(null)
  }, [source?.id])

  if (!source) return null

  const showToggle = source.has_file && source.has_markdown
  const filename = source.filename ?? `file.${source.kind}`
  const title =
    source.title ?? `${source.kind} · ${source.id.slice(0, 8).toUpperCase()}`

  const header = (
    <div className="flex shrink-0 flex-row items-center gap-2 border-b px-4 py-2">
      <span className="min-w-0 flex-1 truncate text-sm font-semibold">{title}</span>
      {view === 'original' && blobUrl && (
        <div className="flex shrink-0 gap-2">
          <Button variant="outline" size="sm" asChild>
            <a href={blobUrl} download={filename}>Download</a>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <a href={blobUrl} target="_blank" rel="noreferrer">Open</a>
          </Button>
        </div>
      )}
      {showToggle && (
        <div className="flex shrink-0 gap-0.5 rounded-md bg-muted p-0.5">
          {(['original', 'markdown'] as const).map((v) => (
            <Button
              key={v}
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setView(v)}
              className={cn(
                'h-7 px-2.5 text-[11px] font-semibold',
                view === v
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:bg-transparent',
              )}
            >
              {v === 'original' ? 'Original' : 'Markdown'}
            </Button>
          ))}
        </div>
      )}
      {inline && handleClose && (
        <Button variant="ghost" size="sm" className="ml-1 h-7 px-2 text-muted-foreground" onClick={handleClose}>
          ✕
        </Button>
      )}
    </div>
  )

  const body = (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {view === 'markdown' ? (
        <MarkdownPane source={source} />
      ) : (
        <OriginalPane source={source} onBlobUrl={setBlobUrl} />
      )}
    </div>
  )

  if (inline) {
    return (
      <div className="flex h-full flex-col overflow-hidden border-l border-border bg-background">
        {header}
        {body}
      </div>
    )
  }

  return (
    <Dialog open onOpenChange={(o) => !o && handleClose?.()}>
      <DialogContent className="flex h-[80vh] max-w-4xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="space-y-0 p-0">{header}</DialogHeader>
        {body}
      </DialogContent>
    </Dialog>
  )
}

function isProcessingStatus(status: string): boolean {
  return status === 'converting' || status === 'ingesting' || status === 'processing'
}

function AuthedImg({ src, alt, sourceId }: { src?: string; alt?: string; sourceId: string }) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  const isExternal = !src || src.startsWith('http') || src.startsWith('data:')

  useEffect(() => {
    if (isExternal || !src) return
    let url: string | null = null
    fetchSourceImage(sourceId, src)
      .then((blob) => {
        url = URL.createObjectURL(blob)
        setBlobUrl(url)
      })
      .catch(() => setFailed(true))
    return () => {
      if (url) URL.revokeObjectURL(url)
    }
  }, [src, sourceId, isExternal])

  if (!src) return null
  if (isExternal) return <img src={src} alt={alt ?? ''} className="max-w-full rounded" />
  if (failed) return <span className="text-xs text-muted-foreground">[image unavailable]</span>
  if (!blobUrl) return <span className="text-xs text-muted-foreground">[loading image…]</span>
  return <img src={blobUrl} alt={alt ?? ''} className="max-w-full rounded" />
}

const imgComponents = (sourceId: string): React.ComponentProps<typeof ReactMarkdown>['components'] => ({
  img: ({ src, alt }) => <AuthedImg src={src} alt={alt} sourceId={sourceId} />,
})

function MarkdownPane({ source }: { source: SourceItem }) {
  const [rawMode, setRawMode] = useState(false)
  const canFetch = source.status === 'done' && source.has_markdown
  const { data: markdown, isLoading, isError, refetch } = useSourceMarkdown(source.id, canFetch)

  if (isProcessingStatus(source.status)) {
    return <Centered>Still processing…</Centered>
  }
  if (source.status === 'error') {
    return <Centered>Conversion failed — no markdown available.</Centered>
  }
  if (!source.has_markdown) {
    return <Centered>No markdown available yet.</Centered>
  }
  if (isLoading) {
    return (
      <div className="space-y-3 p-6">
        <Skeleton className="h-6 w-1/3" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-4/5" />
        <Skeleton className="h-4 w-3/5" />
      </div>
    )
  }
  if (isError) {
    return (
      <Centered>
        Could not load file.{' '}
        <Button type="button" variant="outline" size="sm" onClick={() => refetch()}>
          Retry
        </Button>
      </Centered>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex shrink-0 items-center gap-2 border-b bg-muted/30 px-4 py-1.5">
        <span className="text-sm font-semibold text-foreground">
          {source.filename ?? source.kind} — markdown
        </span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="ml-auto"
          onClick={() => setRawMode((m) => !m)}
        >
          {rawMode ? 'Rendered' : 'Raw'}
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        {rawMode ? (
          <pre className="whitespace-pre-wrap break-words text-[13px] leading-relaxed text-foreground">
            {markdown}
          </pre>
        ) : (
          <article className="prose prose-invert prose-zinc max-w-3xl">
            <ReactMarkdown
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={[rehypeKatex]}
              components={imgComponents(source.id)}
            >
              {markdown ?? ''}
            </ReactMarkdown>
          </article>
        )}
      </div>
    </div>
  )
}

function OriginalPane({ source, onBlobUrl }: { source: SourceItem; onBlobUrl: (url: string | null) => void }) {
  const needsFetch = !NO_FILE_KINDS.includes(source.kind) && source.has_file
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(needsFetch)
  const [progress, setProgress] = useState<{ received: number; total: number | null } | null>(null)
  const [error, setError] = useState(false)
  const [retryCount, setRetryCount] = useState(0)

  useEffect(() => {
    if (!needsFetch) return
    let objectUrl: string | null = null
    setLoading(true)
    setError(false)
    setBlobUrl(null)
    onBlobUrl(null)
    setProgress(null)

    fetchSourceFile(source.id, (received, total) => setProgress({ received, total }))
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob)
        setBlobUrl(objectUrl)
        onBlobUrl(objectUrl)
        setLoading(false)
        setProgress(null)
      })
      .catch(() => {
        setError(true)
        setLoading(false)
        setProgress(null)
      })

    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl)
      onBlobUrl(null)
    }
  }, [source.id, source.kind, source.has_file, needsFetch, retryCount])

  if (NO_FILE_KINDS.includes(source.kind)) {
    return <Centered>Web or text source — no original file to display.</Centered>
  }
  if (!source.has_file) return <Centered>No original file.</Centered>
  if (loading) return <LoadingBar progress={progress} />
  if (error) {
    return (
      <Centered>
        Could not load file.{' '}
        <Button type="button" variant="outline" size="sm" onClick={() => setRetryCount((c) => c + 1)}>
          Retry
        </Button>
      </Centered>
    )
  }

  const filename = source.filename ?? `file.${source.kind}`

  if (blobUrl && source.kind === 'pdf') {
    return (
      <iframe
        src={blobUrl}
        className="block h-full min-h-0 w-full flex-1 border-0"
        title={filename}
      />
    )
  }
  if (blobUrl && IMAGE_KINDS.includes(source.kind)) {
    return (
      <div className="flex min-h-0 flex-1 items-start justify-center overflow-y-auto p-4">
        <img src={blobUrl} alt={filename} className="max-w-full" />
      </div>
    )
  }
  return <Centered>This file type cannot be previewed. Use Download or Open to view it.</Centered>
}

function LoadingBar({ progress }: { progress: { received: number; total: number | null } | null }) {
  const pct = progress?.total ? Math.round((progress.received / progress.total) * 100) : null
  const label = progress
    ? pct !== null
      ? `${pct}% — ${fmt(progress.received)} / ${fmt(progress.total!)}`
      : `${fmt(progress.received)} received…`
    : 'Connecting…'

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3">
      <div className="h-1.5 w-64 overflow-hidden rounded bg-muted">
        {pct !== null ? (
          <div
            className="h-full rounded bg-primary transition-[width] duration-100"
            style={{ width: `${pct}%` }}
          />
        ) : (
          <div className="h-full w-full animate-pulse bg-primary/60" />
        )}
      </div>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  )
}

function fmt(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-1 items-center justify-center gap-2 text-[13px] text-muted-foreground">
      {children}
    </div>
  )
}
