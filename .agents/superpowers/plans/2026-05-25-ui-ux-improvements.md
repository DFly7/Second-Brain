# UI/UX Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up buttons, chat panels, and shell chrome across the app — reduce noise, fix an Enter-key bug, establish consistent interaction patterns.

**Architecture:** Pure frontend changes across 7 components. No backend, no routing, no new dependencies beyond lucide-react icons already in use. Tasks are ordered so each produces a visually complete, shippable change.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, shadcn/ui, lucide-react, react-router-dom

---

## File Map

| File | What changes |
|---|---|
| `frontend/src/components/shell/IconRail.tsx` | Bigger icons, add Activity + Sign out to bottom cluster |
| `frontend/src/components/shell/AppShell.tsx` | Pass `onShowActivity` to `IconRail` |
| `frontend/src/components/shell/WikiWorkspace.tsx` | Remove Sign out, agentStatus, Activity row; wire Activity to rail |
| `frontend/src/components/BrowserChatPage.tsx` | Fix Enter bug, redesign toolbar (Turns above, ⋯ + Send below) |
| `frontend/src/components/ChatPanel.tsx` | Header icons, status pill, remove Edit Mode from input row |
| `frontend/src/components/ChatConversation.tsx` | User message bubble styling |
| `frontend/src/components/ActivityLog.tsx` | Swap Button tabs for shadcn Tabs |
| `frontend/src/components/secondary-sidebar/WikiTree.tsx` | Remove health check button |
| `frontend/src/components/command-palette/commands.ts` | Add "Run health check" command |

---

## Task 1: Icon Rail — bigger icons + Activity + Sign out

**Files:**
- Modify: `frontend/src/components/shell/IconRail.tsx`
- Modify: `frontend/src/components/shell/WikiWorkspace.tsx`

- [ ] **Step 1: Update IconRail to accept onShowActivity prop and add new bottom icons**

Replace the entire contents of `frontend/src/components/shell/IconRail.tsx` with:

```tsx
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
```

- [ ] **Step 2: Wire onShowActivity in WikiWorkspace and AppShell**

In `frontend/src/components/shell/AppShell.tsx`, find where `IconRail` is rendered and add the `onShowActivity` prop. Search for `<IconRail` — it will look something like:

```tsx
<IconRail onOpenHelp={shellUi.openHelp} />
```

Change it to:

```tsx
<IconRail onOpenHelp={shellUi.openHelp} onShowActivity={() => setShowActivity(true)} />
```

If `setShowActivity` is not in scope at that call site, check how `showActivity` is currently managed. In `WikiWorkspace.tsx` it comes from `useShellState()`. You may need to lift the `onShowActivity` callback via `ShellContext` or pass it through `WikiLayout`. Check `AppShell.tsx` to see how it renders `IconRail` vs `WikiWorkspace` and thread accordingly.

- [ ] **Step 3: Verify in browser**

Run `cd frontend && npm run dev`, open http://localhost:5173. Confirm:
- Rail is slightly wider
- All nav icons are visibly larger (24px)
- Activity, Help, Sign out icons appear at the bottom
- Clicking Activity opens the activity sheet
- Clicking Sign out logs out

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/shell/IconRail.tsx frontend/src/components/shell/AppShell.tsx
git commit -m "feat(ui): icon rail — 24px icons, add Activity + Sign out to bottom"
```

---

## Task 2: Wiki Header — strip Sign out, agentStatus, Activity row

**Files:**
- Modify: `frontend/src/components/shell/WikiWorkspace.tsx`

- [ ] **Step 1: Remove Sign out, agentStatus, and activityRow from WikiWorkspace**

Open `frontend/src/components/shell/WikiWorkspace.tsx`. Make the following changes:

1. Remove the `logout` import if it's only used for Sign out.
2. Change `contextActions` from:
```tsx
const contextActions = (
  <>
    {agentStatus && (
      <span className="text-xs text-primary">⟳ {agentStatus}</span>
    )}
    <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => setShowIngest(true)}>
      + Ingest
    </Button>
    <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => logout()}>
      Sign out
    </Button>
  </>
)
```
To:
```tsx
const contextActions = (
  <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => setShowIngest(true)}>
    + Ingest
  </Button>
)
```

3. Remove the `activityRow` const and its usage. Delete:
```tsx
const activityRow = (
  <div className="flex shrink-0 justify-end border-b border-border bg-background px-4 py-1">
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="h-6 text-xs"
      onClick={() => setShowActivity(!showActivity)}
    >
      Activity
    </Button>
  </div>
)
```
And remove `{activityRow}` from both the desktop and mobile return JSX.

- [ ] **Step 2: Verify in browser**

Reload http://localhost:5173/wiki. Confirm:
- Header shows only breadcrumbs, `+ Ingest`, and `⌘K`
- No "Sign out" button in header
- No "Activity" row below the header
- Page content gets the extra vertical space

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/shell/WikiWorkspace.tsx
git commit -m "feat(ui): strip Sign out, agentStatus, and Activity row from wiki header"
```

