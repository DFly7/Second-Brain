# Browser Chat Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three browser chat issues: make tool calls visible in the UI, prevent garbled reply output from multimodal LLM responses, and make the browser undetectable to Cloudflare while giving the agent coordinate-level mouse control.

**Architecture:** Three independent fixes applied in parallel order of risk — backend guard first (safest), then frontend action feed, then browser-agent stealth + new tools, then prompt update. Each task is fully self-contained and commits cleanly.

**Tech Stack:** Python 3.11, FastAPI, LiteLLM, Playwright, `playwright-stealth`, React 18 + TypeScript, pytest + pytest-asyncio.

---

## File Map

| File | What changes |
|------|-------------|
| `api/app/agents/browser_chat_agent.py` | Add `_extract_text`, fix `reply_text`, add `browser_click_at` + `browser_mouse_move` dispatch, add error flag to `_action` |
| `api/app/agents/assistant_message.py` | Guard list `content` before assigning to `out["content"]` |
| `api/app/agents/automation_agent.py` | Add `browser_click_at`, `browser_mouse_move` to `BROWSER_TOOLS` |
| `api/app/agents/prompts/browser_chat.md` | Add CAPTCHA section + new tool rows |
| `api/tests/test_browser_chat_agent.py` | Tests for `_extract_text`, error flag, new dispatch paths |
| `frontend/src/components/BrowserChatPage.tsx` | Add `actions` state + render action feed |
| `browser-agent/requirements.txt` | Add `playwright-stealth` |
| `browser-agent/main.py` | Stealth launch args + UA, `stealth_async` on page, `delay=150` on x/y click, new `/mouse_move` endpoint |

---

## Task 1: Reply Text Guard

Fix garbled output when `msg.content` is a list of content blocks instead of a plain string (Anthropic extended thinking / multimodal responses).

**Files:**
- Modify: `api/app/agents/browser_chat_agent.py`
- Modify: `api/app/agents/assistant_message.py`
- Modify: `api/tests/test_browser_chat_agent.py`

- [ ] **Step 1: Write failing tests for `_extract_text`**

Add to `api/tests/test_browser_chat_agent.py` (import `_extract_text` at the top alongside `_dispatch`):

```python
from app.agents.browser_chat_agent import _dispatch, _extract_text

def test_extract_text_plain_string():
    assert _extract_text("hello world") == "hello world"

def test_extract_text_list_extracts_text_blocks():
    content = [
        {"type": "thinking", "thinking": "let me think"},
        {"type": "text", "text": "Here are the results."},
    ]
    assert _extract_text(content) == "Here are the results."

def test_extract_text_multiple_text_blocks():
    content = [
        {"type": "text", "text": "Part one."},
        {"type": "text", "text": "Part two."},
    ]
    assert _extract_text(content) == "Part one. Part two."

def test_extract_text_list_with_no_text_blocks_returns_done():
    content = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}]
    assert _extract_text(content) == "Done."

def test_extract_text_empty_list_returns_done():
    assert _extract_text([]) == "Done."

def test_extract_text_none_returns_done():
    assert _extract_text(None) == "Done."
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd api && python -m pytest tests/test_browser_chat_agent.py::test_extract_text_plain_string -v
```

Expected: `ImportError: cannot import name '_extract_text'`

- [ ] **Step 3: Add `_extract_text` to `browser_chat_agent.py`**

Add this function at module level, directly after the `_log = structlog.get_logger()` line (around line 22):

```python
def _extract_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip() or "Done."
    return "Done."
```

Then replace in `run_turn` (currently around line 93):
```python
# BEFORE:
reply_text = getattr(msg, "content", None) or "Done."

# AFTER:
reply_text = _extract_text(getattr(msg, "content", None))
```

- [ ] **Step 4: Guard `assistant_message_for_litellm` against list content**

In `api/app/agents/assistant_message.py`, replace lines 24-26:

```python
# BEFORE:
content = getattr(msg, "content", None)
if content:
    out["content"] = content

# AFTER:
content = getattr(msg, "content", None)
if isinstance(content, list):
    content = " ".join(
        block.get("text", "") for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip() or None
if content:
    out["content"] = content
```

- [ ] **Step 5: Run all `_extract_text` tests**

```bash
cd api && python -m pytest tests/test_browser_chat_agent.py -k "extract_text" -v
```

Expected: 6 tests PASS

