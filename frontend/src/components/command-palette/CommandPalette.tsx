import { useNavigate } from 'react-router-dom'
import {
  CommandDialog,
  CommandInput,
  CommandList,
  CommandEmpty,
  CommandGroup,
  CommandItem,
} from '@/components/ui/command'
import { commands } from './commands'

export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
}) {
  const navigate = useNavigate()
  const groups = Array.from(new Set(commands.map((c) => c.group)))

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput placeholder="Type a command or search…" />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>
        {groups.map((g) => (
          <CommandGroup key={g} heading={g}>
            {commands
              .filter((c) => c.group === g)
              .map((c) => {
                const Icon = c.icon
                return (
                  <CommandItem
                    key={c.id}
                    onSelect={() => {
                      onOpenChange(false)
                      c.perform(navigate)
                    }}
                  >
                    <Icon className="h-4 w-4" />
                    <span className="ml-2">{c.label}</span>
                  </CommandItem>
                )
              })}
          </CommandGroup>
        ))}
      </CommandList>
    </CommandDialog>
  )
}
