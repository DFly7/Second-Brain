import { useEffect, useRef, useState } from 'react'
import type React from 'react'
import { ingestText, ingestUrl, ingestFile } from '../api/client'
import { useQueryClient } from '@tanstack/react-query'
import { reduceQueue, type QueueItem, type QueueState, type QueueStatus } from '../state/ingestQueue'

const STATUS_LABEL: Record<QueueStatus, string> = {
  pending: 'Pending',
  uploading: 'Uploading…',
  queued: 'Queued…',
  converting: 'Converting…',
  processing: 'Processing…',
  done: 'Done ✓',
  error: 'Error ✗',
}

const STATUS_COLOR: Record<QueueStatus, string> = {
  pending: '#8b949e',
  uploading: '#58a6ff',
  queued: '#a371f7',
  converting: '#d29922',
  processing: '#d29922',
  done: '#3fb950',
  error: '#f85149',
}

function isControlled(
  props: IngestModalProps,
): props is Required<Pick<IngestModalProps, 'queue' | 'onUpsertQueueItems' | 'onPatchQueueById'>> &
  IngestModalProps {
  return (
    props.queue !== undefined &&
    props.onUpsertQueueItems !== undefined &&
    props.onPatchQueueById !== undefined
  )
}

type IngestModalProps = {
  onClose: () => void
  queue?: QueueState
  onUpsertQueueItems?: (items: QueueItem[]) => void
  onPatchQueueById?: (id: string, patch: Partial<QueueItem>) => void
}

export default function IngestModal(props: IngestModalProps) {
  const { onClose } = props
  const [tab, setTab] = useState<'text' | 'url' | 'file'>('text')
  const [text, setText] = useState('')
  const [url, setUrl] = useState('')
  const [status, setStatus] = useState('')
  const [orderedFileIds, setOrderedFileIds] = useState<string[]>([])
  const filesByIdRef = useRef<Map<string, File>>(new Map())
  const [uploading, setUploading] = useState(false)
  const [localQueue, setLocalQueue] = useState<QueueState>(() => ({ items: [] }))
  const qc = useQueryClient()

  const wired = isControlled(props)
  const queue = wired ? props.queue : localQueue
  const upsertMany = wired
    ? props.onUpsertQueueItems!
    : (items: QueueItem[]) => setLocalQueue(s => reduceQueue(s, { type: 'upsert_many', items }))
  const patchById = wired
    ? props.onPatchQueueById!
    : (id: string, patch: Partial<QueueItem>) =>
        setLocalQueue(s => reduceQueue(s, { type: 'patch_by_id', id, patch }))

  useEffect(() => {
    if (orderedFileIds.length === 0) return
    const allTerminal = orderedFileIds.every(id => {
      const item = queue.items.find(i => i.id === id)
      return item && (item.status === 'done' || item.status === 'error')
    })
    if (!allTerminal) return
    qc.invalidateQueries({ queryKey: ['pages'] })
    const timer = setTimeout(onClose, 2000)
    return () => clearTimeout(timer)
  }, [orderedFileIds, queue, onClose, qc])

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
    const ids = files.map(() => crypto.randomUUID())
    const map = new Map<string, File>()
    files.forEach((file, i) => map.set(ids[i], file))
    filesByIdRef.current = map
    setOrderedFileIds(ids)
    upsertMany(
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
      patchById(id, { status: 'uploading' })
      const file = filesByIdRef.current.get(id)
      if (!file) continue
      try {
        const resp = await ingestFile(file)
        patchById(id, { sourceId: resp.source_id, status: 'queued' })
      } catch {
        patchById(id, { status: 'error', error: 'Upload failed' })
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
        padding: 0, width: 520, maxWidth: '92vw',
        maxHeight: '90vh', display: 'flex', flexDirection: 'column', overflow: 'hidden',
      }}>
        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 24 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ color: '#e6edf3', margin: 0 }}>Ingest</h3>
            <button type="button" onClick={onClose} style={{ background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', fontSize: 18 }}>✕</button>
          </div>

          {/* Tabs */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            {(['text', 'url', 'file'] as const).map(t => (
              <button key={t} type="button" onClick={() => setTab(t)} style={{
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
              {orderedFileIds.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
                  {orderedFileIds.map(fid => {
                    const entry = queue.items.find(i => i.id === fid)
                    const qs: QueueStatus = entry?.status ?? 'pending'
                    const name =
                      entry?.fileName ??
                      filesByIdRef.current.get(fid)?.name ??
                      fid
                    return (
                      <div key={fid} style={{
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        padding: '6px 10px', background: '#0d1117',
                        border: '1px solid #30363d', borderRadius: 6,
                      }}>
                        <span style={{ fontSize: 12, color: '#e6edf3', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 320 }}>
                          {name}
                        </span>
                        <span style={{ fontSize: 11, color: STATUS_COLOR[qs], flexShrink: 0, marginLeft: 8 }}>
                          {STATUS_LABEL[qs]}
                        </span>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )}
        </div>

        <div style={{ flexShrink: 0, padding: '16px 24px', borderTop: '1px solid #30363d', background: '#161b22' }}>
          {tab === 'file' ? (
            orderedFileIds.length > 0 ? (
              <button
                type="button"
                onClick={() => void uploadAll()}
                disabled={uploading}
                style={{
                  width: '100%', padding: '10px 0',
                  background: uploading ? '#21262d' : '#238636',
                  border: 'none', borderRadius: 6,
                  color: uploading ? '#8b949e' : '#fff',
                  cursor: uploading ? 'not-allowed' : 'pointer', fontSize: 14,
                }}
              >
                {uploading ? 'Uploading…' : `Upload ${orderedFileIds.length} file${orderedFileIds.length !== 1 ? 's' : ''}`}
              </button>
            ) : null
          ) : (
            <>
              {status ? (
                <div style={{ marginBottom: 12, fontSize: 13, color: '#58a6ff' }}>{status}</div>
              ) : null}
              <button
                type="button"
                onClick={() => void submitTextOrUrl()}
                style={{
                  width: '100%', padding: '10px 0',
                  background: '#238636', border: 'none', borderRadius: 6,
                  color: '#fff', cursor: 'pointer', fontSize: 14,
                }}
              >
                Ingest
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