- [ ] **Step 6: Run full test suite**

```bash
make test-local
```

Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add api/app/agents/browser_chat_agent.py api/app/agents/assistant_message.py api/tests/test_browser_chat_agent.py
git commit -m "fix(browser-chat): guard multimodal msg.content from leaking into reply text"
```

---

## Task 2: Action Feed — Error Flag

When a tool call fails, `_dispatch` catches the exception and returns `"Error: ..."`. Add an `error` flag to the published SSE action event so the frontend can render it distinctly.

**Files:**
- Modify: `api/app/agents/browser_chat_agent.py`
- Modify: `api/tests/test_browser_chat_agent.py`

- [ ] **Step 1: Write failing test**

Add to `api/tests/test_browser_chat_agent.py`:

```python
@pytest.mark.asyncio
async def test_navigate_error_publishes_error_flag(wiki, patch_broadcaster):
    """When _dispatch returns an error string, run_turn publishes error=True on the action event."""
    # Simulate a failed HTTP call inside navigate
    http = MagicMock()
    http.post = AsyncMock(side_effect=Exception("connection refused"))

    # _dispatch is called directly here; the error is caught by run_turn, not _dispatch itself.
    # Test _action's error flag by calling navigate and letting it raise.
    # Instead, test the helper directly: error flag is set when result_str starts with "Error:".
    # We test this by inspecting what _dispatch publishes on a bad click (no selector/text).
    result = await _dispatch("browser_click", {}, "sid", _make_http(), wiki, "chat-1", "u1")
    assert result.startswith("Error")
    # No action event should have been published for early-return error paths
    patch_broadcaster.publish.assert_not_awaited()
```

Wait — looking at the current code, the `_action` helper in `_dispatch` is only called on successful paths. The error cases (`"return 'Error: provide selector or text'"`) return before calling `_action`. The error flag belongs in the `run_turn` loop where exceptions are caught:

```python
try:
    result_str = await _dispatch(...)
except Exception as tool_exc:
    result_str = f"Error: {tool_exc}"
```

The `_action` call is inside `_dispatch` for success. For the error path we need to publish from `run_turn`. Replace the test above with:

```python
@pytest.mark.asyncio
async def test_run_turn_publishes_error_action_on_dispatch_exception(patch_broadcaster):
    """run_turn publishes an error action SSE event when _dispatch raises."""
    import litellm
    from unittest.mock import patch as upatch
    from app.agents.browser_chat_agent import run_turn

    # First LLM call returns a tool_call for browser_navigate.
    # _dispatch will raise because http.post raises.
    tool_call = MagicMock()
    tool_call.id = "tc1"
    tool_call.function.name = "browser_navigate"
    tool_call.function.arguments = '{"url": "https://example.com"}'

    first_msg = MagicMock()
    first_msg.tool_calls = [tool_call]
    first_msg.content = None

    # Second call: no tool calls, returns plain text.
    second_msg = MagicMock()
    second_msg.tool_calls = []
    second_msg.content = "Done navigating."

    first_resp = MagicMock()
    first_resp.choices = [MagicMock(message=first_msg)]
    second_resp = MagicMock()
    second_resp.choices = [MagicMock(message=second_msg)]

    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

    with upatch("litellm.acompletion", new=AsyncMock(side_effect=[first_resp, second_resp])):
        with upatch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(side_effect=Exception("network error"))
            mock_client_cls.return_value = mock_http

            await run_turn(
                chat_session_id="chat-1",
                workspace_id="ws-1",
                browser_session_id="b-1",
                conversation_history=[{"role": "user", "content": "go to example.com"}],
                audience_user_id="u1",
                db_session=db,
            )

    # Find the error action event among all publishes
    calls = [c[0][0] for c in patch_broadcaster.publish.call_args_list]
    error_actions = [c for c in calls if c.get("event") == "browser_chat:action" and c.get("error") is True]
    assert len(error_actions) == 1
    assert "network error" in error_actions[0]["detail"]
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd api && python -m pytest tests/test_browser_chat_agent.py::test_run_turn_publishes_error_action_on_dispatch_exception -v
```

Expected: FAIL — `AssertionError: assert 0 == 1` (no error action events published)

- [ ] **Step 3: Add error action publishing to `run_turn` in `browser_chat_agent.py`**

In `run_turn`, replace the exception handler in the tool call loop (currently around lines 106-108):

```python
# BEFORE:
try:
    result_str = await _dispatch(
        name, args, browser_session_id, http,
        wiki_tools, chat_session_id, audience_user_id,
    )
