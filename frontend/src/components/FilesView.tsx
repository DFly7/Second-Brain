import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import FilesList from './FilesList'
import FileViewer from './FileViewer'
import SourceMetaModal from './SourceMetaModal'
import { useSources } from '../hooks/useSources'
import { useSse } from '../hooks/useSse'
import { useIsMobile } from '../hooks/useIsMobile'

export default function FilesView() {
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedId = searchParams.get('source')
  const setSelectedId = (id: string | null) => {
    if (id) setSearchParams({ source: id }, { replace: true })
    else setSearchParams({}, { replace: true })
  }
  const [infoId, setInfoId] = useState<string | null>(null)
  const { data: sources, isPending: sourcesLoading } = useSources()
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
            loading={sourcesLoading}
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
    <div className="flex h-full overflow-hidden">
      <aside className="flex w-72 shrink-0 flex-col border-r border-border">
        <FilesList
          sources={sources ?? []}
          loading={sourcesLoading}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onInfo={setInfoId}
          fullWidth
        />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {selectedSource ? (
          <FileViewer source={selectedSource} onClose={closeViewer} inline />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            Select a file to preview
          </div>
        )}
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
