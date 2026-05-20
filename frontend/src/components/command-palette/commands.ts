import { type LucideIcon, BookOpen, FolderOpen, Bot, Globe } from 'lucide-react'

export type Command = {
  id: string
  label: string
  group: 'Navigate' | 'Actions'
  icon: LucideIcon
  perform: (nav: (to: string) => void) => void
}

export const commands: Command[] = [
  { id: 'go-wiki', label: 'Go to Wiki', group: 'Navigate', icon: BookOpen, perform: (n) => n('/wiki') },
  { id: 'go-files', label: 'Go to Files', group: 'Navigate', icon: FolderOpen, perform: (n) => n('/files') },
  { id: 'go-automations', label: 'Go to Automations', group: 'Navigate', icon: Bot, perform: (n) => n('/automations') },
  { id: 'go-browser', label: 'Go to Browser', group: 'Navigate', icon: Globe, perform: (n) => n('/browser-chat') },
]
