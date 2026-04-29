# Wiki Folders, Index & Health Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add folder organisation (slug-as-path), an auto-maintained `meta/index` page, and a wiki-health agent that fixes and reports wiki issues.

**Architecture:** Slugs become full paths (`people/alice-jones`); `meta/index` is a regular wiki page updated incrementally after every agent write; a new `HealthAgent` fixes broken links, regenerates the index, and writes `meta/health-report`; the UI sidebar becomes a collapsible folder tree.

**Tech Stack:** FastAPI, SQLAlchemy async, LiteLLM/Gemini, React 18 + TypeScript, localStorage

---

## File Map

| File | Change |
|------|--------|
| `api/app/routes/wiki.py` | Change `{slug}` → `{slug:path}` on GET, PUT, DELETE routes |
| `api/app/agents/tools.py` | Add `update_index()` method; call it from `write_page()` |
| `api/app/agents/ingest_agent.py` | Update both system prompts with folder taxonomy + full-path slug instruction |
| `api/app/agents/query_agent.py` | Update system prompt to read `meta/index` first |
| `api/app/agents/health_agent.py` | **New** — fix-and-report health agent |
| `api/app/routes/health.py` | **New** — `POST /run` route (prefix `/health`) |
| `api/app/main.py` | Register health router |
| `api/app/routes/ingest.py` | Add auto-trigger: fire health agent after every N ingests |
| `frontend/src/components/WikiPanel.tsx` | Replace flat list with collapsible folder tree + health button |
| `frontend/src/api/client.ts` | Add `runHealthCheck()` |
| `tests/test_wiki.py` | Add folder-slug tests |
| `tests/test_health.py` | **New** — health route smoke tests |

---

## Task 1: Allow `/` in Slug Path Params

Slugs like `people/alice-jones` contain `/` — FastAPI's default `{slug}` path param stops at the first `/`. Fix: use `{slug:path}`.

**Files:**
- Modify: `api/app/routes/wiki.py`
- Modify: `tests/test_wiki.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_wiki.py`:

```python
@pytest.mark.asyncio
async def test_folder_slug_create_and_get():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _token(client)
        headers = {"Authorization": f"Bearer {token}"}

        create = await client.post(
            "/wiki/pages",
            json={
                "slug": "people/alice-jones",
                "title": "Alice Jones",
                "body_md": "# Alice Jones\n\nFounder.",
                "summary": "Co-founder of Acme Corp",
            },
            headers=headers,
        )
        assert create.status_code == 201

        get = await client.get("/wiki/pages/people/alice-jones", headers=headers)
        assert get.status_code == 200
        assert get.json()["slug"] == "people/alice-jones"

        update = await client.put(
            "/wiki/pages/people/alice-jones",
            json={"summary": "Updated summary"},
            headers=headers,
        )
        assert update.status_code == 200

        delete = await client.delete(
            "/wiki/pages/people/alice-jones", headers=headers
        )
        assert delete.status_code == 204
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose run --rm api pytest tests/test_wiki.py::test_folder_slug_create_and_get -v
```

Expected: FAIL — 404 on GET because `/people/alice-jones` is not matched by `{slug}`.

- [ ] **Step 3: Update route path params in `api/app/routes/wiki.py`**

Change the three affected route decorators and their function signatures. Find these three functions and update them:

```python
# BEFORE
@router.get("/pages/{slug}", response_model=PageOut)
async def get_page(slug: str, ...):

@router.put("/pages/{slug}", response_model=PageOut)
async def update_page(slug: str, ...):

@router.delete("/pages/{slug}", status_code=204)
async def delete_page(slug: str, ...):

# AFTER
@router.get("/pages/{slug:path}", response_model=PageOut)
async def get_page(slug: str, ...):

@router.put("/pages/{slug:path}", response_model=PageOut)
async def update_page(slug: str, body: PageUpdate, ...):

@router.delete("/pages/{slug:path}", status_code=204)
async def delete_page(slug: str, ...):
```

