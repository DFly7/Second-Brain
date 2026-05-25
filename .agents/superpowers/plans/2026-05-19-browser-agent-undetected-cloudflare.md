# Browser Agent Undetected / Cloudflare Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the browser agent pass Cloudflare's "Verify you are human" Turnstile/interstitial automatically by replacing detectable Playwright with the patched `patchright` browser stack, so sites like gradcracker.com stop blocking the agent.

**Architecture:** The root cause is not "the agent clicks the checkbox badly" — it is that stock Playwright's bundled Chromium sends the `Runtime.enable` CDP command, which Cloudflare detects *before any checkbox matters*. We swap `playwright` + `playwright_stealth` for `patchright` (a source-patched Playwright drop-in that never sends `Runtime.enable`), launch via `launch_persistent_context` with a real Chrome channel and per-session profile, and remove the anti-detection hacks (`_LAUNCH_ARGS`, custom user-agent, `stealth_async`, `add_init_script`) that patchright forbids — those hacks are now *bot tells*, not cloaks. Cloudflare's passive layer then usually clears with no checkbox at all. The Cloudflare endpoint is rewritten from "frantically click" to "wait for auto-clear, then click once only if still stuck". No paid CAPTCHA services — this is a pure agent browser.

**Tech Stack:** Python 3 / FastAPI / `patchright` (patched Playwright async API) / Docker (Ubuntu 22.04, Xvfb + x11vnc + noVNC) / litellm (api side).

---

## Background — why the current code fails

`browser-agent/main.py` today:
- Line 12-14: imports `playwright` + `playwright_stealth`.
- Line 83-96 `_LAUNCH_ARGS`: `--disable-blink-features=AutomationControlled` etc. — these flags are themselves fingerprinted by Cloudflare in 2025/2026.
- Line 140 `user_agent=_UA`: a hard-coded UA that mismatches the real binary.
- Line 146 `stealth_async(page)`: JS patches applied *after* the CDP leak — too late.
- Line 147 `add_init_script(_CURSOR_SCRIPT)`: init scripts run in the main-world context and re-expose the `Runtime.enable` leak patchright works to close.
- `/session/{id}/click_cloudflare` (line 247-300): tries to click the Turnstile checkbox. But once Cloudflare's passive layer has flagged the browser, clicking does nothing — the agent loops until the turn limit (exactly the failure in the user's screenshot).

patchright fixes the `Runtime.enable` leak at the source. After migration, Cloudflare's passive check usually passes silently. The few interactive challenges that remain are handled by a single patched click.

**patchright "DO NOT" rules** (violating these defeats the purpose — they are load-bearing):
1. DO NOT pass custom `args=[...]` to launch — patchright manages its own flags.
2. DO NOT set `user_agent=` or custom headers — patchright supplies a correct one.
3. DO NOT use `playwright_stealth` / `stealth_async` — it conflicts and adds detection surface.
4. DO NOT use `add_init_script` — it re-opens the CDP leak. Inject DOM helpers via `page.evaluate` *after* navigation instead.
5. DO NOT set a fixed `viewport` — use `no_viewport=True`.
6. `page.on("console", ...)` will not fire (patchright disables `Console.enable`). The codebase does not use it — safe.

---

## File Map

| File | Change |
|------|--------|
| `browser-agent/requirements.txt` | Replace `playwright` + `playwright-stealth` with `patchright` |
| `browser-agent/Dockerfile` | Install patchright browser (chrome on x86_64, chromium on arm64) + fonts; set `BROWSER_CHANNEL` |
| `browser-agent/main.py` | Swap to patchright import; rewrite `_new_page` → persistent context; update `session_new`, `session_recover`, `session_close`, `lifespan`; cursor via `page.evaluate`; rewrite `click_cloudflare` → `await_cloudflare`; human-like click delay |
| `api/app/agents/automation_agent.py` | Rename `browser_click_cloudflare` tool → `browser_await_cloudflare`, update description |
| `api/app/agents/browser_chat_agent.py` | Update `_dispatch` branch for the renamed tool |
| `api/app/agents/prompts/browser_chat.md` | Rewrite "Handling Cloudflare" section + tool table row |
| `api/tests/test_browser_chat_agent.py` | Add test for `browser_await_cloudflare` dispatch |

---

### Task 1: Swap browser-agent dependencies to patchright

**Files:**
- Modify: `browser-agent/requirements.txt`

