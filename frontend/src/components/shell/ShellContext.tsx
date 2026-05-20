import { createContext, useContext } from 'react'

export type ShellContextValue = {
  openPalette: () => void
  openHelp: () => void
}

export const ShellContext = createContext<ShellContextValue>({
  openPalette: () => {},
  openHelp: () => {},
})

export function useShell(): ShellContextValue {
  return useContext(ShellContext)
}