The function signatures don't change — only the route decorator strings.

- [ ] **Step 4: Run test to verify it passes**

```bash
docker compose run --rm api pytest tests/test_wiki.py::test_folder_slug_create_and_get -v
```

Expected: PASS

- [ ] **Step 5: Run full wiki test suite**

```bash
docker compose run --rm api pytest tests/test_wiki.py -v
```

Expected: all existing tests still PASS (flat slugs like `test-page` still work with `{slug:path}`).

- [ ] **Step 6: Commit**

```bash
git add api/app/routes/wiki.py tests/test_wiki.py
git commit -m "feat: support folder slugs (slug:path) in wiki routes"
```

---

## Task 2: `meta/index` Incremental Updates in AgentTools

After every `write_page` / `create_page` call, the agent patches `meta/index` — adding or updating the entry for the written page in the correct folder section. Guard: skip if writing `meta/index` itself (prevents infinite recursion).

**Files:**
- Modify: `api/app/agents/tools.py`
- Modify: `tests/test_agents.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agents.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.agents.tools import AgentTools


@pytest.mark.asyncio
async def test_write_page_updates_meta_index(db_session, workspace_id):
    """After writing a page, meta/index should contain an entry for it."""
    tools = AgentTools(
        session=db_session,
        workspace_id=workspace_id,
        broadcaster=None,
    )

    await tools.write_page(
        slug="people/alice-jones",
        body_md="# Alice Jones\n\nFounder.",
        summary="Co-founder of Acme Corp",
        title="Alice Jones",
    )

    index_content = await tools.read_page("meta/index")
    assert "[[people/alice-jones]]" in index_content
    assert "Co-founder of Acme Corp" in index_content


@pytest.mark.asyncio
async def test_write_meta_index_does_not_recurse(db_session, workspace_id):
    """Writing meta/index itself must not trigger another index update."""
    tools = AgentTools(
        session=db_session,
        workspace_id=workspace_id,
        broadcaster=None,
    )
    # Should complete without RecursionError
    await tools.write_page(
        slug="meta/index",
        body_md="# Wiki Index\n",
        summary="Index",
        title="Index",
    )
    # meta/index exists and was NOT re-patched (content stays as written)
    content = await tools.read_page("meta/index")
    assert content == "# Wiki Index\n"
```

Check if `tests/test_agents.py` has a `db_session` and `workspace_id` fixture — look in `tests/conftest.py` and reuse them. If they don't exist for the agents test file, check what fixtures `test_wiki.py` uses; the agents tests may need the same conftest setup.

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose run --rm api pytest tests/test_agents.py::test_write_page_updates_meta_index -v
```

Expected: FAIL — `meta/index` not found after writing a page.

- [ ] **Step 3: Add `update_index` to `AgentTools` in `api/app/agents/tools.py`**

Add this import at the top of the file:

```python
import re
```

Add this method to the `AgentTools` class, after `create_page` and before `list_source_pages`:

```python
async def update_index(self, slug: str, title: str, summary: str) -> None:
    """Patch meta/index with the entry for the given page. No-op for meta/index itself."""
    if slug == "meta/index":
        return

    folder = (slug.rsplit("/", 1)[0] + "/") if "/" in slug else "misc/"
    entry_line = f"- [[{slug}]] — {summary or title}"

    raw = await self.read_page("meta/index")
    if raw.startswith("[Page 'meta/index' not found]"):
        raw = "# Wiki Index\n\n"

    # Parse existing sections into dict[folder_header -> list[entry_line]]
    sections: dict[str, list[str]] = {}
    current_folder: str | None = None
    preamble: list[str] = []
    in_preamble = True

    for line in raw.split("\n"):
        m = re.match(r"^## (.+?)\s*\(\d+ pages?\)$", line)
        if m:
            in_preamble = False
            current_folder = m.group(1)
            if current_folder not in sections:
                sections[current_folder] = []
        elif in_preamble:
            preamble.append(line)
        elif current_folder is not None and line.startswith("- [["):
            sections[current_folder].append(line)

    # Update or add entry for this slug
    if folder not in sections:
        sections[folder] = []
    sections[folder] = sorted(
        [e for e in sections[folder] if not e.startswith(f"- [[{slug}]]")]
        + [entry_line]
    )

    # Rebuild body — meta/ section always last
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    lines: list[str] = [f"# Wiki Index", "", f"_Last updated: {date_str}_", ""]
    for f in sorted(sections.keys(), key=lambda x: (x == "meta/", x)):
        lines.append(f"## {f} ({len(sections[f])} pages)")
        lines.extend(sections[f])
        lines.append("")

    await self.write_page(
        "meta/index",
        "\n".join(lines),
        summary="Wiki table of contents",
        title="Index",
    )
