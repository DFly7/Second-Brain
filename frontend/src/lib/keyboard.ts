import { useEffect } from 'react'

export type ShortcutHandler = (id: string, e: KeyboardEvent) => void

export function useShortcuts(
  shortcuts: { id: string; match: (e: KeyboardEvent) => boolean }[],
  handler: ShortcutHandler,
) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement
      const isTyping = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable
      for (const s of shortcuts) {
        if (s.match(e)) {
          // Allow ⌘-key shortcuts even when typing, but block bare-key shortcuts (like '?')
          if (isTyping && !(e.metaKey || e.ctrlKey)) continue
          e.preventDefault()
          handler(s.id, e)
          return
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [shortcuts, handler])
}
