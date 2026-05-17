# Mobile Responsive Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Smooth Study site fully usable on mobile screens (<768px) while leaving the desktop layout completely unchanged.

**Architecture:** A `useIsMobile` hook (MediaQueryList-based) gates two alternative render paths in `Layout.tsx` and `FilesView.tsx`. On mobile, the wiki's 3-panel resizable layout becomes a bottom-tab single-panel view (Pages / Content / Chat). The files view becomes a full-width list that drills into a full-width viewer with a back button.

**Tech Stack:** React 18, TypeScript, inline styles (matching existing pattern), Vite/Vitest for frontend, no new dependencies.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `frontend/src/hooks/useIsMobile.ts` | Returns `true` when viewport < 768px; updates on resize |
| Modify | `frontend/src/components/Layout.tsx` | Add mobile tab-based layout branch |
| Modify | `frontend/src/components/FilesView.tsx` | Add mobile stacked layout branch |
| Modify | `frontend/src/components/FileViewer.tsx` | Accept optional `onBack` prop; render back button in header |
| Modify | `frontend/src/components/FilesList.tsx` | Accept optional `fullWidth` prop; fill container width when true |

---

## Task 1: `useIsMobile` hook

**Files:**
- Create: `frontend/src/hooks/useIsMobile.ts`

- [ ] **Step 1: Create the hook**

```ts
import { useState, useEffect } from 'react'

export function useIsMobile(breakpoint = 768): boolean {
  const [isMobile, setIsMobile] = useState(
    () => window.matchMedia(`(max-width: ${breakpoint - 1}px)`).matches
  )

  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${breakpoint - 1}px)`)
    const onChange = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    setIsMobile(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [breakpoint])

  return isMobile
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/hooks/useIsMobile.ts
git commit -m "feat(mobile): add useIsMobile hook"
```

---

## Task 2: `FilesList` fullWidth prop

**Files:**
- Modify: `frontend/src/components/FilesList.tsx`

`FilesList` hardcodes `width: 240`. On mobile we show it filling the full viewport width, so it needs a `fullWidth` prop to override this.

- [ ] **Step 1: Add `fullWidth` prop to `FilesListProps` interface**

In `frontend/src/components/FilesList.tsx`, update the interface and both render paths:

```tsx
interface FilesListProps {
  sources: SourceItem[]
  selectedId: string | null
  onSelect: (id: string) => void
  onInfo: (id: string) => void
  fullWidth?: boolean
}
```

Change the empty-state div (line 46):
```tsx
// OLD
<div style={{ width: 240, borderRight: '1px solid #21262d', padding: 16, color: '#8b949e', fontSize: 13 }}>
// NEW
<div style={{ width: fullWidth ? '100%' : 240, borderRight: fullWidth ? 'none' : '1px solid #21262d', padding: 16, color: '#8b949e', fontSize: 13 }}>
```

Change the main list div (line 53):
```tsx
// OLD
<div style={{ width: 240, borderRight: '1px solid #21262d', overflowY: 'auto', padding: 8, flexShrink: 0 }}>
// NEW
<div style={{ width: fullWidth ? '100%' : 240, borderRight: fullWidth ? 'none' : '1px solid #21262d', overflowY: 'auto', padding: 8, flexShrink: 0 }}>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/FilesList.tsx
git commit -m "feat(mobile): add fullWidth prop to FilesList"
```

---

## Task 3: `FileViewer` back button

**Files:**
- Modify: `frontend/src/components/FileViewer.tsx`

On mobile, when a file is selected in `FilesView` we show `FileViewer` full-screen. The user needs a way to return to the list. An optional `onBack` prop renders a back button in the viewer header.

- [ ] **Step 1: Add `onBack` to `FileViewerProps` and render the back button**

Update the `FileViewerProps` interface at the top of `frontend/src/components/FileViewer.tsx`:

```tsx
interface FileViewerProps {
  source: SourceItem | null
  onBack?: () => void
}
```

Update the function signature:
```tsx
export default function FileViewer({ source, onBack }: FileViewerProps) {
```

In the "no source selected" empty state, also thread through the back button for consistency:
```tsx
if (!source) {
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {onBack && (
        <div style={{ padding: '8px 14px', borderBottom: '1px solid #21262d', flexShrink: 0 }}>
          <button type="button" onClick={onBack} style={btnStyle}>← Back</button>
        </div>
      )}
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#8b949e', fontSize: 13 }}>
        Select a file to view it.
      </div>
    </div>
  )
}
```

In the main return (the header row, around line 45–86), add the back button as the first element inside the header div:

```tsx
<div style={{
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  padding: '8px 14px',
  borderBottom: '1px solid #21262d',
  flexShrink: 0,
}}>
  {onBack && (
    <button type="button" onClick={onBack} style={btnStyle}>← Back</button>
  )}
  <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: '#e6edf3', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
    {source.title ?? `${source.kind} · ${source.id.slice(0, 8).toUpperCase()}`}
  </span>
  {/* ... rest of header unchanged ... */}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/FileViewer.tsx
