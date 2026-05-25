# Browser Chat Page Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the Playwright-controlled browser page is closed unexpectedly, the agent detects it and tells the user, and the user can click a "Recover Browser" button to get a fresh page attached to the same chat session.

**Architecture:** Three-layer fix — (1) `browser-agent` gains a `/recover` endpoint that replaces a dead browser/page under the same session ID; (2) the API route proxies a `POST /recover` call through and the agent's `_dispatch` raises a `BrowserClosedError` on 500s caused by a dead page, which cleanly exits the turn loop and returns a user-facing message; (3) the frontend adds a "Recover Browser" button that calls the new endpoint.

**Tech Stack:** Python / FastAPI / Playwright (browser-agent), Python / FastAPI / httpx / litellm (api), React 18 / TypeScript (frontend)

---

## File Map

| File | Change |
|------|--------|
| `browser-agent/main.py` | Add `POST /session/{session_id}/recover` endpoint |
| `api/app/routes/browser_chat.py` | Add `POST /sessions/{session_id}/recover` endpoint |
| `api/app/agents/browser_chat_agent.py` | Add `BrowserClosedError`, `_safe_browser_post` helper, update `_dispatch` and `run_turn` |
| `api/tests/test_browser_chat_routes.py` | Tests for the new recover route |
| `frontend/src/api/client.ts` | Add `recoverBrowserChat` function |
| `frontend/src/components/BrowserChatPage.tsx` | Add `recovering` state, `handleRecover`, and Recover button |

---

### Task 1: browser-agent recover endpoint

**Files:**
- Modify: `browser-agent/main.py`

- [ ] **Step 1: Write a manual smoke-test note (no test framework in browser-agent)**

The browser-agent has no pytest suite. Verify this endpoint by running the browser-agent locally and hitting it with curl after Task 5 is complete. Skip ahead to Task 2 now.

- [ ] **Step 2: Add the `/recover` endpoint to `browser-agent/main.py`**

Add this block directly after the `session_new` route (after line 97):

```python
@app.post("/session/{session_id}/recover")
async def session_recover(session_id: str):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    s = _sessions[session_id]

    # Best-effort teardown of dead objects.
    for obj in (s.get("browser"), s.get("context")):
        if obj is not None:
            try:
                await obj.close()
            except Exception:
                pass

    video_dir = s.get("video_dir") or tempfile.mkdtemp()
    launch_kwargs = {"headless": False}
    if _CHROMIUM_PATH:
        launch_kwargs["executable_path"] = _CHROMIUM_PATH
    browser = await _playwright.chromium.launch(**launch_kwargs)
    context = await browser.new_context(
        record_video_dir=video_dir,
        viewport={"width": 1280, "height": 800},
    )
    page = await context.new_page()

    _sessions[session_id] = {
        "browser": browser,
        "context": context,
        "page": page,
        "video_dir": video_dir,
    }
    return {"ok": True}
```

- [ ] **Step 3: Commit**

```bash
git add browser-agent/main.py
git commit -m "feat(browser-agent): add /session/{id}/recover endpoint"
```

---

### Task 2: API recover route

**Files:**
- Modify: `api/app/routes/browser_chat.py`
- Test: `api/tests/test_browser_chat_routes.py`

- [ ] **Step 1: Write the failing tests**

Add to `api/tests/test_browser_chat_routes.py` at the bottom:

```python
# ---------------------------------------------------------------------------
# POST /browser-chat/sessions/{id}/recover
# ---------------------------------------------------------------------------


def test_recover_calls_browser_agent(client):
    mock_ws = _make_ws()
    sess = _make_session()

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = sess

    with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws), \
         patch("app.routes.browser_chat.AsyncSession.execute", new_callable=AsyncMock, return_value=result_mock), \
         patch("app.database.get_db") as mock_db, \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:

        mock_db.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        db_mock = MagicMock()
        db_mock.execute = AsyncMock(return_value=result_mock)
        db_mock.commit = AsyncMock()

        app.dependency_overrides[get_db] = lambda: db_mock.__aiter__()

        async def override_db():
            yield db_mock

        app.dependency_overrides[get_db] = override_db

        r = client.post("/browser-chat/sessions/sess-1/recover")
        assert r.status_code == 200
        assert r.json() == {"ok": True}


def test_recover_404_for_unknown_session(client):
    mock_ws = _make_ws()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None

    async def override_db():
        db_mock = MagicMock()
        db_mock.execute = AsyncMock(return_value=result_mock)
        db_mock.commit = AsyncMock()
        yield db_mock

    app.dependency_overrides[get_db] = override_db

    with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws):
        r = client.post("/browser-chat/sessions/no-such/recover")
        assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd api && python -m pytest tests/test_browser_chat_routes.py::test_recover_calls_browser_agent tests/test_browser_chat_routes.py::test_recover_404_for_unknown_session -v
```

