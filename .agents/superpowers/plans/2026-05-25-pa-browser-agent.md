# PA Browser Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve the browser chat agent into a persistent PA — shared Chrome profile that stays logged in, `system/pa/` wiki pages the agent maintains across sessions, warm context loaded at the start of every turn, and a context-save turn fired on disconnect.

**Architecture:** Six targeted changes across browser-agent and the API. No new DB models, no new routes (except the context-save logic wired into the existing disconnect route), no UI changes. The PA identity comes entirely from persistent profile + wiki state + prompt instructions.

**Tech Stack:** Python / FastAPI / patchright / litellm / asyncio, Docker Compose named volumes, pytest

---

## File Map

| File | Change |
|---|---|
| `browser-agent/main.py` | Add `_clear_profile_locks()`, use `PA_PROFILE_DIR` for all sessions, never delete the profile dir |
| `browser-agent/Dockerfile` | Add `PA_PROFILE_DIR` env + create dir |
| `docker-compose.yml` | Add `PA_PROFILE_DIR` env + named volume on browser-agent |
| `docker-compose.prod.yml` | Same |
| `api/app/agents/browser_chat_agent.py` | Add `_PA_SEED_SLUGS`, `_load_pa_context()`, inject into `run_turn`, add `run_context_save()` |
| `api/app/routes/browser_chat.py` | Add `import asyncio`; modify `disconnect` to fire `run_context_save` before browser close |
| `api/app/agents/prompts/browser_chat.md` | Add PA identity, memory rules, tone sections |
| `api/app/agents/tools.py` | Add `_is_changelog_excluded()` helper, apply to write_page |
| `api/tests/test_browser_chat_agent.py` | Tests for `_load_pa_context` and `run_context_save` |
| `api/tests/test_browser_chat_routes.py` | Test that disconnect fires context save |

---

## Task 1: Shared persistent Chrome profile in browser-agent

**Files:**
- Modify: `browser-agent/main.py`

- [ ] **Step 1: Add `glob` import, `PA_PROFILE_DIR` constant, and `_clear_profile_locks()` helper**

Add after the existing `import` block (after line 12, before `MINIO_ENDPOINT`):

```python
import glob
```

Add after `S3_BUCKET = os.getenv(...)` and before `_playwright = None`:

```python
PA_PROFILE_DIR = os.getenv("PA_PROFILE_DIR", "/data/pa-profile")


def _clear_profile_locks(profile_dir: str) -> None:
    """Remove Chrome singleton lock files left by a crashed or killed process."""
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"):
        path = os.path.join(profile_dir, name)
        try:
            os.remove(path)
        except OSError:
            pass
    for path in glob.glob(os.path.join(profile_dir, ".com.google.Chrome.*")):
        try:
            os.remove(path)
        except OSError:
            pass
```

- [ ] **Step 2: Update `session_new` to use `PA_PROFILE_DIR`**

Replace the entire `session_new` function (lines 134–147):

```python
@app.post("/session/new")
async def session_new():
    session_id = str(uuid.uuid4())
    video_dir = tempfile.mkdtemp()
    os.makedirs(PA_PROFILE_DIR, exist_ok=True)
    _clear_profile_locks(PA_PROFILE_DIR)
    context, page = await _new_session_objects(video_dir, PA_PROFILE_DIR)
    await _inject_cursor(page)
    _sessions[session_id] = {
        "context": context,
        "page": page,
        "video_dir": video_dir,
        "user_data_dir": PA_PROFILE_DIR,
    }
    return {"session_id": session_id}
```

- [ ] **Step 3: Update `session_recover` to use `PA_PROFILE_DIR`**

Replace the entire `session_recover` function (lines 150–175):

```python
@app.post("/session/{session_id}/recover")
async def session_recover(session_id: str):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    s = _sessions[session_id]

    ctx = s.get("context")
    if ctx is not None:
        try:
            await ctx.close()
        except Exception:
            pass

    video_dir = s.get("video_dir") or tempfile.mkdtemp()
    _clear_profile_locks(PA_PROFILE_DIR)
    context, page = await _new_session_objects(video_dir, PA_PROFILE_DIR)
    await _inject_cursor(page)

    _sessions[session_id] = {
        "context": context,
        "page": page,
        "video_dir": video_dir,
        "user_data_dir": PA_PROFILE_DIR,
    }
    return {"ok": True}
```

