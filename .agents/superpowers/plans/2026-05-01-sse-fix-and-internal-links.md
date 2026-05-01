# SSE Pipeline Fix + Internal Link Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix queue items stuck at "Processing…", route chat SSE events into an animated bubble in ChatPanel, and fix internal wiki/chat links that open a new browser tab instead of navigating within the app.

**Architecture:** Three backend files get context/source_id additions; four frontend files split the SSE handler by context and swap internal link anchors for spans. No new dependencies or files needed.

**Tech Stack:** Python/FastAPI (backend), React 18 + TypeScript + react-markdown + @tanstack/react-query (frontend), pytest + asyncio (tests).

---

## File Map

| File | What changes |
|------|-------------|
| `api/app/agents/ingest_agent.py:146` | Add `source_id` to `agent:done` broadcast |
| `api/app/agents/tools.py:86-100` | Add `context` param to `AgentTools.__init__`; merge into `_broadcast` |
| `api/app/agents/query_agent.py:26` | Pass `context="chat"` to `AgentTools` |
| `frontend/src/components/Layout.tsx:57-123` | Split SSE handler by `event.context`; add `chatSseEvent` state; pass to ChatPanel |
| `frontend/src/components/ChatPanel.tsx` | Accept `activeSseEvent` prop; animated status bubble; "searched N pages" footnote |
| `frontend/src/components/WikiContent.tsx:86-102` | Internal links: `<a href>` → `<span role="link">` |

---

## Task 1: Backend — AgentTools context field + agent:done source_id

**Files:**
- Modify: `api/app/agents/tools.py:86-100`
- Modify: `api/app/agents/query_agent.py:26`
- Modify: `api/app/agents/ingest_agent.py:146`
- Test: `tests/test_agents.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agents.py`:

```python
@pytest.mark.asyncio
async def test_broadcast_includes_context_ingest_default():
    """_broadcast merges context="ingest" by default."""
    published = []

    class FakeBroadcaster:
        async def publish(self, event):
            published.append(event)

    tools = AgentTools(session=AsyncMock(), workspace_id="ws-1", broadcaster=FakeBroadcaster())
    await tools._broadcast({"event": "agent:reading", "slug": "people/alice"})

    assert len(published) == 1
    assert published[0]["context"] == "ingest"
    assert published[0]["event"] == "agent:reading"
    assert published[0]["slug"] == "people/alice"


@pytest.mark.asyncio
async def test_broadcast_includes_context_chat():
    """_broadcast merges context="chat" when AgentTools is initialised with context="chat"."""
    published = []

    class FakeBroadcaster:
        async def publish(self, event):
            published.append(event)

    tools = AgentTools(
        session=AsyncMock(),
        workspace_id="ws-1",
        broadcaster=FakeBroadcaster(),
        context="chat",
    )
    await tools._broadcast({"event": "agent:reading", "slug": "people/bob"})

    assert published[0]["context"] == "chat"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/darraghflynn/Documents/Second-Brain
docker compose exec api pytest tests/test_agents.py::test_broadcast_includes_context_ingest_default tests/test_agents.py::test_broadcast_includes_context_chat -v
```

Expected: FAIL — `AgentTools.__init__` does not accept `context` parameter yet.

- [ ] **Step 3: Add `context` to AgentTools and fix `_broadcast`**

In `api/app/agents/tools.py`, replace the `__init__` and `_broadcast` methods (lines 86–100):

```python
def __init__(
    self,
    session: AsyncSession,
    workspace_id: str,
    broadcaster: SSEBroadcaster | None,
    source_id: str | None = None,
    context: str = "ingest",
):
    self.session = session
    self.workspace_id = workspace_id
    self.broadcaster = broadcaster
    self.source_id = source_id
    self.context = context

async def _broadcast(self, event: dict):
    if self.broadcaster:
        await self.broadcaster.publish({"context": self.context, **event})
```

- [ ] **Step 4: Pass `context="chat"` in query_agent.py**

In `api/app/agents/query_agent.py`, line 26, replace:

```python
tools = AgentTools(session=session, workspace_id=workspace_id, broadcaster=broadcaster)
```

with:

```python
tools = AgentTools(session=session, workspace_id=workspace_id, broadcaster=broadcaster, context="chat")
```