except Exception as tool_exc:
    result_str = f"Error: {tool_exc}"

# AFTER:
try:
    result_str = await _dispatch(
        name, args, browser_session_id, http,
        wiki_tools, chat_session_id, audience_user_id,
    )
except Exception as tool_exc:
    result_str = f"Error: {tool_exc}"
    await broadcaster.publish(
        {
            "event": "browser_chat:action",
            "session_id": chat_session_id,
            "type": name,
            "detail": str(tool_exc),
            "error": True,
        },
        audience_user_id=audience_user_id,
    )
```

- [ ] **Step 4: Run the test**

```bash
cd api && python -m pytest tests/test_browser_chat_agent.py::test_run_turn_publishes_error_action_on_dispatch_exception -v
```

Expected: PASS

- [ ] **Step 5: Run full test suite**

```bash
make test-local
```

Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add api/app/agents/browser_chat_agent.py api/tests/test_browser_chat_agent.py
git commit -m "fix(browser-chat): publish error action SSE event when tool dispatch raises"
```

---

## Task 3: Action Feed UI

Render `browser_chat:action` SSE events as inline activity rows in the chat column. Show error actions in red.

**Files:**
- Modify: `frontend/src/components/BrowserChatPage.tsx`

No automated frontend tests — verify visually after the dev server starts.

- [ ] **Step 1: Add `ActionItem` type and `actions` state**

At the top of `BrowserChatPage.tsx`, add the type after the existing imports:

```typescript
type ActionItem = {
  id: string
  type: string
  detail: string
  error?: boolean
}
```

Inside `BrowserChatPage()`, add `actions` state after the existing state declarations:

```typescript
const [actions, setActions] = useState<ActionItem[]>([])
```

- [ ] **Step 2: Add the icon helper**

Add this constant outside the component (after the `smallBtn` style at the bottom of the file):

```typescript
function actionIcon(type: string): string {
  const icons: Record<string, string> = {
    navigate: '→',
    page_state: '⊞',
    click: '↖',
    click_at: '↖',
    mouse_move: '⤷',
    type: '✎',
    key: '⌨',
    focus: '◎',
    hover: '⤳',
    select: '▾',
    scroll: '⟳',
    wait_for: '⌛',
    read: '≡',
    execute_js: '{}',
    screenshot: '📷',
    wiki_write: '✦',
  }
  return icons[type] ?? '·'
}
```

- [ ] **Step 3: Wire up SSE handler to append actions and clear on send**

In the `useSse` callback, add handling for `browser_chat:action` events (replacing the current handler which only updates `currentUrl`):

```typescript
useSse((data: unknown) => {
  const ev = data as Record<string, unknown>
  if (ev.session_id !== activeSessionId) return

  if (ev.event === 'browser_chat:action') {
    if (ev.type === 'navigate') {
      setCurrentUrl(String(ev.detail ?? '').replace('Navigated to ', ''))
    }
    setActions(prev => [...prev, {
      id: String(Date.now()) + Math.random(),
      type: String(ev.type ?? ''),
      detail: String(ev.detail ?? ''),
      error: ev.error === true,
    }])
  }
  if (ev.event === 'browser_chat:reply') {
    const msg: BrowserChatMessage = {
      id: String(Date.now()),
      role: 'assistant',
      content: String(ev.content ?? ''),
      created_at: new Date().toISOString(),
    }
    setMessages(prev => [...prev, msg])
    setAgentRunning(false)
    inputRef.current?.focus()
  }
  if (ev.event === 'browser_chat:status') {
    setAgentRunning(ev.status === 'thinking')
  }
})
```

In `handleSend`, clear actions when the user sends a new message — add `setActions([])` right after `setAgentRunning(true)`:

```typescript
setAgentRunning(true)
setActions([])   // ← add this line
```

- [ ] **Step 4: Render action rows inline in the message list**

In the message list `div` (the one containing `messages.map(...)`), add action rendering. Replace the existing messages render block:

```tsx
{messages.map((msg, msgIdx) => {
  // Actions that arrived after the previous message and before this one
  const prevMsgTime = msgIdx > 0 ? new Date(messages[msgIdx - 1].created_at).getTime() : 0
  const thisMsgTime = new Date(msg.created_at).getTime()
  // For simplicity: render all current actions after the last assistant message
  // (actions are cleared per-turn, so they always belong to the current in-progress turn)
  return (
    <React.Fragment key={msg.id}>
      <div style={{
        alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
        maxWidth: '90%',
        background: msg.role === 'user' ? '#1f3a5f' : '#21262d',
        border: `1px solid ${msg.role === 'user' ? '#388bfd40' : '#30363d'}`,
        borderRadius: msg.role === 'user' ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
        padding: '8px 12px',
        fontSize: 13,
        color: '#e6edf3',
        lineHeight: 1.5,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      }}>
        {msg.content}
      </div>
    </React.Fragment>
  )
})}
{/* Live action feed for the current in-progress turn */}
{actions.map(action => (
  <div key={action.id} style={{
    alignSelf: 'flex-start',
    display: 'flex',
    alignItems: 'baseline',
    gap: 6,
    padding: '3px 8px',
    fontSize: 11,
    color: action.error ? '#f85149' : '#8b949e',
    fontFamily: 'monospace',
  }}>
    <span>{action.error ? '⚠' : actionIcon(action.type)}</span>
    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 260 }}>
      {action.detail}
    </span>
  </div>
))}
```

Note: `React.Fragment` requires `import React from 'react'` — ensure that import is present at the top of the file (it already is since `useCallback` etc. are imported from `'react'`, but `React` default import must be explicit for JSX `<React.Fragment>`). If the file uses `import React, { ... } from 'react'` it's fine; if it's `import { ... } from 'react'` only, add `React` to the default import.

- [ ] **Step 5: Verify visually**

```bash
cd frontend && npm run dev
```

Open the browser chat, connect, send a message. You should see grey activity rows appearing in the chat column as the agent works (navigate, click, type, etc.). Error rows should appear red with ⚠ when a tool fails.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/BrowserChatPage.tsx
git commit -m "feat(browser-chat): add live action feed to chat column"
```

---

## Task 4: Browser-Agent Stealth

Add `playwright-stealth`, anti-detection launch args, realistic UA, and the `/mouse_move` endpoint to the browser-agent service.

**Files:**
- Modify: `browser-agent/requirements.txt`
- Modify: `browser-agent/main.py`

- [ ] **Step 1: Add `playwright-stealth` to requirements**

In `browser-agent/requirements.txt`, add:

```
playwright-stealth==1.0.6
```

(Check PyPI for the latest version — as of 2026-05 this is `1.0.6`. Pin to a specific version for reproducibility.)

- [ ] **Step 2: Update `session_new` in `browser-agent/main.py` with stealth**

Replace the `session_new` function:

```python
from playwright_stealth import stealth_async

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