- [ ] **Step 4: Update `session_close` — do NOT delete the profile dir**

Replace the `session_close` function (lines 470–498). Remove the `shutil.rmtree(s.get("user_data_dir") ...)` line; keep the `video_dir` cleanup:

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
    shutil.rmtree(s.get("video_dir") or "", ignore_errors=True)
    # Do NOT delete user_data_dir — it is the shared PA profile and must persist.
    return {"recording_url": recording_url}
```

- [ ] **Step 5: Update `lifespan` — do NOT delete the profile dir**

Replace the `lifespan` function (lines 28–40):

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _playwright
    _playwright = await async_playwright().start()
    yield
    for s in list(_sessions.values()):
        try:
            await s["context"].close()
        except Exception:
            pass
        shutil.rmtree(s.get("video_dir") or "", ignore_errors=True)
        # Do NOT remove user_data_dir — it is the shared PA profile.
    await _playwright.stop()
```

- [ ] **Step 6: Commit**

```bash
git add browser-agent/main.py
git commit -m "feat(browser-agent): shared PA profile dir with lock clearing"
```

---

## Task 2: Docker config — Dockerfile and compose volumes

**Files:**
- Modify: `browser-agent/Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `docker-compose.prod.yml`

- [ ] **Step 1: Update `browser-agent/Dockerfile`**

Add two lines after the existing `ENV DISPLAY=:99` line:

```dockerfile
ENV PA_PROFILE_DIR=/data/pa-profile
RUN mkdir -p /data/pa-profile
```

- [ ] **Step 2: Update `docker-compose.yml` browser-agent service**

In the `browser-agent` service, add `PA_PROFILE_DIR` to environment and a volume mount. The full updated service block (replace the existing `browser-agent:` block):

```yaml
  browser-agent:
    build: browser-agent/
    shm_size: '2gb'
    environment:
      - DISPLAY=:99
      - BROWSER_CHANNEL=${BROWSER_CHANNEL:-chrome}
      - MINIO_ENDPOINT=http://minio:9000
      - MINIO_ACCESS_KEY=minioadmin
      - MINIO_SECRET_KEY=minioadmin
      - S3_BUCKET=wiki
      - PA_PROFILE_DIR=/data/pa-profile
    volumes:
      - pa-profile:/data/pa-profile
    ports:
      - "6080:6080"
      - "8001:8001"
    depends_on:
      - minio
    restart: unless-stopped
```

Then add `pa-profile:` to the top-level `volumes:` section (which already exists at the bottom of the file):

```yaml
volumes:
  pgdata:
  minio_data:
  pa-profile:
```

- [ ] **Step 3: Update `docker-compose.prod.yml` browser-agent service**

Add `PA_PROFILE_DIR` to environment and the volume mount to the `browser-agent` service:

```yaml
      - PA_PROFILE_DIR=/data/pa-profile
```

(Add after the `- S3_BUCKET=${S3_BUCKET:-wiki}` line in the environment block.)

Add to the browser-agent service `volumes:` key (create it if absent):

```yaml
    volumes:
      - pa-profile:/data/pa-profile
```

Add to the top-level `volumes:` section (which already exists):

```yaml
volumes:
  pgdata:
  minio_data:
  pa-profile:
```

- [ ] **Step 4: Commit**

```bash
git add browser-agent/Dockerfile docker-compose.yml docker-compose.prod.yml
git commit -m "feat(docker): named pa-profile volume for persistent browser profile"
```

---

## Task 3: PA context loading in `browser_chat_agent.py`

**Files:**
- Modify: `api/app/agents/browser_chat_agent.py`
- Test: `api/tests/test_browser_chat_agent.py`

- [ ] **Step 1: Write failing tests for `_load_pa_context`**

Add to `api/tests/test_browser_chat_agent.py`:

```python
from app.agents.browser_chat_agent import _load_pa_context