- [ ] **Step 5: Add `source_id` to `agent:done` in ingest_agent.py**

In `api/app/agents/ingest_agent.py`, line 146, replace:

```python
await broadcaster.publish({"event": "agent:done", "pages_touched": pages_touched})
```

with:

```python
await broadcaster.publish({"event": "agent:done", "source_id": source_id, "pages_touched": pages_touched})
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
docker compose exec api pytest tests/test_agents.py::test_broadcast_includes_context_ingest_default tests/test_agents.py::test_broadcast_includes_context_chat -v
```

Expected: PASS.

- [ ] **Step 7: Run the full test suite to check for regressions**

```bash
docker compose exec api pytest tests/ -v --timeout=30
```

Expected: all previously passing tests still pass.

- [ ] **Step 8: Commit**

```bash
git add api/app/agents/tools.py api/app/agents/query_agent.py api/app/agents/ingest_agent.py tests/test_agents.py
git commit -m "fix: add context field to AgentTools broadcast and source_id to agent:done"
```

---

## Task 2: Frontend — Layout SSE routing by context

**Files:**
- Modify: `frontend/src/components/Layout.tsx:57-123`

This task splits the existing SSE handler so that events with `context: "chat"` are stored in a new `chatSseEvent` state and passed to ChatPanel, while `context: "ingest"` (or absent) events continue to drive the topbar and queue exactly as before.

- [ ] **Step 1: Add `chatSseEvent` state and update the event type**

At the top of `Layout()`, after the existing `useState` declarations, add:

```tsx
const [chatSseEvent, setChatSseEvent] = useState<{ event: string; slug?: string } | null>(null)
```

Update the event type cast inside the SSE handler (the `data as { ... }` object) to include `context`:

```tsx
const event = data as {
  event: string
  slug?: string
  source_id?: string
  pages_touched?: string[]
  context?: string
}
```

- [ ] **Step 2: Split the SSE handler by context**

Replace the entire body of the `createSSE` callback (lines 58–104, everything between `const event = data as ...` and the closing `}`) with:

```tsx
const event = data as {
  event: string
  slug?: string
  source_id?: string
  pages_touched?: string[]
  context?: string
}

// Chat-context events go to the ChatPanel bubble, not the topbar.
if (event.context === 'chat') {
  setChatSseEvent({ event: event.event, slug: event.slug })
  return
}

// Ingest-context events (or legacy events with no context) drive the queue and topbar.
const STATUS_MAP: Partial<Record<string, QueueItem['status']>> = {
  'agent:queued': 'queued',
  'agent:converting': 'converting',
  'agent:ingesting': 'processing',
  'agent:done': 'done',
}
const queueStatus = STATUS_MAP[event.event]
if (queueStatus && event.source_id) {
  queueActions.patchBySource(event.source_id, { status: queueStatus })
}
if (event.event === 'agent:queued') {
  setAgentStatus(
    event.source_id
      ? `Queued (source ${event.source_id.slice(0, 8)}…)`
      : 'Queued…',
  )
} else if (event.event === 'agent:converting') {
  setAgentStatus(
    event.source_id
      ? `Converting document (source ${event.source_id.slice(0, 8)}…)…`
      : 'Converting document…',
  )
} else if (event.event === 'agent:ingesting') {
  setAgentStatus(
    event.source_id
      ? `Updating wiki from source ${event.source_id.slice(0, 8)}…`
      : 'Updating wiki from ingested source…',
  )
} else if (event.event === 'agent:reading') {
  setHighlightedSlug(event.slug || null)
  setAgentStatus(`Reading ${event.slug}…`)
} else if (event.event === 'agent:writing') {
  setHighlightedSlug(event.slug || null)
  setAgentStatus(`Writing ${event.slug}…`)
} else if (event.event === 'agent:done') {
  setHighlightedSlug(null)
  setAgentStatus(null)
  qc.invalidateQueries({ queryKey: ['pages'] })
  qc.invalidateQueries({ queryKey: ['activity'] })
}
```

- [ ] **Step 3: Pass `chatSseEvent` to ChatPanel**

Find the `<ChatPanel onNavigate={setSelectedSlug} />` line in the JSX and update it to:

```tsx
<ChatPanel onNavigate={setSelectedSlug} activeSseEvent={chatSseEvent} />
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd /Users/darraghflynn/Documents/Second-Brain/frontend
npm run build 2>&1 | tail -20
```