- [ ] **Step 1: Replace the playwright dependencies**

Replace the entire contents of `browser-agent/requirements.txt` with:

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
patchright==1.49.0
boto3==1.35.0
pydantic==2.9.2
```

`patchright` versions track Playwright's; `1.49.0` matches the Playwright version currently pinned. `playwright-stealth` is removed entirely — patchright supersedes it.

- [ ] **Step 2: Commit**

```bash
git add browser-agent/requirements.txt
git commit -m "build(browser-agent): replace playwright+stealth with patchright"
```

---

### Task 2: Update the Dockerfile to install the patched browser

**Files:**
- Modify: `browser-agent/Dockerfile`

The current Dockerfile installs `chromium-browser` via apt on arm64 and runs `playwright install chromium` on x86_64. patchright ships its own `patchright install` command. Google Chrome stable has **no Linux arm64 build**, so x86_64 uses the real Chrome channel and arm64 uses patchright's patched Chromium. Extra fonts improve the fingerprint (font enumeration is a Cloudflare signal).

- [ ] **Step 1: Replace the Dockerfile contents**

Replace the entire contents of `browser-agent/Dockerfile` with:

```dockerfile
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
ARG ARCH=x86_64

RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    xvfb x11vnc x11-utils netcat-openbsd \
    git curl wget \
    fonts-liberation fonts-noto-core fonts-noto-cjk fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install websockify && \
    git clone --depth=1 https://github.com/novnc/noVNC.git /opt/novnc

WORKDIR /app
COPY requirements.txt .
RUN pip3 install -r requirements.txt

# x86_64: install real Google Chrome (best fingerprint). arm64: Chrome has no
# Linux arm64 build, so use patchright's patched Chromium instead.
RUN if [ "$ARCH" = "arm64" ]; then \
        patchright install --with-deps chromium ; \
    else \
        patchright install --with-deps chrome ; \
    fi

COPY . .
RUN chmod +x start.sh

EXPOSE 6080 8001

CMD ["./start.sh"]
```

Notes:
- `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD` and the old `chromium-browser` apt package are removed — `patchright install` handles everything.
- `--with-deps` installs the OS libraries the browser needs.

- [ ] **Step 2: Set BROWSER_CHANNEL in docker-compose (local)**

In `docker-compose.yml`, under the `browser-agent` service `environment:` list (currently lines 49-54), add one line so `main.py` knows which channel to launch:

```yaml
      - BROWSER_CHANNEL=${BROWSER_CHANNEL:-chrome}
```

On an Apple-Silicon Mac building arm64 images, export `BROWSER_CHANNEL=chromium` in your shell (or `.env`) before `docker compose up`, and pass `--build-arg ARCH=arm64`. On x86_64 the default `chrome` is correct.

- [ ] **Step 3: Set BROWSER_CHANNEL in docker-compose.prod**

In `docker-compose.prod.yml`, under the `browser-agent` service `environment:` list (currently lines 46-52), add:

```yaml
      - BROWSER_CHANNEL=${BROWSER_CHANNEL:-chromium}
