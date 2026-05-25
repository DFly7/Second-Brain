import { NavLink } from 'react-router-dom'
import { BookOpen, FolderOpen, Bot, Globe, HelpCircle, Activity, LogOut } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { logout } from '@/auth'

const navLinkClass =
  'relative flex h-11 w-11 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background'

const sections = [
  { to: '/wiki', icon: BookOpen, label: 'Wiki' },
  { to: '/files', icon: FolderOpen, label: 'Files' },
  { to: '/automations', icon: Bot, label: 'Automations' },
  { to: '/browser-chat', icon: Globe, label: 'Browser' },
]

export function IconRail({
  onOpenHelp,
  onShowActivity,
}: {
  onOpenHelp: () => void
  onShowActivity: () => void
}) {
  return (
    <TooltipProvider delayDuration={300}>
      <nav className="flex h-full w-16 flex-col items-center border-r border-border bg-background py-3">
        <div className="flex flex-1 flex-col gap-1">
          {sections.map(({ to, icon: Icon, label }) => (
            <Tooltip key={to}>
              <TooltipTrigger asChild>
                <NavLink
                  to={to}
                  aria-label={label}
                  className={({ isActive }) =>
                    cn(
                      navLinkClass,
                      isActive &&
                        'bg-muted text-foreground before:absolute before:left-[-10px] before:top-1/2 before:h-5 before:w-0.5 before:-translate-y-1/2 before:rounded-r before:bg-primary'
                    )
                  }
                >
                  <Icon className="h-6 w-6" />
                </NavLink>
              </TooltipTrigger>
              <TooltipContent side="right">{label}</TooltipContent>
            </Tooltip>
          ))}
        </div>
        <div className="flex flex-col gap-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-11 w-11 text-muted-foreground"
                aria-label="Activity"
                onClick={onShowActivity}
              >
                <Activity className="h-6 w-6" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">Activity</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-11 w-11 text-muted-foreground"
                aria-label="Help"
                onClick={onOpenHelp}
              >
                <HelpCircle className="h-6 w-6" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">Help (?)</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-11 w-11 text-muted-foreground hover:text-destructive"
                aria-label="Sign out"
                onClick={() => logout()}
              >
                <LogOut className="h-6 w-6" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">Sign out</TooltipContent>
          </Tooltip>
        </div>
      </nav>
    </TooltipProvider>
  )
}
