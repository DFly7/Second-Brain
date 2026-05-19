# Browser Chat Improvements — Design Spec

Date: 2026-05-19

## Overview

Three independent fixes to the browser chat feature:

1. **Action feed** — show the agent's tool calls as live activity rows in the chat UI
2. **Reply text guard** — prevent multimodal `msg.content` lists from leaking into stored replies
3. **Stealth + visual input tools** — make the browser undetectable and give the agent coordinate-level control

---

## Fix 1 — Action Feed (Issue: tool calls invisible)

### Problem
The backend emits `browser_chat:action` SSE events for every tool call (navigate, click, type, screenshot, etc.) with `type` and `detail` fields. The frontend receives them but only uses navigate events to update the URL bar. All other action types are silently dropped.

### Solution
Maintain an `actions: ActionItem[]` state list in `BrowserChatPage.tsx`. Each `browser_chat:action` SSE event appends `{ type, detail, timestamp }`. Render these as slim activity rows inline in the chat message column, visually distinct from user/assistant messages:

- Muted grey background, smaller font, left-aligned
- Small icon prefix per type: `→` navigate, `↖` click, `✎` type, `📷` screenshot, `⌛` wait, `⟳` scroll, `{}` JS, etc.
- Display the `detail` string (already human-readable, e.g. "Navigated to uk.indeed.com", "Clicked 'Find Jobs'", "Typed 'graduate tech'")
- Clear the actions list when a new user message is sent (fresh slate per turn)
- Render failed actions distinctly: if a tool call raises an exception, `_dispatch` already catches it and returns `"Error: ..."`. The backend should emit an action event with `"error": true` in that case, and the frontend renders it with a `⚠` prefix and red text instead of grey.

No backend changes required for the happy path — events are already being emitted. The error flag requires a small addition to `_dispatch`: detect when `result_str` starts with `"Error:"` and include `"error": True` in the published action event.

---

## Fix 2 — Reply Text Guard (Issue: "image.png" / garbled final output)

### Problem
`msg.content` from litellm can be a list of content blocks (Anthropic extended thinking mode, or certain multimodal model responses) rather than a plain string. The current code does:

```python
reply_text = getattr(msg, "content", None) or "Done."
```

If `msg.content` is a list, `reply_text` becomes that list. This propagates to:
- `BrowserChatMessage.content` in the DB (stored as a stringified list)
- The `browser_chat:reply` SSE event `content` field
- The frontend rendering it as `[object Object],[object Object]` or similar

### Solution
Replace the assignment in `run_turn` (`browser_chat_agent.py`) with a helper that handles both cases:

```python
def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip() or "Done."
    return "Done."

reply_text = _extract_text(getattr(msg, "content", None))
```

Apply the same guard in `assistant_message_for_litellm` when setting `out["content"]` to avoid passing a list into the conversation history.

---

## Fix 3 — Stealth + Coordinate Control (Issue: Cloudflare bot detection)

### Problem
Playwright's default browser launch leaves detectable automation signals (`navigator.webdriver = true`, distinctive canvas/WebGL fingerprints, missing plugin lists, etc.). Cloudflare Turnstile evaluates these signals:

- Phase 1 (silent): JS fingerprint check. If detected as a bot → phase 2.
- Phase 2 (interactive): Shows a "Verify you are human" checkbox in an iframe.

Currently even when the user manually solves the challenge in noVNC, Cloudflare's JS still sees the fingerprint and blocks the request. The Pi's residential IP is fine — the problem is purely browser fingerprinting.

### 3a — playwright-stealth

Add `playwright-stealth` to `browser-agent/requirements.txt`.

In `session_new` in `browser-agent/main.py`, after `page = await context.new_page()`:

```python
from playwright_stealth import stealth_async
await stealth_async(page)
```

Also update the browser context creation to add:
- Launch arg: `--disable-blink-features=AutomationControlled`
- A realistic desktop user-agent string on the context (e.g. Chrome 124 on macOS)

This covers: `navigator.webdriver`, canvas fingerprint, WebGL fingerprint, plugin/mimeType lists, language/platform consistency, Chrome runtime object.

With stealth applied, most Cloudflare "Just a moment..." challenges auto-resolve without any interaction.

### 3b — New tools: `browser_click_at` and `browser_mouse_move`

The browser runs `headless: False` on an Xvfb display streamed via noVNC, so all mouse movements are visible as a real cursor in the browser window. The existing `/session/{id}/click` API endpoint already accepts `x: float` and `y: float` but this is not exposed to the agent.

**Add two new tools to `BROWSER_TOOLS`** (in `automation_agent.py`, shared with browser chat):

```
browser_click_at(x, y)   — move cursor to (x,y) and click (left button)
browser_mouse_move(x, y) — move cursor to (x,y) without clicking
```

**Wire in `browser-agent/main.py`**: `browser_click_at` uses `page.mouse.click(x, y, delay=150)`. The `delay=150` parameter inserts a 150ms gap between `mousedown` and `mouseup` — Cloudflare Turnstile monitors click speed and flags instantaneous (`mousedown`+`mouseup` simultaneously) events as bot activity. `browser_mouse_move` calls `page.mouse.move(x, y)` — add a new `/session/{id}/mouse_move` endpoint.

**Wire in `browser_chat_agent.py` `_dispatch`**: Add handlers for both tools, emitting `browser_chat:action` events with type `"click_at"` and `"mouse_move"`.

**Viewport note**: The browser is launched at 1280×800. Document this in the tool descriptions so the agent knows the coordinate space.

### 3c — Agent prompt update

Add a section to `browser_chat.md`:

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

---

## Files changed

| File | Change |
|------|--------|
| `frontend/src/components/BrowserChatPage.tsx` | Add `actions` state, render action feed |
| `api/app/agents/browser_chat_agent.py` | `_extract_text` guard, `browser_click_at` + `browser_mouse_move` dispatch |
| `api/app/agents/assistant_message.py` | Guard `content` assignment against list |
| `api/app/agents/automation_agent.py` | Add `browser_click_at`, `browser_mouse_move` to `BROWSER_TOOLS` |
| `api/app/agents/prompts/browser_chat.md` | CAPTCHA handling section, new tool reference rows |
| `browser-agent/main.py` | `playwright-stealth` init, `/mouse_move` endpoint, stealth launch args + UA |
| `browser-agent/requirements.txt` | Add `playwright-stealth` |

---

## Out of scope

- CAPTCHA solving services (2captcha etc.) — not needed with stealth
- Pause-and-wait user notification flow — not needed with autonomous solving
- Changes to automation agent prompt (separate feature)
