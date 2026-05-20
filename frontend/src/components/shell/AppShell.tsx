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
import ChatPanel from '@/components/ChatPanel'
import { useIsMobile } from '@/hooks/useIsMobile'
import { useShortcuts } from '@/lib/keyboard'
import { toast } from '@/lib/toast'
import { shortcuts as shortcutsRegistry } from '@/components/help/shortcuts'
import { CommandPalette } from '@/components/command-palette/CommandPalette'
import { HelpOverlay } from '@/components/help/HelpOverlay'

/** Both sidebar and chat are wiki-only — other routes get a full-width main panel. */
function useIsWiki() {
  const { pathname } = useLocation()
  return pathname.startsWith('/wiki')
}


function SecondaryForRoute() {
  const { selectedSlug, highlightedSlug, onSelectSlug } = useShellState()

  return (
    <WikiTree
      selectedSlug={selectedSlug}
      highlightedSlug={highlightedSlug}
      onSelect={onSelectSlug}
    />
  )
}

function AppShellLayout() {
  const isMobile = useIsMobile()
  const isWiki = useIsWiki()
  const { pathname } = useLocation()
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
    } else if (id === 'newSession') {
      window.dispatchEvent(new CustomEvent('chat:new-session'))
    } else if (pathname.startsWith('/wiki')) {
      if (id === 'wikiSend') window.dispatchEvent(new CustomEvent('chat:send'))
      else if (id === 'wikiEdit') window.dispatchEvent(new CustomEvent('wiki:edit'))
      else if (id === 'wikiSave') window.dispatchEvent(new CustomEvent('wiki:save'))
    }
  }, [pathname])

  useShortcuts(shortcutsRegistry, handleShortcut)

  // Sidebar and chat are wiki-only — collapse both when navigating away
  useEffect(() => {
    const sidebar = sidebarRef.current
    const chat = chatRef.current
    if (isWiki) {
      sidebar?.expand()
      chat?.expand()
    } else {
      sidebar?.collapse()
      chat?.collapse()
    }
  }, [isWiki])

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
          <ResizablePanelGroup
            id="app-shell"
            orientation="horizontal"
            className="h-full min-h-0 flex-1"
            resizeTargetMinimumSize={{ coarse: 28, fine: 10 }}
          >
            <ResizablePanel
              id="secondary-sidebar"
              panelRef={sidebarRef}
              defaultSize="22%"
              minSize="16%"
              maxSize="40%"
              collapsible
              collapsedSize="0%"
              className="min-w-0"
            >
              <div className="h-full min-w-0 overflow-hidden">
                <SecondaryForRoute />
              </div>
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel
              id="main"
              defaultSize="53%"
              minSize="30%"
              className="min-w-0"
            >
              <main className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
                <ShellContext.Provider value={shellUi}>
                  <Outlet />
                </ShellContext.Provider>
              </main>
            </ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel
              id="chat"
              panelRef={chatRef}
              defaultSize="25%"
              minSize="18%"
              maxSize="50%"
              collapsible
              collapsedSize="0%"
              className="min-w-0"
            >
              <div className="h-full min-w-0 overflow-hidden">
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