Expected: FAIL — `404 Not Found` (route doesn't exist yet)

- [ ] **Step 3: Add the recover route to `api/app/routes/browser_chat.py`**

Add after the `disconnect` route (after line 225), before the `list_sessions` route:

```python
# ---------------------------------------------------------------------------
# POST /browser-chat/sessions/{id}/recover
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/recover", status_code=200)
async def recover(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(BrowserChatSession).where(
            BrowserChatSession.id == session_id,
            BrowserChatSession.workspace_id == ws.id,
        )
    )
    sess = result.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    async with httpx.AsyncClient(base_url=settings.browser_agent_url, timeout=30.0) as http:
        try:
            resp = await http.post(f"/session/{sess.browser_session_id}/recover")
            resp.raise_for_status()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to recover browser session: {exc}")

    sess.last_activity_at = datetime.utcnow()
    await db.commit()
    _log.info("browser_chat_recovered", session_id=session_id)
    return {"ok": True}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd api && python -m pytest tests/test_browser_chat_routes.py::test_recover_calls_browser_agent tests/test_browser_chat_routes.py::test_recover_404_for_unknown_session -v
```

Expected: PASS

- [ ] **Step 5: Run the full test suite to check for regressions**

```bash
cd api && make test-local
```

Expected: all green

- [ ] **Step 6: Commit**

```bash
git add api/app/routes/browser_chat.py api/tests/test_browser_chat_routes.py
git commit -m "feat(api): add POST /browser-chat/sessions/{id}/recover route"
```

---

### Task 3: Agent-side browser-closed detection

**Files:**
- Modify: `api/app/agents/browser_chat_agent.py`
- Test: `api/tests/test_browser_chat_agent.py`

The goal: when any browser tool call returns a 500 that mentions a closed page/target, raise `BrowserClosedError` which exits the turn loop cleanly and returns a friendly message to the user instead of a cryptic error.

- [ ] **Step 1: Write the failing test**

Open `api/tests/test_browser_chat_agent.py` and add:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from app.agents.browser_chat_agent import BrowserClosedError, _safe_browser_post


@pytest.mark.asyncio
async def test_safe_browser_post_raises_browser_closed_error_on_target_closed():
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 500
    mock_response.text = "playwright._impl._errors.TargetClosedError: Page.goto: Target page, context or browser has been closed"

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    with pytest.raises(BrowserClosedError):
        await _safe_browser_post(mock_client, "/session/abc/navigate", json={"url": "https://example.com"})


@pytest.mark.asyncio
async def test_safe_browser_post_raises_http_error_on_other_500():
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error - something unrelated"
    mock_response.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=mock_response))

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    with pytest.raises(httpx.HTTPStatusError):
        await _safe_browser_post(mock_client, "/session/abc/navigate", json={"url": "https://example.com"})


@pytest.mark.asyncio
async def test_safe_browser_post_returns_response_on_success():
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)

    result = await _safe_browser_post(mock_client, "/session/abc/screenshot")
    assert result is mock_response
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd api && python -m pytest tests/test_browser_chat_agent.py::test_safe_browser_post_raises_browser_closed_error_on_target_closed tests/test_browser_chat_agent.py::test_safe_browser_post_raises_http_error_on_other_500 tests/test_browser_chat_agent.py::test_safe_browser_post_returns_response_on_success -v
```

Expected: FAIL — `ImportError: cannot import name 'BrowserClosedError'`

- [ ] **Step 3: Add `BrowserClosedError` and `_safe_browser_post` to `api/app/agents/browser_chat_agent.py`**

After the imports (after line 18, before `_PROMPTS = ...`), add:

```python
class BrowserClosedError(Exception):
    """Raised when the Playwright browser/page has been closed unexpectedly."""


