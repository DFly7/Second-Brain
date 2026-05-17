import { useState, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { SourceItem } from '../api/client'
import { patchSource } from '../api/client'

interface SourceMetaModalProps {
  source: SourceItem
  onClose: () => void
}

export default function SourceMetaModal({ source, onClose }: SourceMetaModalProps) {
  const [title, setTitle] = useState(source.title ?? '')
  const [description, setDescription] = useState(source.description ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const qc = useQueryClient()

  useEffect(() => {
    setTitle(source.title ?? '')
    setDescription(source.description ?? '')
    setError(null)
  }, [source.id])

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      await patchSource(source.id, { title: title || undefined, description: description || undefined })
      qc.invalidateQueries({ queryKey: ['sources'] })
      onClose()
    } catch {
      setError('Failed to save. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
      }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div style={{
        background: '#161b22', border: '1px solid #30363d', borderRadius: 12,
        padding: 0, width: 460, maxWidth: '92vw',
        maxHeight: '90vh', display: 'flex', flexDirection: 'column', overflow: 'hidden',
      }}>
        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 24 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
            <h3 style={{ color: '#e6edf3', margin: 0, fontSize: 15 }}>File info</h3>
            <button type="button" onClick={onClose} style={{ background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', fontSize: 18 }}>✕</button>
          </div>

          {/* Editable fields */}
          <div style={{ marginBottom: 14 }}>
            <label style={{ display: 'block', fontSize: 11, color: '#8b949e', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Title
            </label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="File title"
              style={{
                width: '100%', boxSizing: 'border-box',
                background: '#0d1117', border: '1px solid #30363d', borderRadius: 6,
                color: '#e6edf3', fontSize: 13, padding: '7px 10px', outline: 'none',
              }}
            />
          </div>

          <div style={{ marginBottom: 20 }}>
            <label style={{ display: 'block', fontSize: 11, color: '#8b949e', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="One sentence summary"
              rows={3}
              style={{
                width: '100%', boxSizing: 'border-box',
                background: '#0d1117', border: '1px solid #30363d', borderRadius: 6,
                color: '#e6edf3', fontSize: 13, padding: '7px 10px', outline: 'none',
                resize: 'vertical', fontFamily: 'inherit',
              }}
            />
          </div>

          {/* Read-only metadata */}
          <div style={{ borderTop: '1px solid #21262d', paddingTop: 14, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {source.filename && (
              <MetaRow label="Original filename" value={source.filename} />
            )}
            <MetaRow label="Type" value={source.kind.toUpperCase()} />
            <MetaRow label="Status" value={source.status} />
            <MetaRow label="Ingested" value={new Date(source.created_at).toLocaleString()} />
          </div>

          {error && (
            <div style={{ marginTop: 12, color: '#f85149', fontSize: 12 }}>{error}</div>
          )}
        </div>

        <div style={{ padding: '12px 24px', borderTop: '1px solid #21262d', display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button type="button" onClick={onClose} style={{
            padding: '6px 14px', background: '#21262d', border: '1px solid #30363d',
            borderRadius: 6, color: '#e6edf3', cursor: 'pointer', fontSize: 13,
          }}>
            Cancel
          </button>
          <button type="button" onClick={handleSave} disabled={saving} style={{
            padding: '6px 14px', background: saving ? '#1a3a1a' : '#238636', border: '1px solid #2ea043',
            borderRadius: 6, color: '#e6edf3', cursor: saving ? 'not-allowed' : 'pointer', fontSize: 13,
          }}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', gap: 8, fontSize: 12 }}>
      <span style={{ color: '#6e7681', minWidth: 120, flexShrink: 0 }}>{label}</span>
      <span style={{ color: '#8b949e', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</span>
    </div>
  )
}