@pytest.mark.asyncio
async def test_load_pa_context_seed_pages_read_in_full():
    """system/pa/context, accounts, preferences are always fetched in full."""
    wiki = MagicMock()
    wiki.list_pages = AsyncMock(return_value=[
        {"slug": "system/pa/context", "title": "", "summary": ""},
        {"slug": "system/pa/accounts", "title": "", "summary": ""},
        {"slug": "system/pa/preferences", "title": "", "summary": ""},
    ])
    wiki.read_page = AsyncMock(side_effect=lambda slug: f"content-of-{slug}")

    result = await _load_pa_context(wiki)

    assert "[system/pa/context]" in result
    assert "content-of-system/pa/context" in result
    assert "[system/pa/accounts]" in result
    assert "content-of-system/pa/accounts" in result
    assert "[system/pa/preferences]" in result
    assert "content-of-system/pa/preferences" in result
    assert wiki.read_page.await_count == 3


@pytest.mark.asyncio
async def test_load_pa_context_domain_pages_listed_by_slug_not_read():
    """Domain pages beyond the seed set are listed by name only, not fetched."""
    wiki = MagicMock()
    wiki.list_pages = AsyncMock(return_value=[
        {"slug": "system/pa/context", "title": "", "summary": ""},
        {"slug": "system/pa/job-search", "title": "", "summary": ""},
    ])
    wiki.read_page = AsyncMock(side_effect=lambda slug: f"content-of-{slug}")

    result = await _load_pa_context(wiki)

    assert "system/pa/job-search" in result
    assert "content-of-system/pa/job-search" not in result
    # Only the seed page (context) was read in full
    assert wiki.read_page.await_count == 1


@pytest.mark.asyncio
async def test_load_pa_context_missing_seed_pages_skipped():
    """Seed pages that don't exist yet are not fetched and not mentioned."""
    wiki = MagicMock()
    wiki.list_pages = AsyncMock(return_value=[])
    wiki.read_page = AsyncMock()

    result = await _load_pa_context(wiki)

    assert "<pa_context>" in result
    assert "Current datetime:" in result
    wiki.read_page.assert_not_awaited()


@pytest.mark.asyncio
async def test_load_pa_context_includes_datetime_string():
    """The pa_context block includes an ISO-8601 datetime."""
    import re
    wiki = MagicMock()
    wiki.list_pages = AsyncMock(return_value=[])
    wiki.read_page = AsyncMock()

    result = await _load_pa_context(wiki)

    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", result)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd api && python -m pytest tests/test_browser_chat_agent.py::test_load_pa_context_seed_pages_read_in_full -v
```

Expected: `ImportError` — `_load_pa_context` does not exist yet.

- [ ] **Step 3: Implement `_load_pa_context` and inject into `run_turn`**

Add after `_log = structlog.get_logger()` in `browser_chat_agent.py`:

```python
from datetime import datetime as _dt

_PA_SEED_SLUGS = ("system/pa/context", "system/pa/accounts", "system/pa/preferences")


async def _load_pa_context(wiki_tools: AgentTools) -> str:
    """Build a <pa_context> block from system/pa/* wiki pages.

    Seed pages are always read in full. Domain pages (everything else under
    system/pa/) are listed by slug only — the agent fetches them on demand
    with read_page when relevant to the current task.
    """
    now = _dt.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    all_pages = await wiki_tools.list_pages()
    pa_slugs = {p["slug"] for p in all_pages if p["slug"].startswith("system/pa/")}

    lines: list[str] = ["<pa_context>", f"Current datetime: {now}", ""]

    for slug in _PA_SEED_SLUGS:
        if slug in pa_slugs:
            content = await wiki_tools.read_page(slug)
            lines += [f"[{slug}]", content, ""]

    domain_slugs = sorted(s for s in pa_slugs if s not in set(_PA_SEED_SLUGS))
    if domain_slugs:
        lines.append(
            "Additional domain pages (fetch with read_page if relevant to current task):"
        )
        for slug in domain_slugs:
            lines.append(f"- {slug}")
        lines.append("")

    lines.append("</pa_context>")
    return "\n".join(lines)
