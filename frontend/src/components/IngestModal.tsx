import { useState } from 'react'
import type React from 'react'
import { ingestText, ingestUrl, ingestFile } from '../api/client'
import { useQueryClient } from '@tanstack/react-query'

export default function IngestModal({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<'text' | 'url' | 'file'>('text')
  const [text, setText] = useState('')
  const [url, setUrl] = useState('')
  const [status, setStatus] = useState('')
  const qc = useQueryClient()

  async function submit() {
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

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setStatus('Uploading…')
    await ingestFile(file)
    setStatus('Uploaded! Agent is processing.')
    qc.invalidateQueries({ queryKey: ['activity'] })
    setTimeout(onClose, 1500)
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex',
      alignItems: 'center', justifyContent: 'center', zIndex: 100 }}
      onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 12,
        padding: 24, width: 480, maxWidth: '90vw' }}>
        <h3 style={{ marginBottom: 16, color: '#e6edf3' }}>Ingest</h3>
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          {(['text', 'url', 'file'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 14px', background: tab === t ? '#238636' : '#21262d',
              border: '1px solid #30363d', borderRadius: 6, color: '#e6edf3', cursor: 'pointer', fontSize: 13
            }}>{t}</button>
          ))}
        </div>
        {tab === 'text' && (
          <textarea value={text} onChange={e => setText(e.target.value)}
            placeholder="Paste any text, note, or idea…" rows={6}
            style={{ width: '100%', padding: 12, background: '#0d1117', border: '1px solid #30363d',
              borderRadius: 6, color: '#e6edf3', fontSize: 13, resize: 'vertical' }} />
        )}
        {tab === 'url' && (
          <input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://…"
            style={{ width: '100%', padding: '8px 12px', background: '#0d1117', border: '1px solid #30363d',
              borderRadius: 6, color: '#e6edf3', fontSize: 13 }} />
        )}
        {tab === 'file' && (
          <input type="file" accept=".pdf,.docx,.md,.markdown,.txt" onChange={handleFile}
            style={{ color: '#e6edf3', fontSize: 13 }} />
        )}
        {status && <div style={{ marginTop: 12, fontSize: 13, color: '#58a6ff' }}>{status}</div>}
        {tab !== 'file' && (
          <button onClick={submit} style={{ marginTop: 16, width: '100%', padding: '10px 0',
            background: '#238636', border: 'none', borderRadius: 6, color: '#fff', cursor: 'pointer', fontSize: 14 }}>
            Ingest
          </button>
        )}
      </div>
    </div>
  )
}