---

## Task 3: Browser Chat — fix Enter key bug

**Files:**
- Modify: `frontend/src/components/BrowserChatPage.tsx`

- [ ] **Step 1: Fix the onKeyDown handler**

In `frontend/src/components/BrowserChatPage.tsx`, find the `Textarea` with the `onKeyDown` prop. It currently reads:

```tsx
onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSend() }}
```

Change it to:

```tsx
onKeyDown={e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}}
```

Also update the placeholder (on the same `Textarea`). Change:

```tsx
placeholder={agentRunning ? 'Agent is working…' : 'Tell the agent what to do… (⌘↵ to send)'}
```

To:

```tsx
placeholder={agentRunning ? 'Agent is working…' : 'Tell the agent what to do…'}
```

- [ ] **Step 2: Verify in browser**

Navigate to http://localhost:5173/browser-chat. Connect a session. Type a message and press Enter — confirm it sends. Press Shift+Enter — confirm it adds a newline instead.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/BrowserChatPage.tsx
git commit -m "fix(browser-chat): Enter sends message, Shift+Enter inserts newline"
```

---

## Task 4: Browser Chat — toolbar redesign

**Files:**
- Modify: `frontend/src/components/BrowserChatPage.tsx`

- [ ] **Step 1: Add DropdownMenu import**

At the top of `frontend/src/components/BrowserChatPage.tsx`, add to the imports:

```tsx
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { MoreHorizontal } from 'lucide-react'
```

- [ ] **Step 2: Replace the bottom toolbar JSX**

Find the `<div className="shrink-0 space-y-2 border-t border-border p-3">` block inside the chat panel (the connected state). Replace the entire block with:

```tsx
<div className="shrink-0 border-t border-border p-3 space-y-2">
  <div className="flex items-center justify-between gap-2">
    <label className="text-xs text-muted-foreground">Max turns for this message</label>
    <div className="flex items-center gap-1">
      <Button
        type="button"
        variant="outline"
        size="icon"
        className="h-6 w-6 text-xs"
        onClick={() => setMaxTurns(t => Math.max(1, t - 1))}
        disabled={agentRunning}
      >
        −
      </Button>
      <span className="w-8 text-center text-sm tabular-nums">{maxTurns}</span>
      <Button
        type="button"
        variant="outline"
        size="icon"
        className="h-6 w-6 text-xs"
        onClick={() => setMaxTurns(t => Math.min(100, t + 1))}
        disabled={agentRunning}
      >
        +
      </Button>
    </div>
  </div>
  <Textarea
    ref={inputRef}
    value={input}
    onChange={e => setInput(e.target.value)}
    onKeyDown={e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    }}
    disabled={agentRunning}
    placeholder={agentRunning ? 'Agent is working…' : 'Tell the agent what to do…'}
    rows={3}
    className="min-h-0 resize-none text-sm"
  />
  <div className="flex items-center justify-between gap-2">
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-8 w-8 text-muted-foreground"
          disabled={agentRunning}
        >
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuItem
          onClick={handleRecover}
          disabled={recovering || agentRunning}
        >
          {recovering ? 'Recovering…' : 'Recover Browser'}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onClick={handleDisconnect}
          className="text-destructive focus:text-destructive"
        >
          Disconnect
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
    <Button
      type="button"
      size="sm"
      onClick={handleSend}
      disabled={!input.trim() || agentRunning}
    >
      Send
    </Button>
  </div>
</div>
```

Note: this block already contains the correct `onKeyDown` handler. If you completed Task 3 first, that earlier edit is superseded by this full replacement — no extra steps needed.

- [ ] **Step 3: Verify in browser**

Navigate to http://localhost:5173/browser-chat and connect. Confirm:
- Turns control is above the textarea with − and + buttons
- Bottom row shows only `⋯` and `Send`
- Clicking `⋯` reveals Recover Browser and Disconnect
- Disconnect is red
- Enter still sends

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/BrowserChatPage.tsx
git commit -m "feat(browser-chat): redesign toolbar — turns above input, secondary actions in overflow menu"
```

---

## Task 5: Wiki Chat Panel — header icons + status pill + clean input row