```

Then in `run_turn`, replace the system message block (currently lines 85–88):

```python
        pa_context = await _load_pa_context(wiki_tools)

        system_msg = {
            "role": "system",
            "content": render_system_prompt(SYSTEM_PROMPT, model=settings.litellm_model)
            + "\n\n"
            + pa_context,
        }
        messages = [system_msg] + conversation_history
```

- [ ] **Step 4: Run the new tests**

```bash
cd api && python -m pytest tests/test_browser_chat_agent.py -k "load_pa_context" -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Run the full agent test suite to check for regressions**

```bash
cd api && make test-local
```

Expected: all existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add api/app/agents/browser_chat_agent.py api/tests/test_browser_chat_agent.py
git commit -m "feat(pa): load system/pa/* context into browser chat agent on every turn"
```

---

## Task 4: Exclude `system/pa/` pages from the wiki changelog

**Files:**
- Modify: `api/app/agents/tools.py`
- Test: `api/tests/test_tools_read_write.py`

- [ ] **Step 1: Write a failing test**

Add to `api/tests/test_tools_read_write.py`:

```python
from app.agents.tools import _is_changelog_excluded


def test_is_changelog_excluded_returns_true_for_pa_pages():
    assert _is_changelog_excluded("system/pa/context") is True
    assert _is_changelog_excluded("system/pa/accounts") is True
    assert _is_changelog_excluded("system/pa/job-search") is True


def test_is_changelog_excluded_returns_false_for_regular_pages():
    assert _is_changelog_excluded("projects/alpha") is False
    assert _is_changelog_excluded("system/memory") is False
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd api && python -m pytest tests/test_tools_read_write.py::test_is_changelog_excluded_returns_true_for_pa_pages -v
```

Expected: `ImportError` — `_is_changelog_excluded` does not exist yet.

- [ ] **Step 3: Implement `_is_changelog_excluded` and wire it in**

Add after `_CHANGELOG_EXCLUDED` in `tools.py`:

```python
def _is_changelog_excluded(slug: str) -> bool:
    return slug in _CHANGELOG_EXCLUDED or slug.startswith("system/pa/")
```

Then on line 163, replace:

```python
        if not self._suppress_changelog and slug not in _CHANGELOG_EXCLUDED:
```

with:

```python
        if not self._suppress_changelog and not _is_changelog_excluded(slug):
```

- [ ] **Step 4: Run the tests**

```bash
cd api && python -m pytest tests/test_tools_read_write.py -k "changelog_excluded" -v
```

Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/agents/tools.py api/tests/test_tools_read_write.py
git commit -m "feat(pa): exclude system/pa/* from wiki changelog"
```

---

## Task 5: `run_context_save` + disconnect intercept

**Files:**
- Modify: `api/app/agents/browser_chat_agent.py`
- Modify: `api/app/routes/browser_chat.py`
- Test: `api/tests/test_browser_chat_agent.py`
- Test: `api/tests/test_browser_chat_routes.py`

- [ ] **Step 1: Write failing tests for `run_context_save`**

Add to `api/tests/test_browser_chat_agent.py`:

```python
from app.agents.browser_chat_agent import run_context_save


@pytest.mark.asyncio
async def test_run_context_save_completes_without_error_when_llm_returns_no_tool_calls(patch_broadcaster):
    """run_context_save exits cleanly when the LLM responds with no tool calls."""
    from unittest.mock import patch as upatch

    no_tool_msg = MagicMock()
    no_tool_msg.tool_calls = []
    no_tool_msg.content = "Context saved."
    no_tool_resp = MagicMock()
    no_tool_resp.choices = [MagicMock(message=no_tool_msg)]

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
    )
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with upatch("litellm.acompletion", new=AsyncMock(return_value=no_tool_resp)), \
         upatch("app.agents.browser_chat_agent.AsyncSessionLocal", return_value=mock_db):
        await run_context_save(workspace_id="ws-1", audience_user_id="u1")


@pytest.mark.asyncio
async def test_run_context_save_swallows_llm_exceptions(patch_broadcaster):
    """run_context_save does not raise even if litellm throws."""
    from unittest.mock import patch as upatch

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
    )
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with upatch("litellm.acompletion", new=AsyncMock(side_effect=Exception("LLM error"))), \
         upatch("app.agents.browser_chat_agent.AsyncSessionLocal", return_value=mock_db):
        await run_context_save(workspace_id="ws-1", audience_user_id="u1")
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd api && python -m pytest tests/test_browser_chat_agent.py::test_run_context_save_completes_without_error_when_llm_returns_no_tool_calls -v
```