```

- [ ] **Step 4: Call `update_index` from `write_page` after `session.commit()`**

In `write_page`, add the call at the very end, before the `return` statement:

```python
    await self.session.commit()
    await self.update_index(slug, title or slug.replace("-", " ").title(), summary)
    return f"Page '{slug}' saved."
```

The full end of `write_page` should look like:

```python
        await self.session.commit()
    await self.update_index(slug, title or slug.replace("-", " ").title(), summary)
    return f"Page '{slug}' saved."
```

- [ ] **Step 5: Run the new tests**

```bash
docker compose run --rm api pytest tests/test_agents.py::test_write_page_updates_meta_index tests/test_agents.py::test_write_meta_index_does_not_recurse -v
```

Expected: both PASS

- [ ] **Step 6: Run full test suite**

```bash
docker compose run --rm api pytest tests/ -v
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add api/app/agents/tools.py tests/test_agents.py
git commit -m "feat: auto-update meta/index after every agent write_page"
```

---

## Task 3: Update Agent System Prompts with Folder Taxonomy

Ingest and query agents must know to use full-path slugs and the top-level folder taxonomy.

**Files:**
- Modify: `api/app/agents/ingest_agent.py`
- Modify: `api/app/agents/query_agent.py`

- [ ] **Step 1: Update `SYSTEM_PROMPT_SMALL` in `api/app/agents/ingest_agent.py`**

Replace the existing `SYSTEM_PROMPT_SMALL` constant with:

```python
SYSTEM_PROMPT_SMALL = """You are an agent that maintains a personal knowledge wiki.
You have been given a source document split into pages. Integrate its knowledge into the wiki.

IMPORTANT — Slug conventions:
- Every page MUST have a folder prefix. Always use full-path slugs: people/alice-jones, concepts/knowledge-management.
- Top-level folders: people/ (individuals), concepts/ (ideas/frameworks), projects/ (ongoing work),
  sources/ (per-source summaries), meta/ (system pages — do not write here).
- Use sub-folders freely within these: people/investors/alice-jones is fine.
- Wikilinks must use the full path: [[people/alice-jones]], NOT [[alice-jones]].

Process:
1. Call read_page("meta/index") to see the current wiki structure.
2. Call list_source_pages() to see the document structure and previews.
3. Read pages with read_source_page(). Read all pages — they are manageable in size.
4. Call search_pages() to find related wiki pages before writing.
5. Write changes using write_page() or create_page(). Prefer updating existing pages.
6. When done, stop calling tools.

Write clear markdown. Use [[full/path/wikilinks]] to link related pages."""
```

- [ ] **Step 2: Update `SYSTEM_PROMPT_LARGE` in `api/app/agents/ingest_agent.py`**

Replace the existing `SYSTEM_PROMPT_LARGE` constant with:

```python
SYSTEM_PROMPT_LARGE = """You are an agent that maintains a personal knowledge wiki.
You have been given a large source document split into pages. Integrate its knowledge into the wiki.

IMPORTANT — Slug conventions:
- Every page MUST have a folder prefix. Always use full-path slugs: people/alice-jones, concepts/knowledge-management.
- Top-level folders: people/ (individuals), concepts/ (ideas/frameworks), projects/ (ongoing work),
  sources/ (per-source summaries), meta/ (system pages — do not write here).
- Use sub-folders freely within these: people/investors/alice-jones is fine.
- Wikilinks must use the full path: [[people/alice-jones]], NOT [[alice-jones]].

Process:
1. Call read_page("meta/index") to see the current wiki structure.
2. Call list_source_pages() to see the full document structure with previews.
3. Call spawn_page_reader() MULTIPLE TIMES IN THE SAME RESPONSE to read sections concurrently.
   Each call assigns a page range to a sub-agent that reads and summarises it.
   Group related pages together. Use focus_hint to guide each sub-agent.
4. After receiving all summaries, integrate knowledge into the wiki:
   - Call search_pages() to find related pages.
   - Write changes using write_page() or create_page(). Prefer updating existing pages.
5. When done, stop calling tools.

Write clear markdown. Use [[full/path/wikilinks]] to link related pages."""
```

- [ ] **Step 3: Update `SYSTEM_PROMPT` in `api/app/agents/query_agent.py`**

Replace the existing `SYSTEM_PROMPT` constant with:

```python
SYSTEM_PROMPT = """You are a knowledgeable assistant with access to the user's personal wiki.
When answering questions:
1. Call read_page("meta/index") first to see the full wiki structure and find relevant pages.
2. Use search_pages() to narrow down if needed.
3. Use read_page() to read up to 5 of the most relevant pages in full.
4. Answer based on what you find. Cite pages using their full slug: [[people/alice-jones]].
5. If the wiki doesn't contain the answer, say so clearly.
You may only read pages — do not write or create anything."""
```

- [ ] **Step 4: Commit**

```bash
git add api/app/agents/ingest_agent.py api/app/agents/query_agent.py
git commit -m "feat: folder taxonomy and full-path slug instructions in agent prompts"
```

---

## Task 4: Health Agent

A new `HealthAgent` that: regenerates `meta/index` from scratch, fixes broken wikilinks, adds missing cross-references, flags orphan pages, and writes `meta/health-report`.

**Files:**
- Create: `api/app/agents/health_agent.py`
- Create: `tests/test_health_agent.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_health_agent.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch

from app.agents.health_agent import run


@pytest.mark.asyncio
async def test_health_run_writes_report(db_session, workspace_id):
    """Running the health agent should create meta/health-report."""
    from app.agents.tools import AgentTools

    # Create some pages first
    tools = AgentTools(session=db_session, workspace_id=workspace_id, broadcaster=None)
    await tools.write_page("people/alice", "# Alice\n\n[[concepts/missing-page]]", "A person", "Alice")
    await tools.write_page("concepts/knowledge", "# Knowledge\n\n", "Knowledge page", "Knowledge")

    # Run health agent (with LLM mocked to avoid real API calls)
    with patch("app.agents.health_agent.litellm.acompletion") as mock_llm:
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.content = "Health check complete."
        mock_llm.return_value = mock_response

        await run(workspace_id=workspace_id)

    # meta/health-report should now exist
    report = await tools.read_page("meta/health-report")
    assert not report.startswith("[Page 'meta/health-report' not found]")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose run --rm api pytest tests/test_health_agent.py::test_health_run_writes_report -v
```

Expected: FAIL — `ImportError` or `ModuleNotFoundError` for `health_agent`.

- [ ] **Step 3: Create `api/app/agents/health_agent.py`**

```python
import json
from datetime import datetime

import litellm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.assistant_message import assistant_message_for_litellm
from app.agents.tools import AgentTools
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Page, PageLink
from app.sse import broadcaster

COST_CEILING_USD = 2.0

