import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'
import { Info, MoreHorizontal } from 'lucide-react'
import type { SourceItem } from '../api/client'

interface FilesListProps {
  sources: SourceItem[]
  selectedId: string | null
  onSelect: (id: string) => void
  onInfo: (id: string) => void
  fullWidth?: boolean
}

const STATUS_CLASS: Record<string, string> = {
  done: 'text-green-500',
  error: 'text-destructive',
  converting: 'text-amber-500',
  ingesting: 'text-blue-400',
  processing: 'text-blue-400',
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

export default function FilesList({ sources, selectedId, onSelect, onInfo, fullWidth }: FilesListProps) {
  const containerClass = cn(
    'flex min-h-0 shrink-0 flex-col overflow-hidden border-border',
    fullWidth ? 'w-full' : 'w-60 border-r',
  )

  if (sources.length === 0) {
    return (
      <div className={cn(containerClass, 'p-4 text-sm text-muted-foreground')}>
        No files ingested yet.
      </div>
    )
  }

  return (
    <div className={cn(containerClass, 'overflow-y-auto')}>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="h-9 px-3">Name</TableHead>
            <TableHead className="h-9 w-16 px-3">Type</TableHead>
            <TableHead className="h-9 w-20 px-3">Status</TableHead>
            <TableHead className="h-9 w-10 px-2" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {sources.map((source) => {
            const title = source.title ?? `${source.kind} · ${source.id.slice(0, 8).toUpperCase()}`
            const isSelected = source.id === selectedId

            return (
              <TableRow
                key={source.id}
                data-state={isSelected ? 'selected' : undefined}
                className="cursor-pointer"
                onClick={() => onSelect(source.id)}
              >
                <TableCell className="max-w-0 px-3 py-2">
                  <div className="flex min-w-0 items-start gap-2">
                    <span className="mt-0.5 shrink-0 text-sm">{fileIcon(source.kind)}</span>
                    <div className="min-w-0">
                      <div
                        className={cn(
                          'truncate text-sm font-medium',
                          isSelected ? 'text-primary' : 'text-foreground',
                        )}
                      >
                        {title}
                      </div>
                      {source.description && (
                        <div className="truncate text-xs text-muted-foreground">{source.description}</div>
                      )}
                    </div>
                  </div>
                </TableCell>
                <TableCell className="px-3 py-2">
                  <Badge variant="outline" className="text-[10px] font-bold uppercase tracking-wide">
                    {source.kind}
                  </Badge>
                </TableCell>
                <TableCell className="px-3 py-2">
                  <span
                    className={cn(
                      'text-xs capitalize',
                      STATUS_CLASS[source.status] ?? 'text-muted-foreground',
                    )}
                    title={source.status}
                  >
                    {source.status}
                  </span>
                </TableCell>
                <TableCell className="px-2 py-2" onClick={(e) => e.stopPropagation()}>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon" className="h-7 w-7">
                        <MoreHorizontal className="h-4 w-4" />
                        <span className="sr-only">File actions</span>
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onClick={() => onSelect(source.id)}>Open</DropdownMenuItem>
                      <DropdownMenuItem onClick={() => onInfo(source.id)}>
                        <Info className="mr-2 h-4 w-4" />
                        Info
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