@app.post("/session/new")
async def session_new():
    session_id = str(uuid.uuid4())
    video_dir = tempfile.mkdtemp()
    launch_kwargs: dict = {
        "headless": False,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    if _CHROMIUM_PATH:
        launch_kwargs["executable_path"] = _CHROMIUM_PATH
    browser = await _playwright.chromium.launch(**launch_kwargs)
    context = await browser.new_context(
        record_video_dir=video_dir,
        viewport={"width": 1280, "height": 800},
        user_agent=_UA,
    )
    page = await context.new_page()
    await stealth_async(page)
    _sessions[session_id] = {
        "browser": browser,
        "context": context,
        "page": page,
        "video_dir": video_dir,
    }
    return {"session_id": session_id}
```

The `_UA` constant and the `from playwright_stealth import stealth_async` import go at the top of the file, after the existing imports.

- [ ] **Step 3: Add `delay=150` to the x/y click path**

In `session_click`, change the `elif body.x is not None` branch:

```python
# BEFORE:
elif body.x is not None and body.y is not None:
    await s["page"].mouse.click(body.x, body.y)

# AFTER:
elif body.x is not None and body.y is not None:
    await s["page"].mouse.click(body.x, body.y, delay=150)
```

- [ ] **Step 4: Add `/mouse_move` endpoint**

Add the model and endpoint after the `session_focus` handler:

```python
class MouseMoveRequest(BaseModel):
    x: float
    y: float


@app.post("/session/{session_id}/mouse_move")
async def session_mouse_move(session_id: str, body: MouseMoveRequest):
    s = _get_session(session_id)
    await s["page"].mouse.move(body.x, body.y)
    return {"ok": True}
```

- [ ] **Step 5: Rebuild the browser-agent Docker image**

```bash
docker compose build browser-agent
```

Expected: build succeeds. If `playwright-stealth` fails to install, check the package name — it may be `playwright_stealth` (underscore) on some registries.

- [ ] **Step 6: Smoke-test the new session endpoint**

```bash
docker compose up -d browser-agent
curl -s -X POST http://localhost:9222/session/new | python3 -m json.tool
```

Expected: `{"session_id": "<uuid>"}` — no errors.

- [ ] **Step 7: Commit**

```bash
git add browser-agent/requirements.txt browser-agent/main.py
git commit -m "feat(browser-agent): add playwright-stealth, anti-detection args, mouse_move endpoint"
```

---

## Task 5: New Browser Tools — `browser_click_at` and `browser_mouse_move`

Expose coordinate-level mouse control to the agent by adding two tools to `BROWSER_TOOLS` and wiring their dispatch.

**Files:**
- Modify: `api/app/agents/automation_agent.py`
- Modify: `api/app/agents/browser_chat_agent.py`
- Modify: `api/tests/test_browser_chat_agent.py`

- [ ] **Step 1: Write failing tests**

Add to `api/tests/test_browser_chat_agent.py`:

```python
@pytest.mark.asyncio
async def test_click_at_posts_to_click_endpoint_with_coordinates(wiki, patch_broadcaster):
    http = _make_http({"ok": True})
    result = await _dispatch("browser_click_at", {"x": 400.0, "y": 300.0}, "sid", http, wiki, "chat-1", "u1")
    assert result == "clicked"
    http.post.assert_awaited_once_with("/session/sid/click", json={"x": 400.0, "y": 300.0})
    published = patch_broadcaster.publish.call_args[0][0]
    assert published["type"] == "click_at"
    assert "400" in published["detail"]
    assert "300" in published["detail"]


@pytest.mark.asyncio
async def test_mouse_move_posts_to_mouse_move_endpoint(wiki, patch_broadcaster):
    http = _make_http({"ok": True})
    result = await _dispatch("browser_mouse_move", {"x": 200.0, "y": 150.0}, "sid", http, wiki, "chat-1", "u1")
    assert result == "moved"
    http.post.assert_awaited_once_with("/session/sid/mouse_move", json={"x": 200.0, "y": 150.0})
    published = patch_broadcaster.publish.call_args[0][0]
    assert published["type"] == "mouse_move"
    assert "200" in published["detail"]
    assert "150" in published["detail"]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd api && python -m pytest tests/test_browser_chat_agent.py::test_click_at_posts_to_click_endpoint_with_coordinates tests/test_browser_chat_agent.py::test_mouse_move_posts_to_mouse_move_endpoint -v
```

Expected: both FAIL — dispatch falls through to wiki tools and returns `"wiki result"`

- [ ] **Step 3: Add dispatch handlers to `browser_chat_agent.py`**

In `_dispatch`, add the two new handlers before the wiki tools fallback (i.e., before `wiki_result = await wiki_tools.dispatch(name, args)`):

```python
if name == "browser_click_at":
    resp = await http.post(f"/session/{browser_session_id}/click", json={"x": args["x"], "y": args["y"]})
    resp.raise_for_status()
    await _action("click_at", f"Clicked at ({int(args['x'])}, {int(args['y'])})")
    return "clicked"

if name == "browser_mouse_move":
    resp = await http.post(f"/session/{browser_session_id}/mouse_move", json={"x": args["x"], "y": args["y"]})
    resp.raise_for_status()
    await _action("mouse_move", f"Moved to ({int(args['x'])}, {int(args['y'])})")
    return "moved"
```

- [ ] **Step 4: Run the new tests**

```bash
cd api && python -m pytest tests/test_browser_chat_agent.py::test_click_at_posts_to_click_endpoint_with_coordinates tests/test_browser_chat_agent.py::test_mouse_move_posts_to_mouse_move_endpoint -v
```

Expected: both PASS

- [ ] **Step 5: Add tools to `BROWSER_TOOLS` in `automation_agent.py`**

Append the two new tool definitions to the `BROWSER_TOOLS` list (before the closing `]`):

```python
    {
        "type": "function",
        "function": {
            "name": "browser_click_at",
            "description": (
                "Click at exact pixel coordinates on the screen. "
                "Use when selector/text clicking fails — e.g. Cloudflare checkboxes inside iframes. "
                "The viewport is 1280×800. Call browser_mouse_move first to position the cursor near "
                "the target, take a screenshot to verify, then call this to click. "
                "The click uses a realistic press duration automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "number", "description": "Horizontal pixel coordinate (0–1280)"},
                    "y": {"type": "number", "description": "Vertical pixel coordinate (0–800)"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_mouse_move",
            "description": (
                "Move the mouse cursor to pixel coordinates without clicking. "
                "Use before browser_click_at to approach the target naturally — "
                "move near the element first, take a screenshot to verify the cursor is in the right area, "
                "then use browser_click_at. The viewport is 1280×800."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "number", "description": "Horizontal pixel coordinate (0–1280)"},
                    "y": {"type": "number", "description": "Vertical pixel coordinate (0–800)"},
                },
                "required": ["x", "y"],
            },
        },
    },
