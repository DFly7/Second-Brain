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

function WikiLayout({ shellUi }: { shellUi: { openPalette: () => void; openHelp: () => void } }) {
  const { onSelectSlug, chatSseEvent } = useShellState()
  const sidebarRef = usePanelRef()
  const chatRef = usePanelRef()
  const { pathname } = useLocation()

  const handleShortcut = useCallback((id: string) => {
    if (id === 'sidebar') {
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
  }, [pathname, sidebarRef, chatRef])

  useShortcuts(shortcutsRegistry, handleShortcut)

  return (
    <ResizablePanelGroup
      id="wiki-shell"
      orientation="horizontal"
      className="h-full min-h-0 flex-1"
      resizeTargetMinimumSize={{ coarse: 28, fine: 10 }}
    >
      <ResizablePanel
        id="wiki-sidebar"
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
      <ResizablePanel id="wiki-main" defaultSize="53%" minSize="30%" className="min-w-0">
        <main className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
          <ShellContext.Provider value={shellUi}>
            <Outlet />
          </ShellContext.Provider>
        </main>
      </ResizablePanel>
      <ResizableHandle withHandle />
      <ResizablePanel
        id="wiki-chat"
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
  )
}

function AppShellLayout() {
  const isMobile = useIsMobile()
  const isWiki = useIsWiki()
  const { pathname } = useLocation()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)

  const handleShortcut = useCallback((id: string) => {
    if (id === 'palette') setPaletteOpen(true)
    else if (id === 'help') setHelpOpen(true)
    else if (id === 'newSession') {
      window.dispatchEvent(new CustomEvent('chat:new-session'))
    } else if (pathname.startsWith('/wiki')) {
      if (id === 'wikiSend') window.dispatchEvent(new CustomEvent('chat:send'))
      else if (id === 'wikiEdit') window.dispatchEvent(new CustomEvent('wiki:edit'))
      else if (id === 'wikiSave') window.dispatchEvent(new CustomEvent('wiki:save'))
    }
  }, [pathname])

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
        ) : isWiki ? (
          <WikiLayout shellUi={shellUi} />
        ) : (
          <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
            <ShellContext.Provider value={shellUi}>
              <Outlet />
            </ShellContext.Provider>
          </main>
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
