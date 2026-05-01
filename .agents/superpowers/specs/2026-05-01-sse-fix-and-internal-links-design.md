# Design: SSE Pipeline Fix + Internal Link Navigation

**Date:** 2026-05-01  
**Status:** Approved

## Problems

1. **SSE stuck at "Processing…"** — Queue items never transition to `done` because `agent:done` is broadcast without `source_id`. The Layout SSE handler gates on `event.source_id`, so the patch is never applied.

2. **SSE events show in topbar during chat** — Query agent `agent:reading`/`agent:writing` events are indistinguishable from ingest events. All events go to the topbar spinner. User wants chat-context events shown as an animated inline status bubble in the chat panel instead.

3. **Internal links open current page in new tab** — `<a href={href}>` with a `wiki://slug` href is either sanitised to `undefined` by react-markdown or causes browser navigation. Clicking hits the `<a href={undefined} target="_blank">` fallback, opening the current URL in a new tab. The working "Sources" links use `<span onClick>` with no href.

---

## Design

### 1. SSE event routing

#### Backend

**`api/app/agents/ingest_agent.py`**  
Add `source_id` to the `agent:done` broadcast (line ~146):
```python
await broadcaster.publish({
    "event": "agent:done",
    "source_id": source_id,
    "pages_touched": pages_touched,
})
```

**`api/app/agents/tools.py` — `AgentTools`**  
Add `context: str = "ingest"` parameter to `__init__`, stored as `self.context`. Merge it into every `_broadcast` payload:
```python
async def _broadcast(self, event: dict):
    if self.broadcaster:
        await self.broadcaster.publish({"context": self.context, **event})
```

**`api/app/agents/query_agent.py`**  
Pass `context="chat"` when instantiating `AgentTools`:
```python
tools = AgentTools(
    session=session,
    workspace_id=workspace_id,
    broadcaster=broadcaster,
    context="chat",
)
```

All ingest agent events continue to carry `context="ingest"` (the default). Query agent events carry `context="chat"`. Legacy events with no context field are treated as `"ingest"`.

#### Frontend — `Layout.tsx`

Add `chatSseEvent` state: `{ event: string; slug?: string } | null`, initially `null`.

In the SSE handler, split on `event.context`:
- `"chat"`: set `chatSseEvent` to the event; do not update topbar or queue
- `"ingest"` or absent: existing queue-patch + topbar logic, unchanged

Pass `chatSseEvent` as a prop to `ChatPanel`. No explicit clearing needed in Layout — the bubble's visibility is gated by `loading === true` in ChatPanel, so it hides automatically when the API call resolves.

---

### 2. ChatPanel animated status bubble

**New prop on `ChatPanel`:** `activeSseEvent: { event: string; slug?: string } | null`

**Behaviour:**
- While `loading === true` and `activeSseEvent !== null`, render a grey status bubble after the last message
- Label map:
  - `agent:reading` → `⟳ Reading {slug}…`
  - `agent:writing` → `⟳ Writing {slug}…`
  - Other events: ignored
- Text swap animation: the inner text element carries `key={activeSseEvent.slug ?? activeSseEvent.event}`. React remounts it on each change, triggering a CSS `@keyframes fadeSlide` (fade-in + slight upward translate) of ~200ms
- When `loading` becomes `false`, the bubble disappears
- The resolved assistant message carries a small grey footnote: `searched {cited_pages.length} pages` (using the already-returned `cited_pages` array). Only shown when `cited_pages.length > 0`

**CSS animation (inline style or style tag):**
```css
@keyframes fadeSlide {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}
```
Applied to the inner text `<span>` with `animation: fadeSlide 200ms ease`.

---

### 3. Internal link rendering fix

**Files:** `frontend/src/components/WikiContent.tsx`, `frontend/src/components/ChatPanel.tsx`

Replace the broken internal-link anchor with a `<span>` matching the working Sources pattern:

```tsx
// Before (broken)
<a
  href={href}
  onClick={(e) => { e.preventDefault(); onNavigate(slug) }}
  style={{ color: '#58a6ff', cursor: 'pointer', textDecoration: 'underline' }}
>
  {children}
</a>

// After (fixed)
<span
  role="link"
  tabIndex={0}
  onClick={() => onNavigate(slug)}
  onKeyDown={(e) => e.key === 'Enter' && onNavigate(slug)}
  style={{ color: '#58a6ff', cursor: 'pointer', textDecoration: 'underline' }}
>
  {children}
</span>
```

The `hrefToSlug` detection logic is unchanged. External links keep their `<a href={href} target="_blank" rel="noreferrer">` fallback.

---

## Files changed

| File | Change |
|------|--------|
| `api/app/agents/ingest_agent.py` | Add `source_id` to `agent:done` broadcast |
| `api/app/agents/tools.py` | Add `context` param to `AgentTools`; merge into `_broadcast` |
| `api/app/agents/query_agent.py` | Pass `context="chat"` to `AgentTools` |
| `frontend/src/components/Layout.tsx` | Split SSE handler by context; add `chatSseEvent` state + prop |
| `frontend/src/components/ChatPanel.tsx` | Accept `activeSseEvent` prop; animated status bubble; "searched N pages" footnote |
| `frontend/src/components/WikiContent.tsx` | Internal links: `<a>` → `<span role="link">` |

---

## Out of scope

- No changes to the SSE broadcaster or EventSource connection
- No router added
- No changes to ingest pipeline UX beyond the stuck-status fix
- The topbar spinner remains for ingest events