git commit -m "feat(mobile): add onBack prop to FileViewer"
```

---

## Task 4: Mobile layout for FilesView

**Files:**
- Modify: `frontend/src/components/FilesView.tsx`

On mobile, show the file list full-width when nothing is selected, or the viewer full-width (with back button) when a file is selected.

- [ ] **Step 1: Import `useIsMobile` and add mobile render branch**

At the top of `frontend/src/components/FilesView.tsx`, add the import:

```tsx
import { useIsMobile } from '../hooks/useIsMobile'
```

Inside `FilesView`, add the hook call after the existing state/hooks:

```tsx
const isMobile = useIsMobile()
```

Add the mobile render branch just before the existing `return` (so the desktop return stays unchanged):

```tsx
if (isMobile) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <TopBar />
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {selectedId === null ? (
          <FilesList
            sources={sources ?? []}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onInfo={setInfoId}
            fullWidth
          />
        ) : (
          <FileViewer source={selectedSource} onBack={() => setSelectedId(null)} />
        )}
      </div>
      {infoSource && (
        <SourceMetaModal source={infoSource} onClose={() => setInfoId(null)} />
      )}
    </div>
  )
}
```

The existing desktop `return` stays exactly as-is below this block.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/FilesView.tsx
git commit -m "feat(mobile): mobile-responsive FilesView with full-width list and back button"
```

---

## Task 5: Mobile layout for Wiki (Layout)

**Files:**
- Modify: `frontend/src/components/Layout.tsx`

On mobile, replace the 3-panel resizable layout with a bottom tab bar. One panel is visible at a time. Selecting a page from "Pages" automatically switches to "Content". Chat navigation also switches to "Content".

- [ ] **Step 1: Import `useIsMobile` and add mobile state**

At the top of `frontend/src/components/Layout.tsx`, add the import alongside existing imports:

```tsx
import { useIsMobile } from '../hooks/useIsMobile'
```

Inside the `Layout` component, after the existing `useState` calls, add:

```tsx
const isMobile = useIsMobile()
const [activeTab, setActiveTab] = useState<'pages' | 'content' | 'chat'>('content')
```

- [ ] **Step 2: Add mobile-aware navigation handlers**

Add these two handler functions inside the `Layout` component, after the existing `useMemo` / `useEffect` blocks (before the `return`):

```tsx
function handleMobileSelect(slug: string) {
  setSelectedSlug(slug)
  if (isMobile) setActiveTab('content')
}

function handleMobileNavigate(slug: string) {
  setSelectedSlug(slug)
  if (isMobile) setActiveTab('content')
}
```

- [ ] **Step 3: Add mobile render branch**

Add the following block just before the existing `return (` statement. The existing desktop `return` stays unchanged below it.

