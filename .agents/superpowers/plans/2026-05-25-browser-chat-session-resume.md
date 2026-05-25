# Browser Chat Session Resume — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to re-enter past browser chat sessions — reconnecting to live sessions or resuming completed ones with full prior context copied to the new agent session.

**Architecture:** Backend gains an optional `prior_session_id` on the connect endpoint that seeds the new session's DB message history from a prior session. The frontend reads `?session=<id>` from the URL on mount, determines if the session is active or completed, and either reconnects directly or calls connect with the prior session ID. Session rows on the landing page become navigable links.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React 18 + React Router (frontend), existing `BrowserChatPage.tsx` and `client.ts`.

---

## Files Changed

| File | Change |
|---|---|
| `api/app/routes/browser_chat.py` | Add `ConnectRequest` body model; copy prior messages after new session created |
| `api/tests/test_browser_chat_routes.py` | Add test for `prior_session_id` message copying |
| `frontend/src/api/client.ts` | `connectBrowserChat` gains optional `priorSessionId` param |
| `frontend/src/components/BrowserChatPage.tsx` | URL param handling, resume logic, `historicMessages` state, divider, clickable rows |

---

## Task 1: Backend — accept `prior_session_id` and copy messages

**Files:**
- Modify: `api/app/routes/browser_chat.py:20-65`
- Test: `api/tests/test_browser_chat_routes.py`

- [ ] **Step 1: Write the failing test**

Add to `api/tests/test_browser_chat_routes.py` (after `test_connect_409_when_active_session_exists`):

```python
def test_connect_with_prior_session_id_copies_messages(client):
    mock_ws = _make_ws()
    no_existing = MagicMock()
    no_existing.scalar_one_or_none.return_value = None

    # Prior messages returned by the second execute call
    prior_msg_1 = MagicMock()
    prior_msg_1.role = "user"
    prior_msg_1.content = "go to google"

    prior_msg_2 = MagicMock()
    prior_msg_2.role = "assistant"
    prior_msg_2.content = "Navigated to google.com"

    prior_msgs_result = MagicMock()
    prior_msgs_result.scalars.return_value.all.return_value = [prior_msg_1, prior_msg_2]

    # execute returns no-existing on first call (active check), prior msgs on second call
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[no_existing, prior_msgs_result])
    session.commit = AsyncMock()
    session.add = MagicMock()
    session.refresh = AsyncMock()

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws), \
             patch("httpx.AsyncClient") as mock_http_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"session_id": "bsess-abc"}
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_http_cls.return_value = mock_http

            def fake_add(obj):
                if hasattr(obj, "browser_session_id"):
                    obj.id = "sess-new"

            session.add.side_effect = fake_add

            r = client.post("/browser-chat/sessions", json={"prior_session_id": "sess-old"})
            assert r.status_code == 201
            # Two BrowserChatMessage objects added (one per prior message) plus the session
            added_types = [type(call.args[0]).__name__ for call in session.add.call_args_list]
            # session add is called for the new session + 2 message copies
            assert session.add.call_count == 3
    finally:
        app.dependency_overrides.pop(get_db, None)
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd /Users/darraghflynn/Documents/Second-Brain && make test-local 2>&1 | grep -A 5 "test_connect_with_prior"
```

Expected: FAIL (endpoint accepts no body / no message copying yet).

- [ ] **Step 3: Add `ConnectRequest` model and update the `connect` endpoint**

In `api/app/routes/browser_chat.py`, replace the section from line 20 to line 65:

```python
class MessageRequest(BaseModel):
    content: str
    max_turns: int = 20


class ConnectRequest(BaseModel):
    prior_session_id: str | None = None


# ---------------------------------------------------------------------------
# POST /browser-chat/sessions — Connect
# ---------------------------------------------------------------------------

@router.post("/sessions", status_code=201)
async def connect(
    body: ConnectRequest = ConnectRequest(),
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)

    # One active session at a time (single Xvfb display).
    existing = await db.execute(
        select(BrowserChatSession).where(
            BrowserChatSession.workspace_id == ws.id,
            BrowserChatSession.status == "active",
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A browser chat session is already active.")

    async with httpx.AsyncClient(base_url=settings.browser_agent_url, timeout=30.0) as http:
        try:
            resp = await http.post("/session/new")
            resp.raise_for_status()
            browser_session_id = resp.json()["session_id"]
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to start browser session: {exc}")

    sess = BrowserChatSession(
        workspace_id=ws.id,
        browser_session_id=browser_session_id,
        status="active",
        last_activity_at=datetime.utcnow(),
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)

    if body.prior_session_id:
        prior_msgs = await db.execute(
            select(BrowserChatMessage)
            .where(BrowserChatMessage.session_id == body.prior_session_id)
            .order_by(BrowserChatMessage.created_at.asc())
        )
        for m in prior_msgs.scalars().all():
            db.add(BrowserChatMessage(session_id=sess.id, role=m.role, content=m.content))
        await db.commit()

    _log.info("browser_chat_connected", session_id=sess.id, browser_session_id=browser_session_id)
    return {"session_id": sess.id}
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /Users/darraghflynn/Documents/Second-Brain && make test-local 2>&1 | grep -E "PASSED|FAILED|ERROR" | grep -i "browser_chat_routes"
```