```

- [ ] **Step 6: Run full test suite**

```bash
make test-local
```

Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add api/app/agents/browser_chat_agent.py api/app/agents/automation_agent.py api/tests/test_browser_chat_agent.py
git commit -m "feat(browser-chat): add browser_click_at and browser_mouse_move tools"
```

---

## Task 6: Agent Prompt Update

Update the browser chat system prompt to reference the two new tools and add the Cloudflare challenge handling workflow.

**Files:**
- Modify: `api/app/agents/prompts/browser_chat.md`

- [ ] **Step 1: Add new tool rows to the Tool Reference table**

In `browser_chat.md`, add two rows to the tool reference table (after the `browser_scroll` row):

```markdown
| `browser_click_at(x, y)` | Click at pixel coordinates — use for iframes and CAPTCHA checkboxes |
| `browser_mouse_move(x, y)` | Move cursor without clicking — approach target before browser_click_at |
```

- [ ] **Step 2: Add the CAPTCHA handling section**

Append to the end of `browser_chat.md`:

```markdown
## Handling Cloudflare and CAPTCHA challenges

If you land on a page with title "Just a moment...", "Verify you are human", or
"Additional Verification Required":

1. Call `browser_screenshot` to see the current state.
2. Identify the checkbox or button in the screenshot. Estimate its centre
   coordinates — the viewport is 1280×800.
3. Call `browser_mouse_move` to a point near but not on the target (approach it
   like a human moving their hand toward a button).
4. Call `browser_screenshot` again to confirm the cursor is hovering near the
   target. Adjust your estimate if needed. Do not click until you can see the
   cursor is in the right area.
5. Call `browser_click_at` with the target coordinates. The click includes a
   realistic press duration automatically.
6. Call `browser_wait_for` with a text or selector from the destination page
   (e.g. a heading or nav element expected after the challenge clears) to
   detect when the challenge resolves.
7. Take a final `browser_screenshot` to confirm you are past the challenge
   before continuing.

If the challenge does not clear after one attempt, try once more from step 3
with adjusted coordinates before reporting failure.
```

- [ ] **Step 3: Run tests to ensure nothing broke**

```bash
make test-local
```

Expected: all tests PASS (prompt is loaded at import time — if the file is malformed the agent tests will fail)

- [ ] **Step 4: Commit**

```bash
git add api/app/agents/prompts/browser_chat.md
git commit -m "feat(browser-chat): add CAPTCHA handling guidance and coordinate tool docs to prompt"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| Action feed renders `browser_chat:action` events | Task 3 |
| Action feed clears on new user message | Task 3, Step 3 |
| Error actions rendered in red with ⚠ | Tasks 2 + 3 |
| `_extract_text` guard on `reply_text` | Task 1 |
| `assistant_message_for_litellm` list guard | Task 1, Step 4 |
| `playwright-stealth` in browser-agent | Task 4 |
| `--disable-blink-features=AutomationControlled` | Task 4 |
| Realistic user-agent on context | Task 4 |
| `delay=150` on x/y click | Task 4, Step 3 |
| `/mouse_move` endpoint | Task 4, Step 4 |
| `browser_click_at` tool in `BROWSER_TOOLS` | Task 5 |
| `browser_mouse_move` tool in `BROWSER_TOOLS` | Task 5 |
| Dispatch handlers for both tools | Task 5, Step 3 |
| CAPTCHA prompt section | Task 6 |
| New tool rows in prompt table | Task 6 |

All spec requirements covered. ✓
