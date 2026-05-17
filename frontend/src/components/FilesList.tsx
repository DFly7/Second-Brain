import type { SourceItem } from '../api/client'

interface FilesListProps {
  sources: SourceItem[]
  selectedId: string | null
  onSelect: (id: string) => void
  onInfo: (id: string) => void
}

const STATUS_COLOR: Record<string, string> = {
  done: '#3fb950',
  error: '#f85149',
  converting: '#d29922',
  ingesting: '#58a6ff',
  processing: '#58a6ff',
}

const KIND_COLOR: Record<string, string> = {
  pdf: '#d2a8ff',
  png: '#79c0ff',
  jpg: '#79c0ff',
  jpeg: '#79c0ff',
  webp: '#79c0ff',
  docx: '#56d364',
  doc: '#56d364',
  url: '#e3b341',
  text: '#8b949e',
  md: '#8b949e',
  markdown: '#8b949e',
  voice: '#56d364',
}

function fileIcon(kind: string): string {
  if (kind === 'pdf') return '📄'
  if (['png', 'jpg', 'jpeg', 'webp'].includes(kind)) return '🖼️'
  if (['docx', 'doc'].includes(kind)) return '📝'
  if (['pptx', 'ppt', 'xlsx', 'xls'].includes(kind)) return '📊'
  if (kind === 'url') return '🔗'
  if (kind === 'voice') return '🎙️'
  return '📄'
}

export default function FilesList({ sources, selectedId, onSelect, onInfo }: FilesListProps) {
  if (sources.length === 0) {
    return (
      <div style={{ width: 240, borderRight: '1px solid #21262d', padding: 16, color: '#8b949e', fontSize: 13 }}>
        No files ingested yet.
      </div>
    )
  }

  return (
    <div style={{ width: 240, borderRight: '1px solid #21262d', overflowY: 'auto', padding: 8, flexShrink: 0 }}>
      {sources.map((source) => {
        const title = source.title ?? `${source.kind} · ${source.id.slice(0, 8).toUpperCase()}`
        const isSelected = source.id === selectedId
        const dotColor = STATUS_COLOR[source.status] ?? '#8b949e'
        const badgeColor = KIND_COLOR[source.kind] ?? '#8b949e'

        return (
          <div
            key={source.id}
            role="button"
            tabIndex={0}
            onClick={() => onSelect(source.id)}
            onKeyDown={(e) => e.key === 'Enter' && onSelect(source.id)}
            style={{
              padding: '6px 8px',
              borderRadius: 4,
              cursor: 'pointer',
              marginBottom: 2,
              background: isSelected ? '#1f3a5f' : 'transparent',
              border: `1px solid ${isSelected ? '#58a6ff33' : 'transparent'}`,
              position: 'relative',
            }}
            className="file-row"
          >
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 6 }}>
              <span style={{ flexShrink: 0, marginTop: 1 }}>{fileIcon(source.kind)}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 12,
                  color: isSelected ? '#58a6ff' : '#e6edf3',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  {title}
                </div>
                {source.description && (
                  <div style={{
                    fontSize: 10,
                    color: '#6e7681',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    marginTop: 2,
                  }}>
                    {source.description}
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
                <span style={{
                  fontSize: 9,
                  padding: '1px 5px',
                  borderRadius: 3,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  background: '#21262d',
                  color: badgeColor,
                }}>
                  {source.kind}
                </span>
                <span
                  style={{ width: 6, height: 6, borderRadius: '50%', background: dotColor, flexShrink: 0 }}
                  title={source.status}
                />
              </div>
            </div>
            <button
              type="button"
              className="info-btn"
              onClick={(e) => { e.stopPropagation(); onInfo(source.id) }}
              style={{
                position: 'absolute',
                top: 4,
                right: 28,
                background: 'none',
                border: 'none',
                color: '#6e7681',
                cursor: 'pointer',
                fontSize: 11,
                padding: '0 2px',
                opacity: 0,
                transition: 'opacity 0.1s',
              }}
              aria-label="File info"
            >
              ⓘ
            </button>
          </div>
        )
      })}
      <style>{`
        .file-row:hover .info-btn { opacity: 1 !important; }
      `}</style>
    </div>
  )
}
