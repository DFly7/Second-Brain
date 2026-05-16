import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import TopBar from './TopBar'
import FilesList from './FilesList'
import FileViewer from './FileViewer'
import { useSources } from '../hooks/useSources'
import { useSse } from '../hooks/useSse'
import type { SourceSelection } from './FilesList'

export default function FilesView() {
  const [selection, setSelection] = useState<SourceSelection | null>(null)
  const { data: sources } = useSources()
  const qc = useQueryClient()

  useSse((data: unknown) => {
    const event = data as { event?: string; context?: string }
    if (event.context === 'chat') return
    if (event.event === 'agent:done') {
      qc.invalidateQueries({ queryKey: ['sources'] })
    }
  })

  const selectedSource = sources?.find((s) => s.id === selection?.sourceId) ?? null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <TopBar />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <FilesList sources={sources ?? []} selection={selection} onSelect={setSelection} />
        <FileViewer source={selectedSource} view={selection?.view ?? 'markdown'} />
      </div>
    </div>
  )
}