SYSTEM_PROMPT = """You are a wiki health agent. Your job is to fix and report issues in the wiki.

Run these steps in order:

1. Call list_pages() to get all pages.
2. Call read_page("meta/index") to load the current index.
3. Regenerate meta/index from scratch using write_page("meta/index", ...) with all pages grouped
   by folder (slug prefix). Format:
     ## people/ (N pages)
     - [[people/alice]] — one-line summary
4. For each page (sample up to 20 if large wiki):
   a. Call read_page(slug) to read its content.
   b. Find [[wikilinks]] that reference slugs not in the page list — these are broken links.
   c. If you can identify the correct target page, fix the link with write_page().
   d. Find plain-text mentions of other page titles/slugs not wrapped in [[]] — add wikilinks.
5. Identify orphan pages: pages that appear in list_pages() but are not linked from any other page.
   Do NOT delete them — just note them.
6. Write meta/health-report with two sections:
   ## Fixed
   - list every patch made (what was broken, what you changed)
   ## Needs attention
   - orphan pages with suggested actions
   - broken links you could not resolve
   - any contradictions or gaps you noticed

Be thorough but do not invent facts. Only fix what you are confident about."""


async def run(workspace_id: str) -> None:
    async with AsyncSessionLocal() as session:
        tools = AgentTools(
            session=session,
            workspace_id=workspace_id,
            broadcaster=broadcaster,
        )

        tool_names = ["list_pages", "search_pages", "read_page", "write_page", "create_page"]
        tool_defs = tools.as_litellm_tools(allowed=tool_names)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Run a full health check on the wiki. Fix what you can, then write meta/health-report."},
        ]

        total_cost = 0.0

        for _ in range(40):
            resp = await litellm.acompletion(
                model=settings.litellm_model,
                messages=messages,
                tools=tool_defs,
                tool_choice="auto",
            )
            total_cost += litellm.completion_cost(resp) or 0.0
            if total_cost > COST_CEILING_USD:
                await tools.write_page(
                    "meta/health-report",
                    f"# Health Report\n\n_Run: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} | STOPPED: cost ceiling reached_\n\nPartial results above.\n",
                    summary="Health check results",
                    title="Health Report",
                )
                break

            msg = resp.choices[0].message
            messages.append(assistant_message_for_litellm(msg))

            if not msg.tool_calls:
                break

            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments or "{}")
                result_str = await tools.dispatch(name, args)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

        await broadcaster.publish({"event": "health:done"})
```

- [ ] **Step 4: Run the test**

```bash
docker compose run --rm api pytest tests/test_health_agent.py::test_health_run_writes_report -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/agents/health_agent.py tests/test_health_agent.py
git commit -m "feat: health agent — fix and report wiki issues"
```

---

## Task 5: Health Route + Auto-Trigger

`POST /health/run` fires the health agent as a background task. Ingest route auto-triggers after every N ingests (counted by Source rows).

**Files:**
- Create: `api/app/routes/health.py`
- Modify: `api/app/main.py`
- Modify: `api/app/routes/ingest.py`
- Create: `tests/test_health.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_health.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