**Files:**
- Modify: `frontend/src/components/ChatPanel.tsx`

- [ ] **Step 1: Add new icon imports**

At the top of `frontend/src/components/ChatPanel.tsx`, add to imports:

```tsx
import { Pencil, SquarePen, Clock } from 'lucide-react'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
```

- [ ] **Step 2: Replace the panel header**

Find the header `<div className="flex h-10 shrink-0 items-center justify-between border-b border-border px-3">` and replace it with:

```tsx
<TooltipProvider delayDuration={300}>
  <div className="flex h-10 shrink-0 items-center justify-between border-b border-border px-3">
    <div className="flex items-center gap-2">
      <span className="text-sm text-muted-foreground">Chat</span>
      {loading && (
        <span className="flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-xs text-primary">
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
          thinking
        </span>
      )}
    </div>
    <div className="flex items-center gap-0.5">
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className={cn('h-7 w-7', editMode && 'text-amber-500')}
            onClick={() => setEditMode(v => !v)}
          >
            <Pencil className="h-3.5 w-3.5" />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="bottom">
          {editMode ? 'Edit mode — agent can write to wiki pages' : 'Read-only mode'}
        </TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={handleNewChat}
          >
            <SquarePen className="h-3.5 w-3.5" />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="bottom">New chat</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className={cn('h-7 w-7', drawerOpen && 'bg-muted text-foreground')}
            onClick={() => setDrawerOpen(v => !v)}
          >
            <Clock className="h-3.5 w-3.5" />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="bottom">Chat history</TooltipContent>
      </Tooltip>
    </div>
  </div>
</TooltipProvider>
```

- [ ] **Step 3: Clean up the input row**

Find the input area at the bottom of ChatPanel. Replace it with:

```tsx
<div
  className={cn(
    'shrink-0 border-t border-border p-3',
    editMode && 'bg-amber-500/5 ring-1 ring-inset ring-amber-500/40',
  )}
>
  <div className="flex items-end gap-2">
    <Textarea
      value={input}
      onChange={e => setInput(e.target.value)}
      onKeyDown={e => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault()
          handleComposerSubmit()
        }
      }}
      placeholder="Ask your wiki..."
      rows={2}
      disabled={loading}
      className="min-h-0 flex-1 resize-none text-sm"
    />
    <Button
      type="button"
      size="sm"
      onClick={handleComposerSubmit}
      disabled={loading || !input.trim()}
      className="shrink-0"
    >
      Send
    </Button>
  </div>
  <p className="mt-1 text-right text-[10px] text-muted-foreground">
    Enter to send · Shift+Enter for newline
  </p>
</div>
```

- [ ] **Step 4: Verify in browser**

