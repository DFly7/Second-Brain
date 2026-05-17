import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import TopBar from './TopBar'
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

  if (isMobile) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100dvh' }}>
        <TopBar />
        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          {selectedId === null ? (
            <FilesList
              sources={sources ?? []}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onInfo={setInfoId}
              fullWidth
            />
          ) : (
            <FileViewer source={selectedSource} onBack={() => setSelectedId(null)} />
          )}
        </div>
        {infoSource && (
          <SourceMetaModal source={infoSource} onClose={() => setInfoId(null)} />
        )}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <TopBar />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <FilesList
          sources={sources ?? []}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onInfo={setInfoId}
        />
        <FileViewer source={selectedSource} />
      </div>
      {infoSource && (
        <SourceMetaModal
          source={infoSource}
          onClose={() => setInfoId(null)}
        />
      )}
    </div>
  )
}
