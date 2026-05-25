# UI/UX Improvements — Design Spec

## Overview

A coherent pass across the app's buttons, chat panels, and shell chrome. Goal: reduce visual noise, establish consistent interaction patterns, and fix a broken keyboard shortcut.

---

## 1. Icon Rail (`IconRail.tsx`)

**Changes:**
- Icons: `h-4 w-4` → `h-6 w-6` (24px). Hit targets: `h-9 w-9` → `h-11 w-11`. Rail width: `w-14` → `w-16`.
- Bottom cluster gains two new icon buttons (above Help):
  - **Activity** (`Activity` icon from lucide) — triggers the activity sheet (replaces the standalone Activity button row in WikiWorkspace). Tooltip: "Activity".
  - **Sign out** (`LogOut` icon from lucide) — calls `logout()`. Tooltip: "Sign out". Sits below Activity, above Help.
- Active nav indicator (the `before:` left bar) scales to match new hit target.

**Files:** `frontend/src/components/shell/IconRail.tsx`, `frontend/src/components/shell/WikiWorkspace.tsx`

---

## 2. Wiki Header / WikiWorkspace (`WikiWorkspace.tsx`)

**Changes:**
- Remove `Sign out` button from `contextActions`.
- Remove `agentStatus` SSE text from `contextActions`.
- Remove the `activityRow` element entirely (the second `<div>` row with the Activity button below the header).
- Remove `setShowActivity` prop threading to context bar — activity is now triggered from the icon rail.
- `contextActions` becomes: `+ Ingest` button only (+ existing `⌘K` button from ContextBar).

**Result:** Header is breadcrumbs · `+ Ingest` · `⌘K`. One less row of chrome, more vertical space for content.

**Files:** `frontend/src/components/shell/WikiWorkspace.tsx`

---

## 3. Browser Chat Toolbar (`BrowserChatPage.tsx`)

### 3a. Enter key bug fix
Change the textarea `onKeyDown` handler:
```
// Before
if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSend()

// After
if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
```
Update placeholder text: remove `(⌘↵ to send)`.

### 3b. Toolbar redesign
Replace the current four-item bottom row with:

**Above the textarea** — "Max turns for this message" row:
```
Max turns for this message    [−] [20] [+]
```
- Label left, `−` / number / `+` buttons right.
- `maxTurns` state remains but is now clearly scoped as "for next message".

**Below the textarea** — two items only:
```
[⋯]                                    [Send]
```
- `⋯` is a ghost icon button that opens a `DropdownMenu` containing:
  - "Recover Browser" — calls `handleRecover()`
  - separator
  - "Disconnect" — calls `handleDisconnect()`, styled destructive (red text)
- `Send` is the primary button, full weight.

**Files:** `frontend/src/components/BrowserChatPage.tsx`

---

## 4. Wiki Chat Panel (`ChatPanel.tsx`)

### 4a. Header redesign
Replace the current header (plain "Chat" label + "New Chat" + "History" outline buttons) with:

```
Chat  [● thinking]          [✏] [+] [🕐]
```

- **"Chat" label** — unchanged, muted text.
- **Agent status pill** — only rendered when `loading === true`. Small animated dot + "thinking" text. Style: `bg-primary/10 text-primary border border-primary/30 rounded-full px-2 py-0.5 text-xs`.
- **Edit Mode** (`Pencil` icon, 14px) — ghost icon button, `h-7 w-7`. Active state: `text-amber-500`. Tooltip: "Edit mode — agent can write to wiki pages" / "Read-only mode".
- **New Chat** (`SquarePen` icon, 14px) — ghost icon button, `h-7 w-7`. Tooltip: "New chat".
- **History** (`Clock` icon, 14px) — ghost icon button, `h-7 w-7`, active state when drawer open. Tooltip: "Chat history".

### 4b. Input row
Remove `Edit Mode` button from input row. Input row becomes:
```
[textarea flex-1]  [Send]
```
Add hint text below: `<p className="mt-1 text-right text-[10px] text-muted-foreground">Enter to send · Shift+Enter for newline</p>`

### 4c. Enter key
Add `onKeyDown` to wiki chat textarea (same pattern as browser chat fix):
```
if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleComposerSubmit() }
```
(This already exists in the current code — verify it's working.)

**Files:** `frontend/src/components/ChatPanel.tsx`

---

## 5. Message Bubbles (`ChatConversation.tsx`, `BrowserChatPage.tsx`)

User messages currently render as unstyled plain text. Change to right-aligned muted bubble in both chat surfaces.

**Style for user messages:**
```tsx
<div className="flex justify-end px-3 py-1">
  <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-muted px-3 py-2 text-sm text-foreground whitespace-pre-wrap break-words">
    {msg.content}
  </div>
</div>
```

- Right-aligned via `flex justify-end`
- `bg-muted` for the muted dark fill (maps to `#30363d` in dark theme)
- `rounded-2xl rounded-br-sm` for bubble shape (full radius except bottom-right corner)
- Apply to both `ChatConversation.tsx` and the user message branch in `BrowserChatPage.tsx`

**Files:** `frontend/src/components/ChatConversation.tsx`, `frontend/src/components/BrowserChatPage.tsx`

---

## 6. Activity Panel Tabs (`ActivityLog.tsx`)

Replace the three `Button` elements (using `variant="default"` / `variant="outline"`) with the shadcn `Tabs` component.

```tsx
// Before: three Button elements with variant toggling
// After:
<Tabs value={tab} onValueChange={(v) => setTab(v as typeof tab)}>
  <TabsList className="h-8">
    <TabsTrigger value="activity" className="text-xs">Activity</TabsTrigger>
    <TabsTrigger value="changes" className="text-xs">Changes</TabsTrigger>
    <TabsTrigger value="queue" className="text-xs">Queue</TabsTrigger>
  </TabsList>
</Tabs>
```

**Files:** `frontend/src/components/ActivityLog.tsx`

---

## 7. Health Check → Command Palette (`WikiTree.tsx`, `CommandPalette.tsx`)

Remove the `health check` button from the bottom of `WikiTree`. Add "Run health check" as a command palette action in `CommandPalette.tsx`.

- Find where the health check API call is made in `WikiTree.tsx` and extract the handler.
- Pass a `onHealthCheck` callback up through `ShellContext` or wire it via a `window` event (consistent with existing `chat:new-session` pattern).
- In `CommandPalette.tsx`, add a command item: label "Run health check", icon `Activity` or `HeartPulse`.

**Files:** `frontend/src/components/secondary-sidebar/WikiTree.tsx`, `frontend/src/components/command-palette/CommandPalette.tsx`, potentially `ShellContext.tsx`

---

## Non-goals

- No changes to mobile layout (WikiWorkspace mobile tab bar).
- No changes to routing, data fetching, or backend.
- No changes to assistant message styling.
