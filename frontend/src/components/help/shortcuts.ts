export type Shortcut = {
  id: string
  keys: string          // human label, e.g. "⌘ K"
  match: (e: KeyboardEvent) => boolean
  description: string
  group: 'Navigation' | 'Chat' | 'Wiki'
}

const mod = (e: KeyboardEvent) => e.metaKey || e.ctrlKey

export const shortcuts: Shortcut[] = [
  { id: 'palette',     keys: '⌘ K',     group: 'Navigation', description: 'Open command palette',   match: (e) => mod(e) && e.key.toLowerCase() === 'k' },
  { id: 'sidebar',     keys: '⌘ B',     group: 'Navigation', description: 'Toggle secondary sidebar', match: (e) => mod(e) && e.key.toLowerCase() === 'b' },
  { id: 'chat',        keys: '⌘ J',     group: 'Navigation', description: 'Toggle chat panel',       match: (e) => mod(e) && e.key.toLowerCase() === 'j' },
  { id: 'help',        keys: '?',       group: 'Navigation', description: 'Show keyboard shortcuts', match: (e) => e.key === '?' && !mod(e) },
  { id: 'wikiSend',    keys: '⌘ Enter', group: 'Chat',       description: 'Send message',            match: (e) => mod(e) && e.key === 'Enter' },
  { id: 'newSession',  keys: '⌘ N',     group: 'Chat',       description: 'New chat session',         match: (e) => mod(e) && e.key.toLowerCase() === 'n' },
  { id: 'wikiEdit',    keys: '⌘ E',     group: 'Wiki',       description: 'Edit current page',       match: (e) => mod(e) && e.key.toLowerCase() === 'e' },
  { id: 'wikiSave',    keys: '⌘ S',     group: 'Wiki',       description: 'Save current page',       match: (e) => mod(e) && e.key.toLowerCase() === 's' },
]