_BROWSER_CLOSED_MARKERS = ("TargetClosedError", "Target page", "browser has been closed")


async def _safe_browser_post(http: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    resp = await http.post(url, **kwargs)
    if resp.status_code == 500 and any(m in resp.text for m in _BROWSER_CLOSED_MARKERS):
        raise BrowserClosedError("Browser window was closed")
    resp.raise_for_status()
    return resp
```

- [ ] **Step 4: Replace all `await http.post(...)` calls in `_dispatch` with `_safe_browser_post`**

In `_dispatch`, every line of the form:
```python
resp = await http.post(f"/session/{browser_session_id}/...", ...)
resp.raise_for_status()
```
becomes:
```python
resp = await _safe_browser_post(http, f"/session/{browser_session_id}/...", ...)
```
(drop the separate `raise_for_status()` call — `_safe_browser_post` calls it internally)

There are 13 such call sites (navigate, get_page_state, click, type, press_key, focus, hover, select_option, scroll, wait_for, extract, execute_js, screenshot). Replace all of them.

The `wait_for` endpoint already handles its own timeout — keep the existing `resp.raise_for_status()` removal and just swap `http.post` for `_safe_browser_post`:

```python
if name == "browser_wait_for":
    ...
    resp = await _safe_browser_post(http, f"/session/{browser_session_id}/wait_for", json=payload)
    # No raise_for_status needed — _safe_browser_post handles it.
    data = resp.json()
    ...
```

- [ ] **Step 5: Update `run_turn` to catch `BrowserClosedError` and exit the loop cleanly**

In `run_turn`, the inner tool-dispatch try/except (currently lines 102–112) becomes:

```python
tool_results = []
for tc in tool_calls:
    name = tc.function.name
    args = json.loads(tc.function.arguments or "{}")
    try:
        result_str = await _dispatch(
            name, args, browser_session_id, http,
            wiki_tools, chat_session_id, audience_user_id,
        )
    except BrowserClosedError:
        raise  # propagate to outer loop handler
    except Exception as tool_exc:
        result_str = f"Error: {tool_exc}"
    tool_results.append({
        "role": "tool",
        "tool_call_id": tc.id,
        "content": result_str,
    })
messages.extend(tool_results)
```

Then wrap the entire `for turn in range(MAX_TURNS):` loop with a try/except:

```python
try:
    async with httpx.AsyncClient(base_url=settings.browser_agent_url, timeout=60.0) as http:
        for turn in range(MAX_TURNS):
            # ... existing loop body unchanged ...
except BrowserClosedError:
    reply_text = (
        "The browser window was closed unexpectedly. "
        "Click **Recover Browser** in the toolbar to get a fresh browser tab, "
        "then tell me where to continue."
    )
    _log.warning("browser_chat_browser_closed", session_id=chat_session_id)

return reply_text
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd api && python -m pytest tests/test_browser_chat_agent.py -v
```

Expected: PASS

- [ ] **Step 7: Run the full test suite**

```bash
cd api && make test-local
```

Expected: all green

- [ ] **Step 8: Commit**

```bash
git add api/app/agents/browser_chat_agent.py api/tests/test_browser_chat_agent.py
git commit -m "feat(agent): detect browser closed errors and return recovery prompt"
```

---

### Task 4: Frontend API client

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add `recoverBrowserChat` to `frontend/src/api/client.ts`**

After the `disconnectBrowserChat` function (after line 354), add:

```typescript
export async function recoverBrowserChat(sessionId: string): Promise<void> {
  const r = await fetchWithAuth(`${BASE}/browser-chat/sessions/${sessionId}/recover`, { method: 'POST' })
  if (!r.ok) throw new Error(`recoverBrowserChat failed: ${r.status}`)
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat(client): add recoverBrowserChat API function"
```

---

### Task 5: Frontend Recover button

**Files:**
- Modify: `frontend/src/components/BrowserChatPage.tsx`

- [ ] **Step 1: Add `recovering` state and import `recoverBrowserChat`**

At the top of `BrowserChatPage.tsx`, update the import from `../api/client` to include `recoverBrowserChat`:

```typescript
import {
  type BrowserChatMessage,
  type BrowserChatSession,
  connectBrowserChat,
  disconnectBrowserChat,
  getBrowserChatSession,
  getNovncUrl,
  interruptBrowserChat,
  listBrowserChatSessions,
  recoverBrowserChat,
  sendBrowserChatMessage,
} from '../api/client'
```

In the component, after the `connectError` state (after line 28), add:

```typescript
const [recovering, setRecovering] = useState(false)
```

- [ ] **Step 2: Add `handleRecover` function**

After `handleDisconnect` (after line 107), add:

```typescript
async function handleRecover() {
  if (!activeSessionId || recovering) return
  setRecovering(true)
  try {
    await recoverBrowserChat(activeSessionId)
    setMessages(prev => [...prev, {
      id: String(Date.now()),
      role: 'assistant',
      content: 'Browser recovered — you have a fresh tab. Tell me where to continue.',
      created_at: new Date().toISOString(),
    }])
  } catch {
    setMessages(prev => [...prev, {
      id: String(Date.now()),
      role: 'assistant',
      content: 'Failed to recover the browser. Try disconnecting and reconnecting.',
      created_at: new Date().toISOString(),
    }])
  } finally {
    setRecovering(false)
  }
}
```

- [ ] **Step 3: Add the Recover button to the chat toolbar**

In the button row (the `div` containing the Disconnect and Send buttons, around line 215), add a Recover button between them:

```tsx
<div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
  <button
    type="button"
    onClick={handleDisconnect}
    style={{ padding: '5px 10px', background: 'transparent', border: '1px solid #f8514940', borderRadius: 6, color: '#f85149', fontSize: 11, cursor: 'pointer' }}
  >
    Disconnect
  </button>
  <button
    type="button"
    onClick={handleRecover}
    disabled={recovering || agentRunning}
    style={{
      padding: '5px 10px',
      background: 'transparent',
      border: `1px solid ${recovering || agentRunning ? '#30363d' : '#d2992240'}`,
      borderRadius: 6,
      color: recovering || agentRunning ? '#8b949e' : '#d29922',
      fontSize: 11,
      cursor: recovering || agentRunning ? 'default' : 'pointer',
    }}
  >
    {recovering ? 'Recovering…' : 'Recover Browser'}
  </button>
  <button
    type="button"
    onClick={handleSend}
    disabled={!input.trim() || agentRunning}
    style={{
      padding: '6px 14px',
      background: input.trim() && !agentRunning ? '#238636' : '#21262d',
      border: `1px solid ${input.trim() && !agentRunning ? '#2ea043' : '#30363d'}`,
      borderRadius: 6,
      color: input.trim() && !agentRunning ? '#ffffff' : '#8b949e',
      fontSize: 12,
      fontWeight: 600,
      cursor: input.trim() && !agentRunning ? 'pointer' : 'default',
    }}
  >
    Send
  </button>
</div>
```

- [ ] **Step 4: Verify in dev server**

Start the frontend dev server and navigate to `/browser-chat`. Connect a session. Confirm:
- "Recover Browser" button is visible in the chat toolbar
- Button is disabled while agent is running
- Button shows "Recovering…" while the API call is in flight
- On success, a system message appears in chat

```bash
cd frontend && npm run dev
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BrowserChatPage.tsx
git commit -m "feat(ui): add Recover Browser button to browser chat"
```

---

## Self-Review

**Spec coverage:**
- ✅ browser-agent `/recover` endpoint replaces dead browser/page — Task 1
- ✅ API `/recover` route proxies to browser-agent — Task 2
- ✅ Agent detects `TargetClosedError` in 500 responses, exits turn loop, tells user to recover — Task 3
- ✅ Frontend API function — Task 4
- ✅ Recover button, visible always, disabled while agent running — Task 5

**Placeholder scan:** No TBDs. All code blocks are complete.

**Type consistency:**
- `BrowserClosedError` defined in Task 3 Step 3, imported in same file — no cross-file import needed
- `_safe_browser_post(http, url, **kwargs)` signature used consistently throughout `_dispatch`
- `recoverBrowserChat(sessionId: string)` defined in Task 4, imported in Task 5 Step 1