Expected: `ImportError` — `run_context_save` does not exist yet.

- [ ] **Step 3: Implement `run_context_save` in `browser_chat_agent.py`**

First add this import at the top of `browser_chat_agent.py` (alongside the other app imports):

```python
from app.database import AsyncSessionLocal
```

Then add after the `run_turn` function:

```python
async def run_context_save(
    workspace_id: str,
    audience_user_id: str,
) -> None:
    """Fire a silent agent turn that writes the session summary to system/pa/context.

    Called on disconnect before the browser is torn down. Uses only wiki tools
    (no browser). Never raises — failures are logged and swallowed.

    Creates its own DB session to avoid sharing the route's transaction —
    wiki tool commits must not leave the caller's session in an aborted state.
    """
    try:
        async with AsyncSessionLocal() as db_session:
            wiki_tools = AgentTools(
                session=db_session,
                workspace_id=workspace_id,
                broadcaster=None,
                context="browser_chat",
                audience_user_id=audience_user_id,
            )
            tool_defs = wiki_tools.as_litellm_tools(allowed=WIKI_TOOLS)
            pa_context = await _load_pa_context(wiki_tools)

            messages: list[dict] = [
                {
                    "role": "system",
                    "content": render_system_prompt(SYSTEM_PROMPT, model=settings.litellm_model)
                    + "\n\n"
                    + pa_context,
                },
                {
                    "role": "user",
                    "content": (
                        "[System: The user has disconnected. "
                        "Write a concise summary of this session to system/pa/context immediately — "
                        "what was accomplished, what is in progress, any loose ends. "
                        "Use write_page or patch_page. Then stop.]"
                    ),
                },
            ]

            for _ in range(5):
                resp = await litellm.acompletion(
                    model=settings.litellm_model,
                    messages=messages,
                    tools=tool_defs,
                    tool_choice="auto",
                )
                msg = resp.choices[0].message
                tool_calls = getattr(msg, "tool_calls", None) or []
                messages.append(assistant_message_for_litellm(msg))

                if not tool_calls:
                    break

                tool_results = []
                for tc in tool_calls:
                    name = tc.function.name
                    args = json.loads(tc.function.arguments or "{}")
                    try:
                        result_str = await wiki_tools.dispatch(name, args)
                    except Exception as exc:
                        result_str = f"Error: {exc}"
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": str(result_str),
                    })
                messages.extend(tool_results)

    except Exception:
        _log.warning("pa_context_save_failed", workspace_id=workspace_id)
```

- [ ] **Step 4: Run the `run_context_save` tests**

```bash
cd api && python -m pytest tests/test_browser_chat_agent.py -k "context_save" -v
```

Expected: both tests PASS.

- [ ] **Step 5: Write the failing route test**

Add to `api/tests/test_browser_chat_routes.py`:

```python
def test_disconnect_calls_context_save_before_browser_close(client):
    """run_context_save is awaited before the browser session close call."""
    mock_ws = _make_ws()
    sess = _make_session()

    session = MagicMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=sess))
    )
    session.commit = AsyncMock()

    call_order: list[str] = []

    async def fake_context_save(**kwargs):
        call_order.append("context_save")

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch("app.routes.browser_chat._ensure_workspace", new_callable=AsyncMock, return_value=mock_ws), \
             patch("app.agents.browser_chat_agent.run_context_save", new=AsyncMock(side_effect=fake_context_save)), \
             patch("httpx.AsyncClient") as mock_http_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)

            async def fake_browser_close(url, **kwargs):
                call_order.append("browser_close")
                m = MagicMock()
                m.raise_for_status = MagicMock()
                return m

            mock_http.post = AsyncMock(side_effect=fake_browser_close)
            mock_http_cls.return_value = mock_http

            r = client.post("/browser-chat/sessions/sess-1/disconnect")
            assert r.status_code == 200
            assert "context_save" in call_order
            assert "browser_close" in call_order
            assert call_order.index("context_save") < call_order.index("browser_close")
    finally:
        app.dependency_overrides.pop(get_db, None)
```

