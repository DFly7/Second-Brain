import { useState, useEffect } from 'react'
import type React from 'react'
import { ingestText, ingestUrl, ingestFile, createSSE } from '../api/client'
import { useQueryClient } from '@tanstack/react-query'

type FileStatus = 'pending' | 'uploading' | 'converting' | 'processing' | 'done' | 'error'

interface FileEntry {
  id: string
  file: File
  status: FileStatus
  sourceId?: string
}

const STATUS_LABEL: Record<FileStatus, string> = {
  pending: 'Pending',
  uploading: 'Uploading…',
  converting: 'Converting…',
  processing: 'Processing…',
  done: 'Done ✓',
  error: 'Error ✗',
}

const STATUS_COLOR: Record<FileStatus, string> = {
  pending: '#8b949e',
  uploading: '#58a6ff',
  converting: '#d29922',
  processing: '#d29922',
  done: '#3fb950',
  error: '#f85149',
}

export default function IngestModal({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<'text' | 'url' | 'file'>('text')
  const [text, setText] = useState('')
  const [url, setUrl] = useState('')
  const [status, setStatus] = useState('')
  const [fileEntries, setFileEntries] = useState<FileEntry[]>([])
  const [uploading, setUploading] = useState(false)
  const qc = useQueryClient()

  // SSE subscription — update file entries as pipeline progresses
  useEffect(() => {
    const STATUS_MAP: Partial<Record<string, FileStatus>> = {
      'agent:queued': 'converting',
      'agent:converting': 'converting',
      'agent:ingesting': 'processing',
      'agent:done': 'done',
    }
    const unsub = createSSE((data: unknown) => {
      const event = data as { event: string; source_id?: string }
      const newStatus = STATUS_MAP[event.event]
      if (!newStatus || !event.source_id) return
      setFileEntries(entries =>
        entries.map(e =>
          e.sourceId === event.source_id ? { ...e, status: newStatus } : e
        )
      )
    })
    return unsub
  }, [])

  // Auto-close 2s after all files reach a terminal state
  useEffect(() => {
    if (fileEntries.length === 0) return
    const allDone = fileEntries.every(e => e.status === 'done' || e.status === 'error')
    if (!allDone) return
    qc.invalidateQueries({ queryKey: ['pages'] })
    const timer = setTimeout(onClose, 2000)
    return () => clearTimeout(timer)
  }, [fileEntries, onClose, qc])

  async function submitTextOrUrl() {
    setStatus('Ingesting…')
    try {
      if (tab === 'text') await ingestText(text)
      else if (tab === 'url') await ingestUrl(url)
      setStatus('Ingested! Agent is updating your wiki.')
      qc.invalidateQueries({ queryKey: ['activity'] })
      setTimeout(onClose, 1500)
    } catch {
      setStatus('Failed — check the console.')
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || [])
    setFileEntries(files.map(file => ({
      id: crypto.randomUUID(),
      file,
      status: 'pending',
    })))
  }

  async function uploadAll() {
    if (uploading || fileEntries.length === 0) return
    setUploading(true)
    for (const entry of fileEntries) {
      setFileEntries(prev => prev.map(e =>
        e.id === entry.id ? { ...e, status: 'uploading' } : e
      ))
      try {
        const resp = await ingestFile(entry.file)
        setFileEntries(prev => prev.map(e =>
          e.id === entry.id ? { ...e, status: 'converting', sourceId: resp.source_id } : e
        ))
      } catch {
        setFileEntries(prev => prev.map(e =>
          e.id === entry.id ? { ...e, status: 'error' } : e
        ))
      }
    }
    setUploading(false)
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
      }}
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div style={{
        background: '#161b22', border: '1px solid #30363d', borderRadius: 12,
        padding: 24, width: 480, maxWidth: '90vw',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ color: '#e6edf3', margin: 0 }}>Ingest</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', fontSize: 18 }}>✕</button>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          {(['text', 'url', 'file'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 14px',
              background: tab === t ? '#238636' : '#21262d',
              border: '1px solid #30363d', borderRadius: 6,
              color: '#e6edf3', cursor: 'pointer', fontSize: 13,
            }}>{t}</button>
          ))}
        </div>

        {/* Text tab */}
        {tab === 'text' && (
          <textarea
            value={text}
            onChange={e => setText(e.target.value)}
            placeholder="Paste any text, note, or idea…"
            rows={6}
            style={{
              width: '100%', padding: 12, background: '#0d1117',
              border: '1px solid #30363d', borderRadius: 6,
              color: '#e6edf3', fontSize: 13, resize: 'vertical',
            }}
          />
        )}

        {/* URL tab */}
        {tab === 'url' && (
          <input
            value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://…"
            style={{
              width: '100%', padding: '8px 12px', background: '#0d1117',
              border: '1px solid #30363d', borderRadius: 6, color: '#e6edf3', fontSize: 13,
            }}
          />
        )}

        {/* File tab */}
        {tab === 'file' && (
          <div>
            <input
              type="file"
              multiple
              accept=".pdf,.docx,.md,.markdown,.txt,.png,.jpg,.jpeg,.webp"
              onChange={handleFileChange}
              style={{ color: '#e6edf3', fontSize: 13, marginBottom: 12 }}
            />
            {fileEntries.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
                {fileEntries.map(entry => (
                  <div key={entry.id} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '6px 10px', background: '#0d1117',
                    border: '1px solid #30363d', borderRadius: 6,
                  }}>
                    <span style={{ fontSize: 12, color: '#e6edf3', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 280 }}>
                      {entry.file.name}
                    </span>
                    <span style={{ fontSize: 11, color: STATUS_COLOR[entry.status], flexShrink: 0, marginLeft: 8 }}>
                      {STATUS_LABEL[entry.status]}
                    </span>
                  </div>
                ))}
              </div>
            )}
            {fileEntries.length > 0 && (
              <button
                onClick={uploadAll}
                disabled={uploading}
                style={{
                  width: '100%', padding: '10px 0',
                  background: uploading ? '#21262d' : '#238636',
                  border: 'none', borderRadius: 6,
                  color: uploading ? '#8b949e' : '#fff',
                  cursor: uploading ? 'not-allowed' : 'pointer', fontSize: 14,
                }}
              >
                {uploading ? 'Uploading…' : `Upload ${fileEntries.length} file${fileEntries.length !== 1 ? 's' : ''}`}
              </button>
            )}
          </div>
        )}

        {/* Text/URL status */}
        {status && tab !== 'file' && (
          <div style={{ marginTop: 12, fontSize: 13, color: '#58a6ff' }}>{status}</div>
        )}

        {/* Text/URL submit */}
        {tab !== 'file' && (
          <button
            onClick={submitTextOrUrl}
            style={{
              marginTop: 16, width: '100%', padding: '10px 0',
              background: '#238636', border: 'none', borderRadius: 6,
              color: '#fff', cursor: 'pointer', fontSize: 14,
            }}
          >
            Ingest
          </button>
        )}
      </div>
    </div>
  )
}