Expected: build succeeds or only errors about the `activeSseEvent` prop not existing on ChatPanel yet (that's fine — fixed in Task 3).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Layout.tsx
git commit -m "feat: route chat SSE events to ChatPanel via chatSseEvent prop"
```

---

## Task 3: Frontend — ChatPanel animated status bubble + searched footnote

**Files:**
- Modify: `frontend/src/components/ChatPanel.tsx`

The existing `{loading && <div>Thinking…</div>}` block is replaced with a smarter bubble. When `activeSseEvent` is non-null and loading, the bubble shows the current event label with a fade-slide animation on each change. When loading ends, the bubble disappears. Each assistant message gets a "searched N pages" footnote.

- [ ] **Step 1: Update the ChatPanelProps interface and component signature**

Replace:

```tsx
interface ChatPanelProps {
  onNavigate: (slug: string) => void
}

export default function ChatPanel({ onNavigate }: ChatPanelProps) {
```

with:

```tsx
interface ChatPanelProps {
  onNavigate: (slug: string) => void
  activeSseEvent: { event: string; slug?: string } | null
}

export default function ChatPanel({ onNavigate, activeSseEvent }: ChatPanelProps) {
```

- [ ] **Step 2: Add the keyframe animation style tag**

Insert a `<style>` tag as the very first child of the outer `<div>` returned by ChatPanel (before the header div):

```tsx
<style>{`
  @keyframes fadeSlide {
    from { opacity: 0; transform: translateY(4px); }
    to   { opacity: 1; transform: translateY(0); }
  }
`}</style>
```

- [ ] **Step 3: Replace the "Thinking…" loading indicator with the animated bubble**

Find and replace:

```tsx
{loading && (
  <div style={{ color: '#8b949e', fontSize: 13, alignSelf: 'flex-start' }}>Thinking…</div>
)}
```

with:

```tsx
{loading && (() => {
  const eventLabel = (() => {
    if (!activeSseEvent) return 'Thinking…'
    if (activeSseEvent.event === 'agent:reading') return `⟳ Reading ${activeSseEvent.slug}…`
    if (activeSseEvent.event === 'agent:writing') return `⟳ Writing ${activeSseEvent.slug}…`
    return 'Thinking…'
  })()
  const animKey = activeSseEvent?.slug ?? activeSseEvent?.event ?? 'thinking'
  return (
    <div style={{
      alignSelf: 'flex-start',
      padding: '6px 10px',
      background: '#161b22',
      border: '1px solid #30363d',
      borderRadius: 8,
      fontSize: 12,
      color: '#8b949e',
      maxWidth: '80%',
    }}>
      <span
        key={animKey}
        style={{ animation: 'fadeSlide 200ms ease', display: 'inline-block' }}
      >
        {eventLabel}
      </span>
    </div>
  )
})()}
```

- [ ] **Step 4: Add "searched N pages" footnote to assistant messages**

The `Message` interface already has `cited?: string[]`. After each assistant message bubble, add a footnote. Find the closing `</div>` of the per-message block and update the block to add the footnote below the bubble:

The per-message block currently ends like:

```tsx
            </div>
            {m.cited && m.cited.length > 0 && (
              <div style={{ fontSize: 11, color: '#8b949e', marginTop: 4, paddingLeft: 4 }}>
                Sources: {m.cited.map((slug) => (
```

Add a "searched N pages" line **before** the existing Sources block:

```tsx
            </div>
            {m.role === 'assistant' && m.cited && m.cited.length > 0 && (
              <div style={{ fontSize: 11, color: '#6e7681', marginTop: 2, paddingLeft: 4 }}>
                searched {m.cited.length} {m.cited.length === 1 ? 'page' : 'pages'}
              </div>
            )}
            {m.cited && m.cited.length > 0 && (
              <div style={{ fontSize: 11, color: '#8b949e', marginTop: 4, paddingLeft: 4 }}>
                Sources: {m.cited.map((slug) => (
```

- [ ] **Step 5: Verify TypeScript compiles cleanly**

```bash
cd /Users/darraghflynn/Documents/Second-Brain/frontend
npm run build 2>&1 | tail -20
```

Expected: no TypeScript errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ChatPanel.tsx
git commit -m "feat: animated SSE status bubble and searched-pages footnote in ChatPanel"
```

---

## Task 4: Frontend — Fix internal links (WikiContent + ChatPanel)

**Files:**
- Modify: `frontend/src/components/WikiContent.tsx:86-102`
- Modify: `frontend/src/components/ChatPanel.tsx` (the `a` component inside ReactMarkdown)

Internal links rendered as `<a href={href}>` are broken — the href is either sanitised or causes browser navigation. The working "Sources" links at the bottom of chat messages use `<span onClick>` with no href. This task applies the same pattern everywhere.

- [ ] **Step 1: Fix internal links in WikiContent.tsx**

Find the `a({ href, children })` component inside the `<ReactMarkdown components={...}>` block in `WikiContent.tsx`. Replace the entire component:

```tsx
a({ href, children }) {
  const slug = href ? hrefToSlug(href) : null
  if (href && slug) {
    return (
      <a
        href={href}
        onClick={(e) => {
          e.preventDefault()
          onNavigate(slug)
        }}
        style={{ color: '#58a6ff', cursor: 'pointer', textDecoration: 'underline' }}
      >
        {children}
      </a>
    )
  }
  return <a href={href} target="_blank" rel="noreferrer">{children}</a>
}
```

with:

```tsx
a({ href, children }) {
  const slug = href ? hrefToSlug(href) : null
  if (slug) {
    return (
      <span
        role="link"
        tabIndex={0}
        onClick={() => onNavigate(slug)}
        onKeyDown={(e) => e.key === 'Enter' && onNavigate(slug)}
        style={{ color: '#58a6ff', cursor: 'pointer', textDecoration: 'underline' }}
      >
        {children}
      </span>
    )
  }
  return <a href={href} target="_blank" rel="noreferrer">{children}</a>
}
```

Note: condition simplified from `if (href && slug)` to `if (slug)` — `hrefToSlug` already returns `null` for empty/null hrefs, so the `href &&` guard is redundant.

- [ ] **Step 2: Fix internal links in ChatPanel.tsx**

Find the `a({ href, children })` component inside the `<ReactMarkdown components={...}>` block in `ChatPanel.tsx`. Apply the exact same replacement as Step 1:

```tsx
a({ href, children }) {
  const slug = href ? hrefToSlug(href) : null
  if (slug) {
    return (
      <span
        role="link"
        tabIndex={0}
        onClick={() => onNavigate(slug)}
        onKeyDown={(e) => e.key === 'Enter' && onNavigate(slug)}
        style={{ color: '#58a6ff', cursor: 'pointer', textDecoration: 'underline' }}
      >
        {children}
      </span>
    )
  }
  return <a href={href} target="_blank" rel="noreferrer">{children}</a>
}
```

- [ ] **Step 3: Verify TypeScript compiles cleanly**

```bash
cd /Users/darraghflynn/Documents/Second-Brain/frontend
npm run build 2>&1 | tail -20
```

Expected: no TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/WikiContent.tsx frontend/src/components/ChatPanel.tsx
git commit -m "fix: replace broken internal link anchors with span role=link in WikiContent and ChatPanel"
```

---

## Verification checklist (manual, after all tasks)

Run the dev stack:
```bash
docker compose up
```

1. **SSE stuck fix** — Ingest a file. Watch the Activity panel. The item should progress: Pending → Uploading → Queued → Converting → Processing → Done ✓. It should no longer stick at "Processing…".

2. **Chat SSE bubble** — Ask a question in chat. While the agent is working, a grey bubble should appear below the last message with animated text swapping between `⟳ Reading …` and `⟳ Writing …` as pages are accessed. When the answer arrives, the bubble disappears and the answer message shows `searched N pages`.

3. **Topbar during chat** — The topbar spinner should NOT activate during chat queries (only during ingestion).

4. **Internal links — wiki pages** — Open a wiki page that has `[[wikilink]]` or `[text](slug)` links. Clicking a link should navigate to that page within the app, not open a new tab.

5. **Internal links — chat** — Ask a question that cites wiki pages. Clicking a link in the answer should navigate within the app. External links (http://) should still open in a new tab.

6. **Sources links still work** — The existing "Sources: slug1 slug2" links at the bottom of chat messages should still navigate correctly (they were already using span — verify no regression).