```

Default is `chromium` here because the Pi (`pi-server.local`) is arm64. The existing `CHROMIUM_EXECUTABLE_PATH` line can stay — `main.py` will ignore it after Task 3 — but is no longer required.

- [ ] **Step 4: Commit**

```bash
git add browser-agent/Dockerfile docker-compose.yml docker-compose.prod.yml
git commit -m "build(browser-agent): install patched browser via patchright, add fonts"
```

---

### Task 3: Rewrite session creation in main.py to use patchright persistent context

**Files:**
- Modify: `browser-agent/main.py`

This is the core change. We move from `playwright.chromium.launch()` + `browser.new_context()` to `patchright`'s recommended `launch_persistent_context()`. A persistent context returns a `BrowserContext` directly (no separate `browser` object) and accumulates cookies — Cloudflare clearance cookies survive within a session, so a site only challenges once.

- [ ] **Step 1: Swap the imports**

In `browser-agent/main.py`, replace lines 12-14:

```python
from playwright.async_api import async_playwright
from playwright._impl._errors import TimeoutError as PlaywrightTimeoutError
from playwright_stealth import stealth_async
```

with:

```python
from patchright.async_api import async_playwright
from patchright._impl._errors import TimeoutError as PlaywrightTimeoutError
```

(`patchright` re-exports Playwright's module tree under the `patchright` namespace, so the `_impl._errors` path is identical.)

Also add `import shutil` to the existing stdlib import block (alphabetical — between `import os` and `import tempfile`). `shutil.rmtree` is used by Steps 6 and 10 to clean up per-session profile/video directories so disk space does not leak on a long-running Pi deployment.

- [ ] **Step 2: Remove the now-forbidden `_UA` and `_LAUNCH_ARGS` constants**

Delete lines 17-20 (`_UA = (...)`) and lines 83-96 (`_LAUNCH_ARGS = [...]`). patchright forbids custom args and user-agent — keeping them re-introduces detection.

- [ ] **Step 3: Add the channel constant near the other env reads**

Replace the line `_CHROMIUM_PATH = os.getenv("CHROMIUM_EXECUTABLE_PATH")` (line 81) with:

```python
# "chrome" = real Google Chrome (x86_64). "chromium" = patchright's patched
# Chromium (arm64, where Chrome has no Linux build). See Dockerfile.
_BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "chromium")
```

- [ ] **Step 4: Rewrite the cursor script as an idempotent function (not an init script)**

Replace the `_CURSOR_SCRIPT` block (lines 100-131) with a version that is safe to run via `page.evaluate` after navigation (it must not assume it runs before page load):

```python
# Injected via page.evaluate AFTER navigation (NOT add_init_script — patchright
# forbids init scripts as they re-open the Runtime.enable CDP leak). Renders a
# red dot that follows the mouse so the cursor is visible in the noVNC view.
_CURSOR_SCRIPT = """() => {
    if (document.getElementById('__pw_cursor__')) return;
    const c = document.createElement('div');
    c.id = '__pw_cursor__';
    c.style.cssText = [
        'position:fixed','width:14px','height:14px','border-radius:50%',
        'background:rgba(220,40,40,0.8)','border:2px solid rgba(255,255,255,0.9)',
        'box-shadow:0 1px 4px rgba(0,0,0,0.45)','pointer-events:none',
        'z-index:2147483647','transform:translate(-50%,-50%)','transition:none',
        'left:-100px','top:-100px',
    ].join(';');
    document.documentElement.appendChild(c);
    document.addEventListener('mousemove', e => {
        c.style.left = e.clientX + 'px';
        c.style.top = e.clientY + 'px';
    }, {passive: true});
}"""


async def _inject_cursor(page):
    """Re-add the visible cursor dot. Safe to call repeatedly; no-op if present."""
    try:
        await page.evaluate(_CURSOR_SCRIPT)
    except Exception:
        pass  # Cursor is cosmetic — never fail a real action over it.
```

- [ ] **Step 5: Rewrite `_new_page` as `_new_session_objects` using a persistent context**

Replace the `_new_page` function (lines 134-148) with:

```python
async def _new_session_objects(video_dir: str, user_data_dir: str):
    """Launch a patchright persistent context + page.

    Returns (context, page). There is no separate `browser` object with
    launch_persistent_context — the context owns the browser process.
    """
    context = await _playwright.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        channel=_BROWSER_CHANNEL,
        headless=False,
        no_viewport=True,
        record_video_dir=video_dir,
        locale="en-GB",
        timezone_id="Europe/London",
        color_scheme="light",
    )
    page = context.pages[0] if context.pages else await context.new_page()
    return context, page
```

Notes:
- No `args`, no `user_agent`, no `viewport`, no `stealth_async`, no `add_init_script` — all forbidden by patchright.
- `locale` / `timezone_id` / `color_scheme` are still allowed and useful (UK localisation).
- A persistent context always opens with one page already in `context.pages`.

- [ ] **Step 6: Update the `lifespan` teardown**

In `lifespan` (lines 31-41), the per-session object stored is now `context`, not `browser`. Replace the teardown loop:

```python
    for s in list(_sessions.values()):
        try:
            await s["browser"].close()
        except Exception:
            pass
```

with:

```python
    for s in list(_sessions.values()):
        try:
            await s["context"].close()
        except Exception:
            pass
        # Clean up the per-session profile + video dirs so a server restart
        # does not leave hundreds of MB behind on the host disk.
        shutil.rmtree(s.get("video_dir") or "", ignore_errors=True)
        shutil.rmtree(s.get("user_data_dir") or "", ignore_errors=True)