- [ ] **Step 6: Run to confirm it fails**

```bash
cd api && python -m pytest tests/test_browser_chat_routes.py::test_disconnect_calls_context_save_before_browser_close -v
```

Expected: FAIL — `run_context_save` is not imported or called in the disconnect route yet.

- [ ] **Step 7: Modify the `disconnect` route in `browser_chat.py`**

Add `import asyncio` to the imports at the top of `browser_chat.py` (after `from datetime import datetime`):

```python
import asyncio
```

Replace the entire `disconnect` route function:

```python
@router.post("/sessions/{session_id}/disconnect", status_code=200)
async def disconnect(
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

    if sess.browser_session_id:
        from app.agents.browser_chat_agent import run_context_save
        try:
            await asyncio.wait_for(
                run_context_save(
                    workspace_id=ws.id,
                    audience_user_id=user,
                ),
                timeout=30.0,
            )
        except (asyncio.TimeoutError, Exception):
            _log.warning("pa_context_save_timeout", session_id=session_id)

        async with httpx.AsyncClient(base_url=settings.browser_agent_url, timeout=10.0) as http:
            try:
                await http.post(f"/session/{sess.browser_session_id}/close")
            except Exception:
                pass

    sess.status = "completed"
    sess.completed_at = datetime.utcnow()
    await db.commit()
    _log.info("browser_chat_disconnected", session_id=session_id)
    return {"ok": True}
```

- [ ] **Step 8: Run the route test**

```bash
cd api && python -m pytest tests/test_browser_chat_routes.py::test_disconnect_calls_context_save_before_browser_close -v
```

Expected: PASS.

- [ ] **Step 9: Run full test suite**

```bash
cd api && make test-local
```

Expected: all tests pass.

- [ ] **Step 10: Commit**

```bash
git add api/app/agents/browser_chat_agent.py api/app/routes/browser_chat.py api/tests/test_browser_chat_agent.py api/tests/test_browser_chat_routes.py
git commit -m "feat(pa): run_context_save on disconnect — PA writes session summary before browser closes"
```

---

## Task 6: System prompt — PA identity, memory rules, tone

**Files:**
- Modify: `api/app/agents/prompts/browser_chat.md`

- [ ] **Step 1: Prepend the PA identity section to `browser_chat.md`**

Replace the entire contents of `api/app/agents/prompts/browser_chat.md` with:

```markdown
## Your identity

You are a persistent personal assistant with access to a real web browser. You maintain memory across sessions via wiki pages under `system/pa/`. You are not a fresh agent — you have history with this user. Your PA context is injected at the bottom of this prompt each session.

## PA memory rules

- **On session start:** Read the `<pa_context>` block injected below. Greet the user with genuine continuity — reference what's most relevant, not everything. If no PA pages exist yet, introduce yourself and create `system/pa/context`, `system/pa/accounts`, and `system/pa/preferences` with placeholder content before responding.
- **Accounts:** Update `system/pa/accounts` immediately when you successfully log into a site. Record: URL, login method/auth strategy (e.g. "OAuth via Google", "password + SMS 2FA", "SSO via GitHub"), and today's date as `Last verified`. If you hit an auth failure on a known account, check when it was last verified — ask the user for help rather than retrying blindly.
- **Preferences:** Update `system/pa/preferences` immediately when the user tells you how they like something done, or when you clearly infer a standing preference from their behaviour.
- **Context:** Before this session ends (user disconnects or you finish a task), update `system/pa/context` with: what was accomplished, what is in progress, what the next steps are. Write today's date as `Last updated:` at the top of the page.
- **Domain pages:** Create new pages under `system/pa/` freely as your work expands into new areas (e.g. `system/pa/job-search`, `system/pa/finances`). Use `read_page` to fetch them when they are relevant to the current task.

## Tone

You know this user. Act like it. Open with what matters from last time. Anticipate needs. Keep it brief — the user can see the browser.

---

You are a browser assistant. The user will give you tasks to carry out in a real web browser. You have full control of the browser — navigate, click, type, read, screenshot.

You also have wiki tools to save useful findings to the user's knowledge base.

## Workflow

1. Read the user's message and decide what to do.
2. Call `browser_get_page_state` after navigating to see what interactive elements are available.
3. Execute the task using browser tools.
4. When done, reply in chat with a concise summary of what you did.

## Tool reference

| Tool | When to use |
|------|-------------|
| `browser_navigate(url)` | Go to a URL |
| `browser_get_page_state()` | Get URL, title, and interactive elements with selectors |
| `browser_click(selector?, text?)` | Click by CSS selector or visible text |
| `browser_type(text)` | Type into the focused element |
| `browser_press_key(key)` | Press Enter, Tab, Escape, arrow keys, etc. |
| `browser_focus(selector)` | Focus a specific input before typing |
| `browser_hover(selector)` | Hover to reveal dropdowns or tooltips |
| `browser_select_option(selector, value)` | Select from a `<select>` dropdown |
| `browser_scroll(direction, amount?)` | Scroll up or down |
| `browser_click_at(x, y)` | Click at pixel coordinates — use for iframes and CAPTCHA checkboxes |
| `browser_mouse_move(x, y)` | Move cursor without clicking — approach target before browser_click_at |
| `browser_await_cloudflare()` | Wait for a Cloudflare "Verify you are human" challenge to clear — call once, never loop |
| `browser_wait_for(selector?, text?, timeout?)` | Wait for element or text to appear |
| `browser_read()` | Extract all visible text from the page |
| `browser_execute_js(script)` | Run JavaScript — escape hatch |
| `browser_screenshot()` | Take a screenshot to see the current browser view |

## Guidelines

- After each navigation, call `browser_get_page_state` before deciding what to click.
- Use `browser_click(text="Sign in")` when you know the button label — it's more reliable than guessing a selector.
- After form submissions, call `browser_wait_for` before continuing.
- If you get stuck, take a `browser_screenshot` to see what is on screen.
- Keep wiki page slugs lowercase with hyphens, e.g. `research/topic-name`.
- If the system tells you the user has interacted with the browser, call `browser_screenshot` to see the updated state before continuing.
- Reply concisely — the user can see the browser, so focus on what you did and what you found.

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

- [ ] **Step 2: Run the prompt-loading test to verify the file is valid**

```bash
cd api && python -m pytest tests/test_prompts.py -v
```

Expected: all pass — the test just checks prompts load without error.

- [ ] **Step 3: Commit**

```bash
git add api/app/agents/prompts/browser_chat.md
git commit -m "feat(pa): PA identity, memory rules, and tone in browser_chat system prompt"
```

---

## Self-Review Checklist

- [x] **Profile lock clearing** — `_clear_profile_locks()` called in both `session_new` and `session_recover` before `launch_persistent_context`. ✓
- [x] **Profile not deleted** — `session_close` and `lifespan` both have `user_data_dir` cleanup removed. ✓
- [x] **Seed page lazy-load** — `_load_pa_context` always reads 3 seeds in full; domain pages are names only. ✓
- [x] **Datetime injection** — `_dt.utcnow()` injected into every `<pa_context>` block. ✓
- [x] **run_context_save is silent** — `broadcaster=None`, no SSE events, exceptions swallowed with a log warning. ✓
- [x] **run_context_save owns its own DB session** — uses `AsyncSessionLocal()` internally so wiki tool commits cannot abort the disconnect route's transaction. ✓
- [x] **Disconnect order** — `run_context_save` awaited inside `asyncio.wait_for(timeout=30)`, then browser close, then DB commit. ✓
- [x] **Changelog exclusion** — `_is_changelog_excluded` covers exact matches (`_CHANGELOG_EXCLUDED`) plus `system/pa/` prefix. ✓
- [x] **No type inconsistencies** — `_load_pa_context` used in both `run_turn` and `run_context_save` with the same `AgentTools` arg. ✓
- [x] **No placeholders** — all code blocks are complete and runnable. ✓
