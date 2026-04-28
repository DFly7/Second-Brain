import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listPages, getPage, updatePage } from '../api/client'

export function usePages() {
  return useQuery({ queryKey: ['pages'], queryFn: listPages, refetchInterval: 10000 })
}

export function usePage(slug: string | null) {
  return useQuery({ queryKey: ['page', slug], queryFn: () => getPage(slug!), enabled: !!slug })
}

export function useUpdatePage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ slug, ...body }: { slug: string; title?: string; body_md?: string }) =>
      updatePage(slug, body),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['pages'] })
      qc.invalidateQueries({ queryKey: ['page', vars.slug] })
    }
  })
}
