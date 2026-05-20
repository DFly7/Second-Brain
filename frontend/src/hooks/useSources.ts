import { useQuery } from '@tanstack/react-query'
import { listSources, fetchSourceMarkdown } from '../api/client'
import type { SourceItem } from '../api/client'

export type { SourceItem }

export function useSources() {
  return useQuery<SourceItem[]>({
    queryKey: ['sources'],
    queryFn: listSources,
    refetchOnWindowFocus: true,
  })
}

export function useSourceMarkdown(sourceId: string | null, enabled: boolean) {
  return useQuery<string>({
    queryKey: ['source-markdown', sourceId],
    queryFn: () => fetchSourceMarkdown(sourceId!),
    enabled: enabled && !!sourceId,
  })
}