async def _token(client: AsyncClient) -> str:
    resp = await client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "changeme"},
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_health_run_returns_202():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _token(client)
        resp = await client.post(
            "/health/run",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202
        assert resp.json() == {"status": "health check started"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose run --rm api pytest tests/test_health.py::test_health_run_returns_202 -v
```

Expected: FAIL — 404, route not registered yet.

- [ ] **Step 3: Create `api/app/routes/health.py`**

```python
from fastapi import APIRouter, BackgroundTasks, Depends

from app.auth import get_current_user
from app.routes.wiki import _ensure_workspace
from app.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/health", tags=["health"])

HEALTH_TRIGGER_EVERY_N = 10


@router.post("/run", status_code=202)
async def run_health_check(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    from app.agents import health_agent

    ws = await _ensure_workspace(db, user)
    background_tasks.add_task(health_agent.run, ws.id)
    return {"status": "health check started"}
```

- [ ] **Step 4: Register the health router in `api/app/main.py`**

Add the import and `include_router` call:

```python
from app.auth import router as auth_router
from app.routes.activity import router as activity_router
from app.routes.chat import router as chat_router
from app.routes.health import router as health_router   # add this line
from app.routes.ingest import router as ingest_router
from app.routes.wiki import router as wiki_router

# ... existing middleware setup ...

app.include_router(auth_router)
app.include_router(wiki_router)
app.include_router(ingest_router)
app.include_router(chat_router)
app.include_router(activity_router)
app.include_router(health_router)   # add this line
```

- [ ] **Step 5: Run the test**

```bash
docker compose run --rm api pytest tests/test_health.py::test_health_run_returns_202 -v
```

Expected: PASS

- [ ] **Step 6: Add auto-trigger to ingest route**

In `api/app/routes/ingest.py`, at the end of each of the three ingest handlers (`POST /ingest/file`, `POST /ingest/url`, `POST /ingest/text`), add an auto-trigger after `background_tasks.add_task(...)`.

Find the shared ingest utility function or each handler's background task dispatch. Add this block after the `background_tasks.add_task(run_pipeline, ...)` call in each handler:

```python
# Auto health check every N ingests
from sqlalchemy import func, select as sa_select
from app.models import Source as _Source
count_result = await db.execute(
    sa_select(func.count(_Source.id)).where(_Source.workspace_id == ws.id)
)
source_count = count_result.scalar() or 0
if source_count > 0 and source_count % 10 == 0:
    from app.agents import health_agent
    background_tasks.add_task(health_agent.run, ws.id)
```

Note: import `func` from `sqlalchemy` at the top of the file — add `from sqlalchemy import func` if not already present.

- [ ] **Step 7: Run full test suite**

```bash
docker compose run --rm api pytest tests/ -v
```

Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add api/app/routes/health.py api/app/main.py api/app/routes/ingest.py tests/test_health.py
git commit -m "feat: health route POST /health/run and auto-trigger every 10 ingests"
```

---

## Task 6: Add `runHealthCheck` to Frontend API Client

The UI health button needs a client function.

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add `runHealthCheck` to `frontend/src/api/client.ts`**

Add at the end of the file:

```typescript
export async function runHealthCheck() {
  const r = await fetch(`${BASE}/health/run`, {
    method: 'POST',
    headers: headers(),
  })
  if (!r.ok) throw new Error('Health check failed to start')
  return r.json()
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat: add runHealthCheck API client function"
```

---

## Task 7: Sidebar Folder Tree UI

Replace the flat page list in `WikiPanel.tsx` with a collapsible folder tree. Add a health run button at the bottom.

**Files:**
- Modify: `frontend/src/components/WikiPanel.tsx`

- [ ] **Step 1: Replace the sidebar section in `frontend/src/components/WikiPanel.tsx`**

The current sidebar renders a flat `pages.map(...)`. Replace the entire `WikiPanel` component with the following. This preserves all existing page viewer + edit functionality and replaces only the sidebar:

```tsx
import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { usePages, usePage, useUpdatePage } from '../hooks/useWiki'
import { runHealthCheck } from '../api/client'

interface Props {
  highlightedSlug: string | null
}

function getFolderGroups(pages: { slug: string; title: string }[]) {
  const groups: Record<string, { slug: string; title: string }[]> = {}
  for (const page of pages) {
    const parts = page.slug.split('/')
    const folder = parts.length > 1 ? parts[0] + '/' : 'misc/'
    if (!groups[folder]) groups[folder] = []
    groups[folder].push(page)
  }
  // Sort: meta/ last, everything else alphabetical
  return Object.entries(groups).sort(([a], [b]) => {
    if (a === 'meta/') return 1
    if (b === 'meta/') return -1
    return a.localeCompare(b)
  })
}

const STORAGE_KEY = 'wiki_collapsed_folders'

function getCollapsed(): Record<string, boolean> {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') } catch { return {} }
}

function setCollapsed(state: Record<string, boolean>) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
}

export default function WikiPanel({ highlightedSlug }: Props) {
  const { data: pages = [] } = usePages()
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [editBody, setEditBody] = useState('')
  const [collapsed, setCollapsedState] = useState<Record<string, boolean>>(getCollapsed)
  const [healthRunning, setHealthRunning] = useState(false)
  const { data: page } = usePage(selectedSlug)
  const updatePage = useUpdatePage()

  function toggleFolder(folder: string) {
    const next = { ...collapsed, [folder]: !collapsed[folder] }
    setCollapsedState(next)
    setCollapsed(next)
  }

  function startEdit() {
    setEditBody(page?.body_md || '')
    setEditing(true)
  }

  function saveEdit() {
    if (!selectedSlug) return
    updatePage.mutate({ slug: selectedSlug, body_md: editBody })
    setEditing(false)
  }

  async function handleHealthRun() {
    if (healthRunning) return
    setHealthRunning(true)
    try { await runHealthCheck() } finally {
      setTimeout(() => setHealthRunning(false), 3000)
    }
  }

  const folderGroups = getFolderGroups(pages)

  return (
    <div style={{ display: 'flex', height: '100%', borderRight: '1px solid #30363d' }}>
      {/* Sidebar */}
      <div style={{ width: 220, overflowY: 'auto', background: '#161b22', padding: '12px 0', display: 'flex', flexDirection: 'column' }}>
        <div style={{ flex: 1 }}>
          <div style={{ padding: '0 16px 12px', fontSize: 11, color: '#8b949e', textTransform: 'uppercase', letterSpacing: 1 }}>
            Pages
          </div>
          {folderGroups.map(([folder, folderPages]) => {
            const isMeta = folder === 'meta/'
            const isCollapsed = collapsed[folder]
            return (
              <div key={folder}>
                {/* Folder header */}
                <div
                  onClick={() => toggleFolder(folder)}
                  style={{
                    padding: '4px 16px',
                    cursor: 'pointer',
                    fontSize: 11,
                    color: isMeta ? '#484f58' : '#6e7681',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                    userSelect: 'none',
                    letterSpacing: 0.5,
                  }}
                >
                  <span style={{ fontSize: 9 }}>{isCollapsed ? '▶' : '▼'}</span>
                  <span>{folder}</span>
                  <span style={{ marginLeft: 'auto', opacity: 0.6 }}>{folderPages.length}</span>
                </div>
                {/* Pages in folder */}
                {!isCollapsed && folderPages.map((p) => {
                  const leafName = p.slug.includes('/') ? p.slug.split('/').slice(1).join('/') : p.slug
                  return (
                    <div
                      key={p.slug}
                      onClick={() => { setSelectedSlug(p.slug); setEditing(false) }}
                      style={{
                        padding: '5px 16px 5px 28px',
                        cursor: 'pointer',
                        fontSize: 13,
                        color: selectedSlug === p.slug ? '#e6edf3' : isMeta ? '#484f58' : '#8b949e',
                        background: selectedSlug === p.slug ? '#21262d' : 'transparent',
                        borderLeft: highlightedSlug === p.slug ? '2px solid #58a6ff' : '2px solid transparent',
                        transition: 'all 0.15s',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                      title={p.title}
                    >
                      {leafName}
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>

        {/* Health run button */}
        <div style={{ padding: '12px 16px', borderTop: '1px solid #21262d' }}>
          <button
            onClick={handleHealthRun}
            disabled={healthRunning}
            style={{
              width: '100%',
              padding: '6px 0',
              background: healthRunning ? '#21262d' : '#161b22',
              border: '1px solid #30363d',
              borderRadius: 6,
              color: healthRunning ? '#484f58' : '#6e7681',
              fontSize: 11,
              cursor: healthRunning ? 'default' : 'pointer',
              letterSpacing: 0.5,
            }}
          >
            {healthRunning ? 'running health check…' : '⚕ health check'}
          </button>
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 24 }}>
        {page ? (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h1 style={{ fontSize: 20, color: '#e6edf3' }}>{page.title}</h1>
              <button onClick={editing ? saveEdit : startEdit}
                style={{ padding: '4px 14px', background: editing ? '#238636' : '#21262d',
                  border: '1px solid #30363d', borderRadius: 6, color: '#e6edf3', cursor: 'pointer', fontSize: 13 }}>
                {editing ? 'Save' : 'Edit'}
              </button>
            </div>
            {editing ? (
              <textarea value={editBody} onChange={e => setEditBody(e.target.value)}
                style={{ width: '100%', minHeight: 400, background: '#0d1117', border: '1px solid #30363d',
                  borderRadius: 6, color: '#e6edf3', padding: 16, fontFamily: 'monospace', fontSize: 13,
                  resize: 'vertical' }} />
            ) : (
              <div style={{ lineHeight: 1.7, fontSize: 14 }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{page.body_md}</ReactMarkdown>
              </div>
            )}
          </>
        ) : (
          <div style={{ color: '#8b949e', marginTop: 40, textAlign: 'center' }}>
            Select a page to read it, or ingest your first source.
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Build the frontend to verify no TypeScript errors**

```bash
cd frontend && npm run build
```

Expected: build succeeds with no errors.

- [ ] **Step 3: Start the full stack and manually verify**

```bash
docker compose up --build
```

Open `http://localhost:5173`. Verify:
- Sidebar shows folders (or `misc/` if no folder-prefixed pages exist yet)
- Clicking a folder toggles it open/closed
- Refreshing the page preserves collapsed state
- Health check button is visible at the bottom of the sidebar
- Clicking health check button shows "running health check…" then returns to normal

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/WikiPanel.tsx
git commit -m "feat: sidebar folder tree with collapse/expand and health run button"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| Slug-as-path, allow `/` in slugs | Task 1 |
| Fixed top-level taxonomy in agent prompts | Task 3 |
| Full-path wikilinks (`[[people/alice]]`) | Task 3 (prompt) + Task 1 (route) |
| `meta/` reserved for system pages | Task 3 (prompt) |
| `meta/index` incremental update after every write | Task 2 |
| `meta/index` folder-grouped with summaries | Task 2 (`update_index`) |
| Query agent reads `meta/index` first | Task 3 |
| Health agent: manual trigger `POST /health/run` | Task 5 |
| Health agent: auto-trigger every N ingests | Task 5 |
| Health agent: regenerate `meta/index` from scratch | Task 4 (prompt) |
| Health agent: fix broken wikilinks | Task 4 (prompt) |
| Health agent: add missing cross-references | Task 4 (prompt) |
| Health agent: flag orphan pages (no auto-delete) | Task 4 (prompt) |
| `meta/health-report` with Fixed + Needs attention | Task 4 |
| Sidebar: collapsible folder tree | Task 7 |
| `meta/` shown last, visually de-emphasised | Task 7 |
| Collapse state in localStorage | Task 7 |
| Health run button in sidebar | Task 7 |
| SSE shows health agent running live | Task 4 (`health:done` event published) |

All spec requirements are covered. ✓

**Placeholder scan:** No TBDs, TODOs, or vague steps. All code is complete. ✓

**Type consistency:**
- `update_index(slug, title, summary)` defined in Task 2, called from `write_page` in Task 2 — consistent.
- `health_agent.run(workspace_id)` defined in Task 4, called in Tasks 5 — consistent.
- `runHealthCheck()` defined in Task 6, imported in WikiPanel Task 7 — consistent.
- `getFolderGroups`, `getCollapsed`, `setCollapsed` all defined and used within Task 7 — consistent. ✓