Navigate to http://localhost:5173/wiki. Confirm:
- Chat header shows: "Chat" label · pencil icon · + icon · clock icon
- Pencil icon turns amber when edit mode is active
- Tooltips appear on hover
- Agent "thinking" pill appears during a query
- Input row has no Edit Mode button
- Hint text shows below the input
- Enter sends, Shift+Enter newlines

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ChatPanel.tsx
git commit -m "feat(chat-panel): icon header with status pill, clean input row"
```

---

## Task 6: User message bubbles

**Files:**
- Modify: `frontend/src/components/ChatConversation.tsx`
- Modify: `frontend/src/components/BrowserChatPage.tsx`

- [ ] **Step 1: Update user message style in ChatConversation.tsx**

In `frontend/src/components/ChatConversation.tsx`, find the user message branch:

```tsx
m.role === 'user' ? (
  <div key={i} className="px-3 py-2 text-sm text-foreground">
    {m.content}
  </div>
) : (
```

Replace with:

```tsx
m.role === 'user' ? (
  <div key={i} className="flex justify-end px-3 py-1">
    <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-sm bg-muted px-3 py-2 text-sm text-foreground">
      {m.content}
    </div>
  </div>
) : (
```

- [ ] **Step 2: Update user message style in BrowserChatPage.tsx**

In `frontend/src/components/BrowserChatPage.tsx`, find the user message branch inside `messages.map`:

```tsx
msg.role === 'user' ? (
  <div
    key={msg.id}
    className="whitespace-pre-wrap break-words px-3 py-2 text-sm text-foreground"
  >
    {msg.content}
  </div>
) : (
```

Replace with:

```tsx
msg.role === 'user' ? (
  <div key={msg.id} className="flex justify-end px-3 py-1">
    <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-sm bg-muted px-3 py-2 text-sm text-foreground">
      {msg.content}
    </div>
  </div>
) : (
```

- [ ] **Step 3: Verify in browser**

Send a message in both the wiki chat and the browser chat. Confirm user messages appear right-aligned with a muted dark bubble. Assistant messages remain left-aligned in their card.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ChatConversation.tsx frontend/src/components/BrowserChatPage.tsx
git commit -m "feat(chat): right-aligned muted bubble for user messages"
```

---

## Task 7: Activity panel — proper Tabs

**Files:**
- Modify: `frontend/src/components/ActivityLog.tsx`

- [ ] **Step 1: Replace Button tab group with shadcn Tabs**

In `frontend/src/components/ActivityLog.tsx`:

1. Remove the `tabBtn` helper function entirely.

2. Add Tabs to the import:
```tsx
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
```

3. Find the sheet header `<div className="flex items-center gap-2 border-b border-border px-4 py-3 pr-12">` and replace its contents:

```tsx
<div className="flex items-center border-b border-border px-4 py-2 pr-12">
  <Tabs value={tab} onValueChange={(v) => setTab(v as typeof tab)}>
    <TabsList className="h-8">
      <TabsTrigger value="activity" className="text-xs">Activity</TabsTrigger>
      <TabsTrigger value="changes" className="text-xs">Changes</TabsTrigger>
      <TabsTrigger value="queue" className="text-xs">Queue</TabsTrigger>
    </TabsList>
  </Tabs>
</div>
```

- [ ] **Step 2: Verify in browser**

Open the Activity sheet (click the Activity icon in the rail). Confirm:
- Activity / Changes / Queue look like proper tabs (pill or underline style, not outline/filled buttons)
- Switching tabs works
- Active tab is visually distinct

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ActivityLog.tsx
git commit -m "feat(activity): replace button tabs with shadcn Tabs component"
```

---

## Task 8: Health Check → Command Palette

**Files:**
- Modify: `frontend/src/components/secondary-sidebar/WikiTree.tsx`
- Modify: `frontend/src/components/command-palette/commands.ts`

- [ ] **Step 1: Remove health check button from WikiTree**

In `frontend/src/components/secondary-sidebar/WikiTree.tsx`:

1. Remove the `healthRunning` state:
```tsx
// Delete this line:
const [healthRunning, setHealthRunning] = useState(false)
```

2. Remove the `handleHealthRun` function:
```tsx
// Delete this entire function:
async function handleHealthRun() {
  if (healthRunning) return
  setHealthRunning(true)
  try {
    await runHealthCheck()
  } finally {
    setTimeout(() => setHealthRunning(false), 3000)
  }
}
```

3. Remove the bottom `<div>` containing the button:
```tsx
// Delete this entire block:
<div className="shrink-0 border-t border-border p-2">
  <Button
    type="button"
    variant="outline"
    size="sm"
    onClick={handleHealthRun}
    disabled={healthRunning}
    className={cn(
      'h-auto w-full px-2 py-1.5 text-[11px] tracking-wide',
      healthRunning && 'text-muted-foreground/50',
    )}
  >
    {healthRunning ? 'running health check…' : '⚕ health check'}
  </Button>
</div>
```

4. If `runHealthCheck` is now unused in this file, remove its import from `'../api/client'`.
5. If `Button` and `cn` are now unused in this file, remove those imports too. Check carefully — `cn` and `Button` may still be used elsewhere in this file.

- [ ] **Step 2: Add health check command to command palette**

In `frontend/src/components/command-palette/commands.ts`, add the `HeartPulse` import and a new command:

```ts
import { type LucideIcon, BookOpen, FolderOpen, Bot, Globe, HeartPulse } from 'lucide-react'
import { runHealthCheck } from '@/api/client'

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
  { id: 'health-check', label: 'Run health check', group: 'Actions', icon: HeartPulse, perform: () => { runHealthCheck() } },
]
```

- [ ] **Step 3: Verify in browser**

1. Open the wiki sidebar — confirm no health check button at the bottom.
2. Press ⌘K — confirm "Run health check" appears under an "Actions" group.
3. Select it — confirm it runs (watch network tab or check the wiki meta/health-report page for an updated timestamp).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/secondary-sidebar/WikiTree.tsx frontend/src/components/command-palette/commands.ts
git commit -m "feat(ui): move health check from wiki sidebar to command palette"
```

---

## Final verification

- [ ] Run `cd frontend && npm run build` — confirm no TypeScript errors
- [ ] Run `make lint` from repo root — confirm no ruff/mypy issues (backend unchanged, but good habit)
- [ ] Do a full walkthrough: wiki, browser chat, activity panel, command palette — confirm all changes look correct together
