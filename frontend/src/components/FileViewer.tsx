import { useState, useEffect } from 'react'
import type React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import 'github-markdown-css/github-markdown-dark.css'
import { fetchSourceFile, fetchSourceImage } from '../api/client'
import { useSourceMarkdown } from '../hooks/useSources'
import type { SourceItem } from '../hooks/useSources'

const IMAGE_KINDS = ['png', 'jpg', 'jpeg', 'webp']
const NO_FILE_KINDS = ['url', 'text', 'md', 'markdown', 'txt']

interface FileViewerProps {
  source: SourceItem | null
}

export default function FileViewer({ source }: FileViewerProps) {
  const defaultView = (s: SourceItem | null) =>
    s?.has_markdown ? 'markdown' : 'original'

  const [view, setView] = useState<'original' | 'markdown'>(() => defaultView(source))
  const [blobUrl, setBlobUrl] = useState<string | null>(null)

  useEffect(() => {
    setView(defaultView(source))
    setBlobUrl(null)
  }, [source?.id])

  if (!source) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#8b949e', fontSize: 13 }}>
        Select a file to view it.
      </div>
    )
  }

  const showToggle = source.has_file && source.has_markdown
  const filename = source.filename ?? `file.${source.kind}`

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 14px',
        borderBottom: '1px solid #21262d',
        flexShrink: 0,
      }}>
        <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: '#e6edf3', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {source.title ?? `${source.kind} · ${source.id.slice(0, 8).toUpperCase()}`}
        </span>
        {view === 'original' && blobUrl && (
          <div style={{ display: 'flex', gap: 6 }}>
            <a href={blobUrl} download={filename} style={linkBtnStyle}>⬇ Download</a>
            <a href={blobUrl} target="_blank" rel="noreferrer" style={linkBtnStyle}>↗ Open</a>
          </div>
        )}
        {showToggle && (
          <div style={{ display: 'flex', background: '#21262d', borderRadius: 6, padding: 2, gap: 2 }}>
            {(['original', 'markdown'] as const).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => setView(v)}
                style={{
                  padding: '3px 10px',
                  borderRadius: 4,
                  border: 'none',
                  cursor: 'pointer',
                  fontSize: 11,
                  fontWeight: 600,
                  background: view === v ? '#0d1117' : 'transparent',
                  color: view === v ? '#e6edf3' : '#6e7681',
                  boxShadow: view === v ? '0 1px 3px rgba(0,0,0,0.4)' : 'none',
                }}
              >
                {v === 'original' ? 'Original' : 'Markdown'}
              </button>
            ))}
          </div>
        )}
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {view === 'markdown'
          ? <MarkdownPane source={source} />
          : <OriginalPane source={source} onBlobUrl={setBlobUrl} />}
      </div>
    </div>
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
  if (isExternal) return <img src={src} alt={alt ?? ''} style={{ maxWidth: '100%', borderRadius: 4 }} />
  if (failed) return <span style={{ color: '#6e7681', fontSize: 12 }}>[image unavailable]</span>
  if (!blobUrl) return <span style={{ color: '#6e7681', fontSize: 12 }}>[loading image…]</span>
  return <img src={blobUrl} alt={alt ?? ''} style={{ maxWidth: '100%', borderRadius: 4 }} />
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
  if (isLoading) return <Centered>Loading…</Centered>
  if (isError) {
    return (
      <Centered>
        Could not load file.{' '}
        <button type="button" onClick={() => refetch()} style={btnStyle}>
          Retry
        </button>
      </Centered>
    )
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 16px', borderBottom: '1px solid #21262d', background: '#161b22', flexShrink: 0 }}>
        <span style={{ color: '#e6edf3', fontWeight: 600 }}>
          {source.filename ?? source.kind} — markdown
        </span>
        <button type="button" onClick={() => setRawMode((m) => !m)} style={{ ...btnStyle, marginLeft: 'auto' }}>
          {rawMode ? 'Rendered' : 'Raw'}
        </button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: 24 }}>
        {rawMode ? (
          <pre
            style={{
              color: '#c9d1d9',
              fontSize: 13,
              lineHeight: 1.6,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {markdown}
          </pre>
        ) : (
          <div className="markdown-body" style={{ maxWidth: 800 }}>
            <ReactMarkdown
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={[rehypeKatex]}
              components={imgComponents(source.id)}
            >
              {markdown ?? ''}
            </ReactMarkdown>
          </div>
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
        <button type="button" onClick={() => setRetryCount((c) => c + 1)} style={btnStyle}>
          Retry
        </button>
      </Centered>
    )
  }

  const filename = source.filename ?? `file.${source.kind}`

  if (blobUrl && source.kind === 'pdf') {
    return <iframe src={blobUrl} style={{ flex: 1, width: '100%', height: '100%', border: 'none', display: 'block' }} title={filename} />
  }
  if (blobUrl && IMAGE_KINDS.includes(source.kind)) {
    return (
      <div style={{ flex: 1, overflowY: 'auto', padding: 16, display: 'flex', alignItems: 'flex-start', justifyContent: 'center' }}>
        <img src={blobUrl} alt={filename} style={{ maxWidth: '100%' }} />
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
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12 }}>
      <div style={{ width: 260, background: '#21262d', borderRadius: 4, overflow: 'hidden', height: 6 }}>
        {pct !== null ? (
          <div
            style={{
              height: '100%',
              width: `${pct}%`,
              background: '#388bfd',
              borderRadius: 4,
              transition: 'width 0.1s ease',
            }}
          />
        ) : (
          <div style={{ height: '100%', background: 'linear-gradient(90deg, #21262d 25%, #388bfd 50%, #21262d 75%)', backgroundSize: '200% 100%', animation: 'indeterminate 1.4s ease infinite' }} />
        )}
      </div>
      <span style={{ color: '#8b949e', fontSize: 12 }}>{label}</span>
      <style>{`@keyframes indeterminate { 0% { background-position: 200% 0 } 100% { background-position: -200% 0 } }`}</style>
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
    <div
      style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#8b949e',
        fontSize: 13,
        gap: 8,
      }}
    >
      {children}
    </div>
  )
}

const btnStyle: React.CSSProperties = {
  padding: '3px 10px',
  background: '#21262d',
  border: '1px solid #30363d',
  borderRadius: 4,
  color: '#e6edf3',
  cursor: 'pointer',
  fontSize: 12,
}

const linkBtnStyle: React.CSSProperties = {
  padding: '3px 10px',
  background: '#21262d',
  border: '1px solid #30363d',
  borderRadius: 4,
  color: '#e6edf3',
  cursor: 'pointer',
  fontSize: 12,
  textDecoration: 'none',
}
