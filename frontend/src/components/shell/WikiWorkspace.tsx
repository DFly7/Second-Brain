import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { WikiTree } from '@/components/secondary-sidebar/WikiTree'
import WikiContent from '@/components/WikiContent'
import ChatPanel from '@/components/ChatPanel'
import IngestModal from '@/components/IngestModal'
import { ContextBar } from '@/components/shell/ContextBar'
import { useShell } from '@/components/shell/ShellContext'
import { useShellState } from '@/components/shell/ShellStateContext'
import { useIsMobile } from '@/hooks/useIsMobile'
import { usePage } from '@/hooks/useWiki'
import { cn } from '@/lib/utils'

export default function WikiWorkspace() {
  const {
    selectedSlug,
    highlightedSlug,
    showIngest,
    setShowIngest,
    queue,
    queueActions,
    chatSseEvent,
    onSelectSlug,
  } = useShellState()
  const { openPalette } = useShell()

  const isMobile = useIsMobile()
  const [activeTab, setActiveTab] = useState<'pages' | 'content' | 'chat'>('content')
  const { data: page } = usePage(selectedSlug)

  function handleSelect(slug: string) {
    onSelectSlug(slug)
    if (isMobile) setActiveTab('content')
  }

  const breadcrumbs = [
    { label: 'Wiki', href: '/wiki' },
    ...(selectedSlug
      ? [{ label: page?.title ?? selectedSlug.split('/').pop() ?? selectedSlug }]
      : []),
  ]

  const contextActions = (
    <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => setShowIngest(true)}>
      + Ingest
    </Button>
  )

  const modals = showIngest && (
    <IngestModal
      onClose={() => setShowIngest(false)}
      queue={queue}
      onUpsertQueueItems={items => queueActions.upsertMany(items)}
      onPatchQueueById={(id, patch) => queueActions.patchById(id, patch)}
    />
  )

  if (isMobile) {
    return (
      <div className="flex h-full flex-col overflow-hidden">
        <ContextBar breadcrumbs={breadcrumbs} actions={contextActions} onOpenPalette={openPalette} />
        <div className="min-h-0 flex-1 overflow-hidden">
          {activeTab === 'pages' && (
            <WikiTree
              selectedSlug={selectedSlug}
              highlightedSlug={highlightedSlug}
              onSelect={handleSelect}
            />
          )}
          {activeTab === 'content' && (
            <WikiContent selectedSlug={selectedSlug} onNavigate={handleSelect} />
          )}
          {activeTab === 'chat' && (
            <ChatPanel onNavigate={handleSelect} activeSseEvent={chatSseEvent} />
          )}
        </div>
        <div
          className="flex shrink-0 border-t-2 border-border bg-background pb-[env(safe-area-inset-bottom)]"
        >
          {(
            [
              { id: 'pages' as const, label: '≡ Pages' },
              { id: 'content' as const, label: '□ Content' },
              { id: 'chat' as const, label: '◎ Chat' },
            ] as const
          ).map(({ id, label }) => (
            <Button
              key={id}
              type="button"
              variant="ghost"
              onClick={() => setActiveTab(id)}
              className={cn(
                'h-auto flex-1 rounded-none border-t-2 py-3 text-[13px] hover:bg-transparent',
                activeTab === id
                  ? '-mt-0.5 border-primary text-primary'
                  : 'border-transparent text-muted-foreground',
              )}
            >
              {label}
            </Button>
          ))}
        </div>
        {modals}
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <ContextBar breadcrumbs={breadcrumbs} actions={contextActions} onOpenPalette={openPalette} />
      <div className="min-h-0 flex-1 overflow-hidden">
        <WikiContent selectedSlug={selectedSlug} onNavigate={onSelectSlug} />
      </div>
      {modals}
    </div>
  )
}
