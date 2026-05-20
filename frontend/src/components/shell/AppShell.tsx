import { useState, useMemo, useCallback, useEffect } from 'react'
import { useLocation, Outlet } from 'react-router-dom'
import { usePanelRef } from 'react-resizable-panels'
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from '@/components/ui/resizable'
import { IconRail } from '@/components/shell/IconRail'
import { ShellStateProvider, useShellState } from '@/components/shell/ShellStateContext'
import { ShellContext } from '@/components/shell/ShellContext'
import { WikiTree } from '@/components/secondary-sidebar/WikiTree'
import { FilesTree } from '@/components/secondary-sidebar/FilesTree'
import { AutomationsList } from '@/components/secondary-sidebar/AutomationsList'
import { BrowserSessionsList } from '@/components/secondary-sidebar/BrowserSessionsList'
import { SessionsList } from '@/components/secondary-sidebar/SessionsList'
import ChatPanel from '@/components/ChatPanel'
import { useIsMobile } from '@/hooks/useIsMobile'
import { useShortcuts } from '@/lib/keyboard'
import { toast } from '@/lib/toast'
import { shortcuts as shortcutsRegistry } from '@/components/help/shortcuts'
import { CommandPalette } from '@/components/command-palette/CommandPalette'
import { HelpOverlay } from '@/components/help/HelpOverlay'

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
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const sidebarRef = usePanelRef()
  const chatRef = usePanelRef()

  const handleShortcut = useCallback((id: string) => {
    if (id === 'palette') setPaletteOpen(true)
    else if (id === 'help') setHelpOpen(true)
    else if (id === 'sidebar') {
      const p = sidebarRef.current
      if (p) (p.isCollapsed() ? p.expand() : p.collapse())
    } else if (id === 'chat') {
      const p = chatRef.current
      if (p) (p.isCollapsed() ? p.expand() : p.collapse())
    }
  }, [])

  useShortcuts(shortcutsRegistry, handleShortcut)

  useEffect(() => {
    if (localStorage.getItem('sb.helpHintShown') === '1') return
    const t = setTimeout(() => {
      toast.info('Press ? for keyboard shortcuts')
      localStorage.setItem('sb.helpHintShown', '1')
    }, 2000)
    return () => clearTimeout(t)
  }, [])

  const shellUi = useMemo(
    () => ({
      openPalette: () => setPaletteOpen(true),
      openHelp: () => setHelpOpen(true),
    }),
    [],
  )

  return (
    <>
      <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
        <IconRail onOpenHelp={() => setHelpOpen(true)} />
        {isMobile ? (
          <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
            <ShellContext.Provider value={shellUi}>
              <Outlet />
            </ShellContext.Provider>
          </main>
        ) : (
          <ResizablePanelGroup orientation="horizontal" className="min-h-0 flex-1">
            <ResizablePanel
              panelRef={sidebarRef}
              defaultSize={18}
              minSize={14}
              maxSize={30}
              collapsible
              collapsedSize={0}
            >
              <div className="h-full overflow-hidden">
                <SecondaryForRoute />
              </div>
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel defaultSize={56} minSize={30}>
              <main className="flex h-full min-h-0 flex-col overflow-hidden">
                <ShellContext.Provider value={shellUi}>
                  <Outlet />
                </ShellContext.Provider>
              </main>
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel
              panelRef={chatRef}
              defaultSize={26}
              minSize={20}
              maxSize={45}
              collapsible
              collapsedSize={0}
            >
              <div className="h-full overflow-hidden">
                <ChatPanel onNavigate={onSelectSlug} activeSseEvent={chatSseEvent} />
              </div>
            </ResizablePanel>
          </ResizablePanelGroup>
        )}
      </div>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
      <HelpOverlay open={helpOpen} onOpenChange={setHelpOpen} />
    </>
  )
}

export function AppShell() {
  return (
    <ShellStateProvider>
      <AppShellLayout />
    </ShellStateProvider>
  )
}