Expected: all `test_browser_chat_routes` tests PASSED.

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/darraghflynn/Documents/Second-Brain && make test-local 2>&1 | tail -5
```

Expected: no failures.

- [ ] **Step 6: Commit**

```bash
git add api/app/routes/browser_chat.py api/tests/test_browser_chat_routes.py
git commit -m "feat(browser-chat): accept prior_session_id on connect and copy messages"
```

---

## Task 2: Frontend client — `connectBrowserChat` with optional `priorSessionId`

**Files:**
- Modify: `frontend/src/api/client.ts:331-335`

- [ ] **Step 1: Update `connectBrowserChat`**

In `frontend/src/api/client.ts`, replace:

```typescript
export async function connectBrowserChat(): Promise<{ session_id: string }> {
  const r = await fetchWithAuth(`${BASE}/browser-chat/sessions`, { method: 'POST' })
  if (!r.ok) throw new Error(`connectBrowserChat failed: ${r.status}`)
  return r.json()
}
```

With:

```typescript
export async function connectBrowserChat(priorSessionId?: string): Promise<{ session_id: string }> {
  const r = await fetchWithAuth(`${BASE}/browser-chat/sessions`, {
    method: 'POST',
    headers: priorSessionId ? jsonHeaders() : undefined,
    body: priorSessionId ? JSON.stringify({ prior_session_id: priorSessionId }) : undefined,
  })
  if (!r.ok) throw new Error(`connectBrowserChat failed: ${r.status}`)
  return r.json()
}
```

(Note: `jsonHeaders()` is defined at line 64 of `client.ts` — it returns `{ 'Content-Type': 'application/json' }`; it's already used by other functions in the same file.)

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /Users/darraghflynn/Documents/Second-Brain/frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat(browser-chat): connectBrowserChat accepts optional priorSessionId"
```

---

## Task 3: Frontend — URL param handling, resume logic, historic messages, and divider

**Files:**
- Modify: `frontend/src/components/BrowserChatPage.tsx`

This task adds:
1. New state: `historicMessages` (prior session messages shown before divider) and `priorSessionCreatedAt` (for divider label)
2. `useSearchParams` to read `?session`
3. A `useEffect` that fires when the URL session param changes (only when disconnected)
4. The visual divider rendered between historic and current messages

- [ ] **Step 1: Add `useSearchParams` import and new state**

At the top of `BrowserChatPage.tsx`, add `useSearchParams` to the React Router import. Currently there are no React Router imports in this file — add a new import line after the existing imports:

```typescript
import { useSearchParams } from 'react-router-dom'
```

Inside `BrowserChatPage()`, add these three new state declarations after the existing `useState` declarations (after line `const [actions, setActions] = useState<ActionItem[]>([])`):

```typescript
const [historicMessages, setHistoricMessages] = useState<BrowserChatMessage[]>([])
const [priorSessionCreatedAt, setPriorSessionCreatedAt] = useState<string | null>(null)
const [sessionParam] = useSearchParams()
```

- [ ] **Step 2: Add resume effect**

Add this `useEffect` after the existing `useEffect` that calls `getNovncUrl` and `listBrowserChatSessions` (after the block ending around line 65):

```typescript
useEffect(() => {
  const paramId = sessionParam.get('session')
  if (!paramId || connectionState !== 'disconnected') return

  getBrowserChatSession(paramId).then(async detail => {
    if (detail.status === 'active') {
      setActiveSessionId(detail.id)
      setMessages(detail.messages)
      setHistoricMessages([])
      setPriorSessionCreatedAt(null)
      setCurrentUrl('')
      setConnectionState('connected')
    } else {
      // Completed session: connect fresh browser, seed with prior context
      setConnectionState('connecting')
      try {
        const { session_id } = await connectBrowserChat(detail.id)
        setActiveSessionId(session_id)
        setHistoricMessages(detail.messages)
        setPriorSessionCreatedAt(detail.created_at)
        setMessages([])
        setCurrentUrl('')
        setConnectionState('connected')
      } catch {
        setConnectError('Failed to resume session.')
        setConnectionState('disconnected')
      }
    }
  }).catch(() => {
    // Unknown session param — silently ignore, stay on disconnected page
  })
}, [sessionParam, connectionState])
```

- [ ] **Step 3: Reset historic state on manual connect and disconnect**

In `handleConnect` (around line 115), add resets after `setConnectionState('connecting')`:

```typescript
setHistoricMessages([])
setPriorSessionCreatedAt(null)
```

In `handleDisconnect` (around line 131), add resets after `setMessages([])`:

```typescript
setHistoricMessages([])
setPriorSessionCreatedAt(null)
```

- [ ] **Step 4: Add the divider and historic messages to the chat render**

In the connected `pageContent` JSX, locate the messages list section that starts with:

```typescript
{messages.length === 0 && (
  <p className="mt-10 px-3 text-center text-sm italic text-muted-foreground">
    Type a message to get started.
  </p>
)}
{messages.map(msg =>
```

Replace it with:

```typescript
{historicMessages.length === 0 && messages.length === 0 && (
  <p className="mt-10 px-3 text-center text-sm italic text-muted-foreground">
    Type a message to get started.
  </p>
)}
{historicMessages.map(msg =>
  msg.role === 'user' ? (
    <div key={msg.id} className="flex justify-end px-3 py-1">
      <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-sm bg-muted px-3 py-2 text-sm text-foreground">
        {msg.content}
      </div>
    </div>
  ) : (
    <Card
      key={msg.id}
      className="mx-3 my-2 border-border bg-card p-3 text-sm leading-relaxed text-card-foreground"
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="my-1">{children}</p>,
          ul: ({ children }) => <ul className="my-1 list-disc pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="my-1 list-decimal pl-5">{children}</ol>,
          a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer" className="text-primary underline">{children}</a>,
          code: ({ children }) => <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">{children}</code>,
          pre: ({ children }) => <pre className="my-2 overflow-x-auto rounded bg-muted p-2 font-mono text-xs">{children}</pre>,
        }}
      >
        {msg.content}
      </ReactMarkdown>
    </Card>
  ),
)}
{priorSessionCreatedAt && (
  <div className="my-3 flex items-center gap-2 px-3">
    <div className="h-px flex-1 bg-border" />
    <span className="shrink-0 text-xs text-muted-foreground">
      Resumed from {new Date(priorSessionCreatedAt).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}
    </span>
    <div className="h-px flex-1 bg-border" />
  </div>
)}
{messages.map(msg =>
```

- [ ] **Step 5: Verify TypeScript compiles**

```bash
cd /Users/darraghflynn/Documents/Second-Brain/frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/BrowserChatPage.tsx
git commit -m "feat(browser-chat): resume session from URL param with historic message context"
```

---

## Task 4: Frontend — make session rows clickable on the landing page

**Files:**
- Modify: `frontend/src/components/BrowserChatPage.tsx` (session row section, ~lines 411–475)

Currently the date/name area of each session card is inert. This task wraps it in a `Link` so clicking navigates to `?session=<id>`.

- [ ] **Step 1: Add `Link` import**

Add `Link` to the React Router import added in Task 3:

```typescript
import { Link, useSearchParams } from 'react-router-dom'
```

- [ ] **Step 2: Wrap the session row info in a Link**

Locate the inner `div` containing the date and status text inside each session card's `flex items-center gap-2.5 p-3` row. It currently looks like:

```typescript
<div className="min-w-0 flex-1">
  <p className="text-sm text-foreground">
    {new Date(s.created_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}
  </p>
  <p className="text-xs text-muted-foreground">
    {s.status === 'active' ? 'Active' : 'Completed'}
    {s.completed_at && ` · ${Math.round((new Date(s.completed_at).getTime() - new Date(s.created_at).getTime()) / 60000)}m`}
  </p>
</div>
```

Replace it with:

```typescript
<Link
  to={`/browser-chat?session=${encodeURIComponent(s.id)}`}
  className="min-w-0 flex-1 hover:opacity-80"
>
  <p className="text-sm text-foreground">
    {new Date(s.created_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}
  </p>
  <p className="text-xs text-muted-foreground">
    {s.status === 'active' ? 'Active' : 'Completed'}
    {s.completed_at && ` · ${Math.round((new Date(s.completed_at).getTime() - new Date(s.created_at).getTime()) / 60000)}m`}
  </p>
</Link>
```

The `Disconnect` and `Messages ▾` buttons keep their existing `onClick` handlers unchanged — they sit alongside the `Link` in the flex row so clicks don't propagate to it.

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /Users/darraghflynn/Documents/Second-Brain/frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 4: Manual smoke test**

Start the dev server (`docker compose up` or `npm run dev` from `frontend/`) and:
1. Open `/browser-chat` — landing page shows past sessions
2. Click the date area of a completed session — URL changes to `?session=<id>`, connecting state appears, then connected view with historic messages and divider
3. Click the date area of an active session — connected view loads with prior messages, no divider
4. Sidebar links to sessions also navigate correctly

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BrowserChatPage.tsx
git commit -m "feat(browser-chat): make session rows navigable links to resume sessions"
```
