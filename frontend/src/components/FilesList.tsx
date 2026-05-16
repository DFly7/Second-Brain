import type React from 'react'
import type { SourceItem } from '../hooks/useSources'

export interface SourceSelection {
  sourceId: string
  view: 'original' | 'markdown'
}

interface FilesListProps {
  sources: SourceItem[]
  selection: SourceSelection | null
  onSelect: (sel: SourceSelection) => void
}

const STATUS_COLOR: Record<string, string> = {
  done: '#3fb950',
  error: '#f85149',
  converting: '#d29922',
  ingesting: '#58a6ff',
  processing: '#58a6ff',
}

function fileIcon(kind: string): string {
  if (kind === 'pdf') return '📄'
  if (['png', 'jpg', 'jpeg', 'webp'].includes(kind)) return '🖼'
  if (['docx', 'doc'].includes(kind)) return '📝'
  if (['pptx', 'ppt', 'xlsx', 'xls'].includes(kind)) return '📊'
  if (kind === 'url') return '🔗'
  return '📄'
}

export default function FilesList({ sources, selection, onSelect }: FilesListProps) {
  if (sources.length === 0) {
    return (
      <div
        style={{
          width: 240,
          borderRight: '1px solid #21262d',
          padding: 16,
          color: '#8b949e',
          fontSize: 13,
        }}
      >
        No files ingested yet.
      </div>
    )
  }

  return (
    <div
      style={{
        width: 240,
        borderRight: '1px solid #21262d',
        overflowY: 'auto',
        padding: 8,
        flexShrink: 0,
      }}
    >
      {sources.map((source) => {
        const label = source.filename ?? `${source.kind} · ${source.id.slice(0, 8)}`
        const isOriginalSelected = selection?.sourceId === source.id && selection?.view === 'original'
        const isMarkdownSelected = selection?.sourceId === source.id && selection?.view === 'markdown'
        const dotColor = STATUS_COLOR[source.status] ?? '#8b949e'

        return (
          <div key={source.id} style={{ marginBottom: 10 }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                marginBottom: 3,
                paddingLeft: 4,
              }}
            >
              <span
                style={{
                  color: '#6e7681',
                  fontSize: 10,
                  textTransform: 'uppercase',
                  letterSpacing: '.05em',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  flex: 1,
                }}
              >
                {label}
              </span>
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: dotColor,
                  flexShrink: 0,
                }}
                title={source.status}
              />
            </div>

            {source.has_file && (
              <div
                role="button"
                tabIndex={0}
                onClick={() => onSelect({ sourceId: source.id, view: 'original' })}
                onKeyDown={(e) => e.key === 'Enter' && onSelect({ sourceId: source.id, view: 'original' })}
                style={rowStyle(isOriginalSelected)}
              >
                <span>{fileIcon(source.kind)}</span>
                <span
                  style={{
                    fontSize: 12,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    flex: 1,
                  }}
                >
                  {label}
                </span>
                <span style={{ marginLeft: 'auto', fontSize: 10, color: '#6e7681', flexShrink: 0 }}>
                  original
                </span>
              </div>
            )}

            <div
              role="button"
              tabIndex={0}
              onClick={() => onSelect({ sourceId: source.id, view: 'markdown' })}
              onKeyDown={(e) => e.key === 'Enter' && onSelect({ sourceId: source.id, view: 'markdown' })}
              style={rowStyle(isMarkdownSelected)}
            >
              <span>📝</span>
              <span style={{ fontSize: 12, flex: 1 }}>converted.md</span>
              <span style={{ marginLeft: 'auto', fontSize: 10, color: '#6e7681', flexShrink: 0 }}>
                markdown
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function rowStyle(active: boolean): React.CSSProperties {
  return {
    padding: '4px 8px',
    borderRadius: 4,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    marginBottom: 2,
    background: active ? '#1f3a5f' : 'transparent',
    color: active ? '#58a6ff' : '#8b949e',
    border: `1px solid ${active ? '#58a6ff33' : 'transparent'}`,
  }
}
