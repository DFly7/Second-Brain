import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import FilesList from './FilesList'
import FileViewer from './FileViewer'
import SourceMetaModal from './SourceMetaModal'
import { useSources } from '../hooks/useSources'
import { useSse } from '../hooks/useSse'
import { useIsMobile } from '../hooks/useIsMobile'

export default function FilesView() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [infoId, setInfoId] = useState<string | null>(null)
  const { data: sources } = useSources()
  const qc = useQueryClient()
  const isMobile = useIsMobile()

  useSse((data: unknown) => {
    const event = data as { event?: string; context?: string }
    if (event.context === 'chat') return
    if (event.event === 'agent:done') {
      qc.invalidateQueries({ queryKey: ['sources'] })
    }
  })

  const selectedSource = sources?.find((s) => s.id === selectedId) ?? null
  const infoSource = sources?.find((s) => s.id === infoId) ?? null
  const closeViewer = () => setSelectedId(null)

  if (isMobile) {
    return (
      <div className="flex h-full flex-col overflow-hidden">
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <FilesList
            sources={sources ?? []}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onInfo={setInfoId}
            fullWidth
          />
        </div>
        <FileViewer source={selectedSource} onClose={closeViewer} />
        {infoSource && (
          <SourceMetaModal source={infoSource} onClose={() => setInfoId(null)} />
        )}
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <aside className="flex min-h-0 shrink-0 flex-col">
          <FilesList
            sources={sources ?? []}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onInfo={setInfoId}
          />
        </aside>
      </div>
      <FileViewer source={selectedSource} onClose={closeViewer} />
      {infoSource && (
        <SourceMetaModal
          source={infoSource}
          onClose={() => setInfoId(null)}
        />
      )}
    </div>
  )
}
