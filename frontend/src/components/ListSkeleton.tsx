import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

export function ListSkeleton({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn('space-y-2 p-3', className)}>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton
          key={i}
          className={cn('h-7 w-full', i === rows - 1 && 'w-3/4')}
        />
      ))}
    </div>
  )
}