```tsx
if (isMobile) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <TopBar agentStatus={agentStatus} onShowIngest={() => setShowIngest(true)} />

      {/* Activity row */}
      <div style={{
        display: 'flex',
        justifyContent: 'flex-end',
        padding: '4px 16px',
        background: '#161b22',
        borderBottom: '1px solid #30363d',
      }}>
        <button
          type="button"
          onClick={() => setShowActivity(!showActivity)}
          style={{
            padding: '2px 10px',
            background: '#21262d',
            border: '1px solid #30363d',
            borderRadius: 6,
            color: '#e6edf3',
            cursor: 'pointer',
            fontSize: 12,
          }}
        >
          Activity
        </button>
      </div>

      {/* Active panel */}
      <div style={{ flex: 1, overflow: 'hidden' }}>
        {activeTab === 'pages' && (
          <WikiSidebar
            selectedSlug={selectedSlug}
            highlightedSlug={highlightedSlug}
            onSelect={handleMobileSelect}
          />
        )}
        {activeTab === 'content' && (
          <WikiContent selectedSlug={selectedSlug} onNavigate={handleMobileNavigate} />
        )}
        {activeTab === 'chat' && (
          <ChatPanel onNavigate={handleMobileNavigate} activeSseEvent={chatSseEvent} />
        )}
      </div>

      {/* Bottom tab bar */}
      <div style={{
        display: 'flex',
        borderTop: '2px solid #30363d',
        background: '#161b22',
        flexShrink: 0,
      }}>
        {([
          { id: 'pages', label: '≡ Pages' },
          { id: 'content', label: '□ Content' },
          { id: 'chat', label: '◎ Chat' },
        ] as const).map(({ id, label }) => (
          <button
            key={id}
            type="button"
            onClick={() => setActiveTab(id)}
            style={{
              flex: 1,
              padding: '12px 0',
              border: 'none',
              borderTop: activeTab === id ? '2px solid #58a6ff' : '2px solid transparent',
              marginTop: -2,
              background: 'none',
              color: activeTab === id ? '#58a6ff' : '#6e7681',
              fontSize: 13,
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {showActivity && (
        <ActivityLog
          onClose={() => setShowActivity(false)}
          queue={queue}
          onClearQueue={() => queueActions.clear()}
        />
      )}
      {showIngest && (
        <IngestModal
          onClose={() => setShowIngest(false)}
          queue={queue}
          onUpsertQueueItems={items => queueActions.upsertMany(items)}
          onPatchQueueById={(id, patch) =>
            setQueue(s => reduceQueue(s, { type: 'patch_by_id', id, patch }))
          }
        />
      )}
    </div>
  )
}
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Layout.tsx
git commit -m "feat(mobile): mobile-responsive Wiki layout with bottom tab navigation"
```

---

## Task 6: Verify visually in browser

- [ ] **Step 1: Start the dev server**

```bash
cd frontend && npm run dev
```

- [ ] **Step 2: Open browser DevTools → toggle device toolbar (Cmd+Shift+M in Chrome)**

Set width to 390px (iPhone 14 size).

- [ ] **Step 3: Verify Wiki view (navigate to `/wiki`)**

Check all of the following:
- Bottom tab bar shows "≡ Pages", "□ Content", "◎ Chat"
- "□ Content" tab is active by default (shows empty content prompt)
- Tapping "≡ Pages" shows the sidebar tree full-screen
- Tapping a page switches to "□ Content" tab and shows that page
- Tapping "◎ Chat" shows the chat panel full-screen
- Asking a question in Chat and clicking a cited page link switches to "□ Content" tab
- Tapping "Activity" opens the Activity log overlay
- Tapping "+ Ingest" opens the Ingest modal
- TopBar "Sign out" button is visible

- [ ] **Step 4: Verify Files view (navigate to `/files`)**

Check all of the following:
- File list shows full-width (no FileViewer alongside)
- Tapping a file shows the FileViewer full-screen with "← Back" button in the header
- Tapping "← Back" returns to the file list
- The Original/Markdown toggle still works within the viewer

- [ ] **Step 5: Verify desktop layout is unchanged**

Set browser width back to 1280px. Confirm the 3-panel resizable layout is exactly as before — no regressions.

- [ ] **Step 6: Final commit if any fixups were made during verification**

```bash
git add -p
git commit -m "fix(mobile): fixups from visual verification"
```
