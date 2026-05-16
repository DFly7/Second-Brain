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
  view: 'original' | 'markdown'
}

function isProcessingStatus(status: string): boolean {
  return status === 'converting' || status === 'ingesting' || status === 'processing'
}

export default function FileViewer({ source, view }: FileViewerProps) {
  if (!source) {
    return (
      <div
        style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#8b949e',
          fontSize: 13,
        }}
      >
        Select a file to view it.
      </div>
    )
  }

  if (view === 'markdown') return <MarkdownPane source={source} />
  return <OriginalPane source={source} />
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
      <div style={headerStyle}>
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

function OriginalPane({ source }: { source: SourceItem }) {
  const needsFetch = !NO_FILE_KINDS.includes(source.kind) && source.has_file
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(needsFetch)
  const [error, setError] = useState(false)
  const [retryCount, setRetryCount] = useState(0)

  useEffect(() => {
    if (!needsFetch) return
    let objectUrl: string | null = null
    setLoading(true)
    setError(false)
    setBlobUrl(null)

    fetchSourceFile(source.id)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob)
        setBlobUrl(objectUrl)
        setLoading(false)
      })
      .catch(() => {
        setError(true)
        setLoading(false)
      })

    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [source.id, source.kind, source.has_file, needsFetch, retryCount])

  if (NO_FILE_KINDS.includes(source.kind)) {
    return <Centered>Web or text source — no original file to display.</Centered>
  }
  if (!source.has_file) return <Centered>No original file.</Centered>
  if (loading) return <Centered>Loading…</Centered>
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

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={headerStyle}>
        <span style={{ color: '#e6edf3', fontWeight: 600 }}>{filename}</span>
        {blobUrl && (
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <a href={blobUrl} download={filename} style={linkBtnStyle}>
              ⬇ Download
            </a>
            <a href={blobUrl} target="_blank" rel="noreferrer" style={linkBtnStyle}>
              ↗ Open in tab
            </a>
          </div>
        )}
      </div>

      {blobUrl && source.kind === 'pdf' && (
        <iframe src={blobUrl} style={{ flex: 1, border: 'none' }} title={filename} />
      )}
      {blobUrl && IMAGE_KINDS.includes(source.kind) && (
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: 16,
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'center',
          }}
        >
          <img src={blobUrl} alt={filename} style={{ maxWidth: '100%' }} />
        </div>
      )}
      {blobUrl && !IMAGE_KINDS.includes(source.kind) && source.kind !== 'pdf' && (
        <Centered>This file type cannot be previewed. Use the buttons above to download or open it.</Centered>
      )}
    </div>
  )
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

const headerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  padding: '8px 16px',
  borderBottom: '1px solid #21262d',
  background: '#161b22',
  flexShrink: 0,
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