```

- [ ] **Step 7: Rewrite `session_new`**

Replace the `session_new` function (lines 151-169) with:

```python
@app.post("/session/new")
async def session_new():
    session_id = str(uuid.uuid4())
    video_dir = tempfile.mkdtemp()
    user_data_dir = tempfile.mkdtemp(prefix="pw-profile-")
    context, page = await _new_session_objects(video_dir, user_data_dir)
    await _inject_cursor(page)
    _sessions[session_id] = {
        "context": context,
        "page": page,
        "video_dir": video_dir,
        "user_data_dir": user_data_dir,
    }
    return {"session_id": session_id}
```

- [ ] **Step 8: Rewrite `session_recover`**

Replace the `session_recover` function (lines 172-199) with:

```python
@app.post("/session/{session_id}/recover")
async def session_recover(session_id: str):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    s = _sessions[session_id]

    # Best-effort teardown of the dead context.
    ctx = s.get("context")
    if ctx is not None:
        try:
            await ctx.close()
        except Exception:
            pass

    video_dir = s.get("video_dir") or tempfile.mkdtemp()
    user_data_dir = s.get("user_data_dir") or tempfile.mkdtemp(prefix="pw-profile-")
    context, page = await _new_session_objects(video_dir, user_data_dir)
    await _inject_cursor(page)

    _sessions[session_id] = {
        "context": context,
        "page": page,
        "video_dir": video_dir,
        "user_data_dir": user_data_dir,
    }
    return {"ok": True}
```

- [ ] **Step 9: Update `session_navigate` to re-inject the cursor**

Replace the `session_navigate` function (lines 206-211) with:

```python
@app.post("/session/{session_id}/navigate")
async def session_navigate(session_id: str, body: NavigateRequest):
    s = _get_session(session_id)
    await s["page"].goto(body.url, wait_until="domcontentloaded")
    await _inject_cursor(s["page"])
    title = await s["page"].title()
    return {"title": title, "url": s["page"].url}
```

- [ ] **Step 10: Update `session_close` (no separate browser object)**

Replace the `session_close` function (lines 473-500) with:

```python
@app.post("/session/{session_id}/close")
async def session_close(session_id: str):
    s = _get_session(session_id)
    page = s["page"]
    context = s["context"]

    video_path = await page.video.path() if page.video else None
    await context.close()

    recording_url = None
    if video_path:
        try:
            _ensure_bucket()
            key = f"automation-recordings/{session_id}.webm"
            with open(video_path, "rb") as f:
                _s3_client().put_object(
                    Bucket=S3_BUCKET,
                    Key=key,
                    Body=f.read(),
                    ContentType="video/webm",
                )
            recording_url = key
        except Exception:
            pass

    del _sessions[session_id]
    # `tempfile.mkdtemp` does NOT auto-clean — wipe the per-session profile
    # and video directories now that the recording is uploaded. Without this,
    # every closed session leaks tens-to-hundreds of MB to host disk.
    shutil.rmtree(s.get("video_dir") or "", ignore_errors=True)
    shutil.rmtree(s.get("user_data_dir") or "", ignore_errors=True)
    return {"recording_url": recording_url}
```

Note: `page.video.path()` must be read *before* `context.close()` — but the video file is only finalised *after* close, so we capture the path first, then close, then upload. This matches the original ordering (original called `context.close()` then read `page.video.path()`; reading the path object is fine either side, but the file content is written on context close, so upload after close is correct).

- [ ] **Step 11: Manual smoke test (browser-agent has no pytest suite)**

The browser-agent has no automated tests. Verify manually after Task 6:

```bash
docker compose up --build browser-agent
# in another terminal:
curl -s -X POST http://localhost:8001/session/new
# → {"session_id":"<uuid>"}
curl -s -X POST http://localhost:8001/session/<uuid>/navigate \
  -H 'Content-Type: application/json' -d '{"url":"https://www.gradcracker.com/"}'
# → expect a real page title, NOT "Just a moment..."
```

Open `http://localhost:6080/vnc.html` to watch the live browser. Expected: gradcracker loads without the Cloudflare interstitial, or the interstitial flashes and self-clears within a few seconds.

- [ ] **Step 12: Commit**

```bash
git add browser-agent/main.py
git commit -m "feat(browser-agent): launch via patchright persistent context, drop stealth hacks"
```

---

### Task 4: Replace the `click_cloudflare` endpoint with `await_cloudflare`

