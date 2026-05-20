import { useLocation, Outlet } from 'react-router-dom'
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from '@/components/ui/resizable'
import { IconRail } from '@/components/shell/IconRail'
import { ShellStateProvider, useShellState } from '@/components/shell/ShellStateContext'
import { WikiTree } from '@/components/secondary-sidebar/WikiTree'
import { FilesTree } from '@/components/secondary-sidebar/FilesTree'
import { AutomationsList } from '@/components/secondary-sidebar/AutomationsList'
import { BrowserSessionsList } from '@/components/secondary-sidebar/BrowserSessionsList'
import { SessionsList } from '@/components/secondary-sidebar/SessionsList'
import ChatPanel from '@/components/ChatPanel'
import { useIsMobile } from '@/hooks/useIsMobile'

function SecondaryForRoute() {
  const { pathname } = useLocation()
  const { selectedSlug, highlightedSlug, onSelectSlug } = useShellState()

  if (pathname.startsWith('/wiki')) {
    return (
      <WikiTree
        selectedSlug={selectedSlug}
        highlightedSlug={highlightedSlug}
        onSelect={onSelectSlug}
      />
    )
  }
  if (pathname.startsWith('/files')) return <FilesTree />
  if (pathname.startsWith('/automations')) return <AutomationsList />
  if (pathname.startsWith('/browser-chat')) return <BrowserSessionsList />
  if (pathname.startsWith('/sessions')) return <SessionsList />
  return null
}

function AppShellLayout() {
  const isMobile = useIsMobile()
  const { onSelectSlug, chatSseEvent } = useShellState()

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
      <IconRail />
      {isMobile ? (
        <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <Outlet />
        </main>
      ) : (
        <ResizablePanelGroup orientation="horizontal" className="min-h-0 flex-1">
          <ResizablePanel defaultSize={18} minSize={14} maxSize={30} collapsible collapsedSize={0}>
            <div className="h-full overflow-hidden">
              <SecondaryForRoute />
            </div>
          </ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel defaultSize={56} minSize={30}>
            <main className="flex h-full min-h-0 flex-col overflow-hidden">
              <Outlet />
            </main>
          </ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel defaultSize={26} minSize={20} maxSize={45} collapsible collapsedSize={0}>
            <div className="h-full overflow-hidden">
              <ChatPanel onNavigate={onSelectSlug} activeSseEvent={chatSseEvent} />
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>
      )}
    </div>
  )
}

export function AppShell() {
  return (
    <ShellStateProvider>
      <AppShellLayout />
    </ShellStateProvider>
  )
}