**Files:**
- Modify: `browser-agent/main.py`

With patchright, Cloudflare's passive layer clears on its own — usually with no visible checkbox. The old "click the checkbox" model is wrong: clicking before the passive check finishes does nothing, and clicking after it has *failed* also does nothing. The correct model is **wait for the challenge to clear; only if it is genuinely an interactive checkbox still showing after the wait, click it once.**

- [ ] **Step 1: Replace the `click_cloudflare` endpoint**

Replace the entire `session_click_cloudflare` function and its `_cf_selectors` block (lines 247-300) with:

```python
# Heuristics for "still on a Cloudflare challenge page".
_CF_TITLES = ("just a moment", "verify you are human", "additional verification")


async def _is_cloudflare_challenge(page) -> bool:
    """True if the page still looks like a Cloudflare interstitial."""
    try:
        title = (await page.title() or "").lower()
        if any(t in title for t in _CF_TITLES):
            return True
        for frame in page.frames:
            url = frame.url or ""
            if "challenges.cloudflare.com" in url or "turnstile" in url:
                return True
    except Exception:
        pass
    return False


@app.post("/session/{session_id}/await_cloudflare")
async def session_await_cloudflare(session_id: str):
    """Wait for a Cloudflare challenge to clear on its own. patchright passes
    the passive check automatically; this just polls until it succeeds. If an
    interactive Turnstile checkbox is still present after the initial wait, we
    click it ONCE, then poll again. No frantic re-clicking."""
    s = _get_session(session_id)
    page = s["page"]

    async def _poll_cleared(seconds: float) -> bool:
        deadline = seconds * 2  # poll every 0.5s
        for _ in range(int(deadline)):
            if not await _is_cloudflare_challenge(page):
                return True
            await asyncio.sleep(0.5)
        return False

    # Phase 1: give the passive check time to clear with no interaction.
    if await _poll_cleared(20):
        await _inject_cursor(page)
        return {"cleared": True, "method": "passive"}

    # Phase 2: an interactive checkbox is still showing — click it once.
    # The outer try guards against the frame detaching mid-iteration (which
    # happens if Turnstile auto-clears while we're inspecting frames).
    clicked = False
    for frame in page.frames:
        try:
            url = frame.url or ""
            if "challenges.cloudflare.com" in url or "turnstile" in url:
                for sel in ("input[type=checkbox]", "[role=checkbox]", "label", "body"):
                    try:
                        await frame.click(sel, timeout=2500)
                        clicked = True
                        break
                    except Exception:
                        continue
        except Exception:
            continue  # frame detached — Turnstile likely cleared on its own
        if clicked:
            break

    # Phase 3: poll again after the click.
    if await _poll_cleared(15):
        await _inject_cursor(page)
        return {"cleared": True, "method": "clicked" if clicked else "passive_late"}

    frame_urls = [f.url for f in page.frames if f.url]
    return {
        "cleared": False,
        "clicked": clicked,
        "error": "Cloudflare challenge did not clear",
        "frames_seen": frame_urls[:10],
    }
```

- [ ] **Step 2: Add the `asyncio` import**

At the top of `browser-agent/main.py`, add `import asyncio` to the import block (alphabetically, before `import base64` on line 1):

```python
import asyncio
import base64
```

- [ ] **Step 3: Manual smoke test**

After Task 6, with the browser-agent running:

```bash
curl -s -X POST http://localhost:8001/session/<uuid>/navigate \
  -H 'Content-Type: application/json' -d '{"url":"https://www.gradcracker.com/search/computing-technology/jobs"}'
curl -s -X POST http://localhost:8001/session/<uuid>/await_cloudflare
# → expect {"cleared": true, "method": "passive"}  (or "clicked")
```

- [ ] **Step 4: Commit**

```bash
git add browser-agent/main.py
git commit -m "feat(browser-agent): replace click_cloudflare with await_cloudflare auto-pass"
```

---

### Task 5: Add a small human-like delay to coordinate clicks

**Files:**
- Modify: `browser-agent/main.py`

Cloudflare also has a behavioural layer. A tiny randomised pre-click pause + mouse move makes coordinate clicks look less robotic. This is cheap insurance; keep it minimal (YAGNI — no full mouse-path simulation).

- [ ] **Step 1: Add the `random` import**

Add `import random` to the import block (after `import os`):

```python
import os
import random
```

- [ ] **Step 2: Update the coordinate branch of `session_click`**

In `session_click` (lines 221-232), replace the `elif body.x is not None and body.y is not None:` branch:

```python
    elif body.x is not None and body.y is not None:
        await s["page"].mouse.click(body.x, body.y, delay=150)
```

with:

```python
    elif body.x is not None and body.y is not None:
        page = s["page"]
        await page.mouse.move(body.x, body.y, steps=8)
        await asyncio.sleep(random.uniform(0.08, 0.25))
        await page.mouse.click(body.x, body.y, delay=random.randint(70, 160))
```

`steps=8` makes the cursor glide to the target instead of teleporting; the random sleep + click delay vary the timing.

- [ ] **Step 3: Commit**

```bash
git add browser-agent/main.py
git commit -m "feat(browser-agent): human-like motion on coordinate clicks"
```

---

### Task 6: Rename the agent tool from `browser_click_cloudflare` to `browser_await_cloudflare`

**Files:**
- Test: `api/tests/test_browser_chat_agent.py`
- Modify: `api/app/agents/browser_chat_agent.py:302-309`
- Modify: `api/app/agents/automation_agent.py:244-254`

The API side exposes `browser_click_cloudflare` as an LLM tool. The endpoint it calls is gone, and the *semantics* changed (wait, don't frantically click), so the tool is renamed and re-described. This task is TDD — the API has a real pytest suite.

- [ ] **Step 1: Write the failing test**

Add to the end of `api/tests/test_browser_chat_agent.py`:

```python
@pytest.mark.asyncio
async def test_await_cloudflare_cleared(wiki):
    http = _make_http({"cleared": True, "method": "passive"})
    result = await _dispatch("browser_await_cloudflare", {}, "sid", http, wiki, "chat-1", "u1")
    http.post.assert_awaited_once()
    assert http.post.await_args[0][0].endswith("/session/sid/await_cloudflare")
    assert "cleared" in result.lower()


@pytest.mark.asyncio
async def test_await_cloudflare_not_cleared(wiki):
    http = _make_http({"cleared": False, "error": "Cloudflare challenge did not clear"})
    result = await _dispatch("browser_await_cloudflare", {}, "sid", http, wiki, "chat-1", "u1")
    assert "did not clear" in result.lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd api && make test-local` (or `python3 -m pytest tests/test_browser_chat_agent.py -v -k await_cloudflare`)
Expected: FAIL — `browser_await_cloudflare` falls through to the wiki dispatch branch and returns `"wiki result"`, so the assertions fail.

- [ ] **Step 3: Update the `_dispatch` branch in `browser_chat_agent.py`**

Replace lines 302-309 (`if name == "browser_click_cloudflare":` … through `return result.get("error", "Cloudflare iframe not found")`) with:

```python
    if name == "browser_await_cloudflare":
        resp = await _safe_browser_post(http, f"/session/{browser_session_id}/await_cloudflare")
        result = resp.json()
        if result.get("cleared"):
            method = result.get("method", "")
            await _action("wait_for", f"Cloudflare challenge cleared ({method})")
            return f"Cloudflare challenge cleared ({method}). Call browser_get_page_state to continue."
        await _action("wait_for", "Cloudflare challenge did not clear")
        return result.get("error", "Cloudflare challenge did not clear") + (
            " — try browser_screenshot to inspect, or report to the user that this site is blocking automation."
        )
```

- [ ] **Step 4: Update the tool schema in `automation_agent.py`**

Replace lines 244-254 (the `browser_click_cloudflare` tool object, from `"type": "function",` block ending at `},`) with:

```python
        "type": "function",
        "function": {
            "name": "browser_await_cloudflare",
            "description": (
                "Wait for a Cloudflare 'Verify you are human' / 'Just a moment...' "
                "challenge to clear. The browser is hardened and usually passes the "
                "check automatically within a few seconds — this tool waits for that "
                "and clicks the checkbox once only if one is still shown. Call it once "
                "when you land on a challenge page, then call browser_get_page_state. "
                "Do NOT call it repeatedly or guess checkbox coordinates."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]
```

(The `]` and preceding `},` close the `BROWSER_TOOLS` list — confirm the list still ends correctly: the final tool object's closing `},` followed by `]`.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd api && make test-local`
Expected: PASS — both new tests pass, and the full suite is still green.

- [ ] **Step 6: Run lint**

Run: `cd api && make lint`
Expected: ruff + mypy clean.

- [ ] **Step 7: Commit**

```bash
git add api/app/agents/browser_chat_agent.py api/app/agents/automation_agent.py api/tests/test_browser_chat_agent.py
git commit -m "feat(browser-chat): rename cloudflare tool to browser_await_cloudflare"
```

---

### Task 7: Update the browser-chat prompt

**Files:**
- Modify: `api/app/agents/prompts/browser_chat.md:27` and `:43-64`

The prompt currently tells the agent to call `browser_click_cloudflare()` then fall back to coordinate clicking — both obsolete and the source of the infinite-click loop.

- [ ] **Step 1: Update the tool table row**

In `api/app/agents/prompts/browser_chat.md`, replace line 27:

```
| `browser_click_cloudflare()` | Click the Cloudflare "Verify you are human" checkbox via iframe access — no coordinates needed |
```

with:

```
| `browser_await_cloudflare()` | Wait for a Cloudflare "Verify you are human" challenge to clear — call once, never loop |
```

- [ ] **Step 2: Rewrite the "Handling Cloudflare" section**

Replace the whole section from line 43 (`## Handling Cloudflare and CAPTCHA challenges`) through line 64 (end of file) with:

```markdown
## Handling Cloudflare challenges

The browser is hardened against bot detection, so Cloudflare's "Verify you are
human" check almost always passes on its own within a few seconds.

If you land on a page titled "Just a moment...", "Verify you are human", or
"Additional Verification Required":

1. Call `browser_await_cloudflare()` **once**. It waits for the challenge to
   clear and clicks the checkbox a single time only if one is still showing.
2. When it reports the challenge cleared, call `browser_get_page_state` and
   continue with the task.
3. If it reports the challenge did **not** clear, do not retry it in a loop and
   do not guess checkbox coordinates — that never works. Take one
   `browser_screenshot` to confirm, then tell the user the site is actively
   blocking automated access and you cannot proceed.

Never call `browser_await_cloudflare()` more than twice for the same page.
```

- [ ] **Step 3: Commit**

```bash
git add api/app/agents/prompts/browser_chat.md
git commit -m "docs(browser-chat): rewrite Cloudflare guidance for await-not-click model"
```

---

### Task 8: Full end-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Rebuild and start the stack**

```bash
docker compose up --build browser-agent api frontend
```

On Apple Silicon, first export `BROWSER_CHANNEL=chromium` and build with `--build-arg ARCH=arm64` (see Task 2 Step 2).

- [ ] **Step 2: Reproduce the original failure scenario**

In the browser-chat UI, send: `go to grad cracker and get recent postings for tech London roles`.

Watch the live browser at `http://localhost:6080/vnc.html`.

Expected:
- The agent navigates to gradcracker, the Cloudflare interstitial either does not appear or self-clears within a few seconds.
- The agent calls `browser_await_cloudflare` at most once and gets `cleared: true`.
- The agent reaches the jobs listing and returns results — **no turn-limit loop**.

- [ ] **Step 3: Confirm the API test suite is still green**

Run: `cd api && make test-local && make lint`
Expected: all pass.

- [ ] **Step 4: Final commit (if any verification fixups were needed)**

```bash
git add -A
git commit -m "test(browser-agent): verify Cloudflare pass end-to-end"
```

---

## Notes / Honest Caveats

- **No silver bullet.** patchright closes the single biggest detection vector (`Runtime.enable`). It does not change the TLS/JA4 fingerprint or IP reputation. For a low-frequency, single-user personal tool this is enough to pass gradcracker-class Cloudflare *most of the time*. A site on Cloudflare *Enterprise* bot management may still block — if `await_cloudflare` reports "did not clear", that is the expected, honest failure mode, and the agent now tells the user instead of looping.
- **patchright can break on Cloudflare updates.** It is a cat-and-mouse patch. If it regresses, the next step (not in this plan) is `camoufox` (patched Firefox) — a larger rewrite because it has a different launcher API.
- **arm64 vs x86_64.** The whole plan is arch-aware via `BROWSER_CHANNEL` + the `ARCH` build-arg. The Pi is arm64 → `chromium`; a typical CI/x86 host → `chrome`.
- **No paid CAPTCHA services.** Per the user's requirement, this is a pure agent browser — no 2captcha/CapSolver.
