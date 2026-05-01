# Edit Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an edit-mode agent that can restructure and edit wiki pages on user instruction, accessed via an edit mode toggle in the existing chat UI.

**Architecture:** Three new tools (`move_page`, `delete_page`, `move_folder`) are added to `AgentTools`. A new `edit_agent.py` mirrors `query_agent.py` with these tools exposed. The `/chat/message` endpoint gains a `mode` field that routes to the appropriate agent. The frontend chat panel gains an amber edit mode toggle; the same `session_id` is used across modes.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, litellm, pytest-asyncio, React/TypeScript (inline styles)

---

## File Map

**Created:**
- `api/app/agents/edit_agent.py`
- `api/app/agents/prompts/edit.md`
- `api/tests/test_edit_tools.py`

**Modified:**
- `api/app/agents/tools.py` — add `_SLUG_RE`, `_FOLDER_RE`, `_remove_from_index`, `_do_move_page`, `move_page`, `delete_page`, `move_folder`; extend `as_litellm_tools()` and `dispatch()`
- `api/app/routes/chat.py` — add `mode` field to `MessageRequest`, dispatch to edit agent
- `api/tests/test_prompts.py` — add `edit.md` and `edit_agent` module checks
- `frontend/src/api/client.ts` — add `mode` param to `sendMessage`
- `frontend/src/components/ChatPanel.tsx` — add edit mode toggle
- `frontend/src/components/Layout.tsx` — handle `agent:moving`, `agent:deleting`, `agent:moved_folder` SSE events

---

### Task 1: Extend imports and add slug validation constants to `tools.py`

**Files:**
- Modify: `api/app/agents/tools.py`

- [ ] **Step 1: Update imports in `tools.py`**

At the top of `api/app/agents/tools.py`, the current sqlalchemy import is:
```python
from sqlalchemy import select
```
Change it to:
```python
from sqlalchemy import delete, select
```

The current models import is:
```python
from app.models import ActivityLog, Page, Revision, SourcePage
```
Change it to:
```python
from app.models import ActivityLog, Page, PageLink, Revision, SourcePage
```

- [ ] **Step 2: Add slug validation constants**

After the existing `_VISION_DESCRIBE_PROMPT` line, add:

```python
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*(/[a-z0-9][a-z0-9-]*)+$")
_FOLDER_RE = re.compile(r"^[a-z0-9][a-z0-9-]*(/[a-z0-9][a-z0-9-]*)*$")
```

`_SLUG_RE` requires at least one `/` (valid page slug). `_FOLDER_RE` allows a bare top-level prefix with no `/`.

- [ ] **Step 3: Commit**

```bash
git add api/app/agents/tools.py
git commit -m "feat: add slug validation regexes and PageLink import to AgentTools"
```

---

### Task 2: Add `_remove_from_index` helper

**Files:**
- Modify: `api/app/agents/tools.py`
- Create: `api/tests/test_edit_tools.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_edit_tools.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools import AgentTools


@pytest.fixture
def session():
    s = AsyncMock(spec=AsyncSession)
    s.add = MagicMock()
    return s


@pytest.fixture
def tools(session):
    return AgentTools(session=session, workspace_id="ws-1", broadcaster=None)


@pytest.mark.asyncio
async def test_remove_from_index_removes_entry(tools):
    index_body = (
        "# Wiki Index\n\n_Last updated: 2026-01-01_\n\n"
        "## people/ (2 pages)\n"
        "- [[people/alice]] — Alice\n"
        "- [[people/bob]] — Bob\n"
    )
    tools.read_page = AsyncMock(return_value=index_body)
    tools.write_page = AsyncMock(return_value="saved")

    await tools._remove_from_index("people/alice")

    written_body = tools.write_page.call_args[0][1]
    assert "people/alice" not in written_body
    assert "people/bob" in written_body


@pytest.mark.asyncio
async def test_remove_from_index_no_op_when_missing(tools):
    tools.read_page = AsyncMock(return_value="[Page 'meta/index' not found]")
    tools.write_page = AsyncMock()

    await tools._remove_from_index("people/alice")

    tools.write_page.assert_not_called()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd api && python -m pytest tests/test_edit_tools.py::test_remove_from_index_removes_entry tests/test_edit_tools.py::test_remove_from_index_no_op_when_missing -v
```

Expected: `FAILED` — `AgentTools` has no `_remove_from_index`.

- [ ] **Step 3: Implement `_remove_from_index`**

Add this method to `AgentTools` in `api/app/agents/tools.py`, after `update_index`:

```python
async def _remove_from_index(self, slug: str) -> None:
    raw = await self.read_page("meta/index")
    if raw.startswith("[Page 'meta/index' not found]"):
        return

    sections: dict[str, list[str]] = {}
    current_folder: str | None = None
    in_preamble = True

    for line in raw.split("\n"):
        m = re.match(r"^## (.+?)\s*\(\d+ pages?\)$", line)
        if m:
            in_preamble = False
            current_folder = m.group(1)
            if current_folder not in sections:
                sections[current_folder] = []
        elif not in_preamble and current_folder is not None and line.startswith("- [["):
            sections[current_folder].append(line)

    folder = (slug.rsplit("/", 1)[0] + "/") if "/" in slug else "misc/"
    if folder in sections:
        sections[folder] = [e for e in sections[folder] if not e.startswith(f"- [[{slug}]]")]

    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    lines: list[str] = ["# Wiki Index", "", f"_Last updated: {date_str}_", ""]
    for f in sorted(sections.keys(), key=lambda x: (x == "meta/", x)):
        if sections[f]:
            lines.append(f"## {f} ({len(sections[f])} pages)")
            lines.extend(sections[f])
            lines.append("")

    await self.write_page(
        "meta/index", "\n".join(lines), summary="Wiki table of contents", title="Index"
    )
```

Note: calling `write_page("meta/index", ...)` is safe — `update_index` has a guard `if slug == "meta/index": return` so it won't loop.

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd api && python -m pytest tests/test_edit_tools.py::test_remove_from_index_removes_entry tests/test_edit_tools.py::test_remove_from_index_no_op_when_missing -v
```

Expected: `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add api/app/agents/tools.py api/tests/test_edit_tools.py
git commit -m "feat: add _remove_from_index helper to AgentTools"
```

---

### Task 3: Add `_do_move_page` internal method

**Files:**
- Modify: `api/app/agents/tools.py`
- Modify: `api/tests/test_edit_tools.py`

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_edit_tools.py`:

```python
@pytest.mark.asyncio
async def test_do_move_page_copies_and_deletes(tools, session):
    from app.models import Page, PageLink

    old_page = MagicMock(spec=Page)
    old_page.id = "old-id"
    old_page.title = "Alice"
    old_page.body_md = "Content here."
    old_page.summary = "About Alice"

    # execute calls in order:
    # 1. check new_slug exists → None
    # 2. get old_page by old_slug → old_page
    # 3. query incoming PageLinks → empty list
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=old_page)),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        MagicMock(),  # delete PageLinks statement
    ]

    tools.write_page = AsyncMock(return_value="saved")
    tools._remove_from_index = AsyncMock()

    await tools._do_move_page("people/alice", "people/alice-jones")

    tools.write_page.assert_called_once_with(
        "people/alice-jones", old_page.body_md, old_page.summary, title=old_page.title
    )
    tools._remove_from_index.assert_called_once_with("people/alice")
    session.delete.assert_called_once_with(old_page)
    session.commit.assert_called()


@pytest.mark.asyncio
async def test_do_move_page_raises_on_collision(tools, session):
    from app.models import Page

    existing = MagicMock(spec=Page)
    session.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=existing))

    with pytest.raises(ValueError, match="already exists"):
        await tools._do_move_page("people/alice", "people/bob")


@pytest.mark.asyncio
async def test_do_move_page_rewrites_backlinks(tools, session):
    from app.models import Page, PageLink

    old_page = MagicMock(spec=Page)
    old_page.id = "old-id"
    old_page.title = "Alice"
    old_page.body_md = "Old content."
    old_page.summary = ""

    linking_page = MagicMock(spec=Page)
    linking_page.id = "linker-id"
    linking_page.slug = "projects/alpha"
    linking_page.body_md = "See [[people/alice]] for details."
    linking_page.workspace_id = "ws-1"

    link = MagicMock(spec=PageLink)
    link.from_page_id = "linker-id"

    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),       # new_slug check
        MagicMock(scalar_one_or_none=MagicMock(return_value=old_page)),   # get old page
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[link])))),  # incoming links
        MagicMock(scalar_one_or_none=MagicMock(return_value=linking_page)),  # get linking page
        MagicMock(),  # delete PageLinks
    ]

    tools.write_page = AsyncMock(return_value="saved")
    tools._remove_from_index = AsyncMock()

    with pytest.mock.patch("app.wikilinks.sync_links", new_callable=AsyncMock):
        await tools._do_move_page("people/alice", "people/alice-jones")

    assert "[[people/alice-jones]]" in linking_page.body_md
    assert "[[people/alice]]" not in linking_page.body_md
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd api && python -m pytest tests/test_edit_tools.py::test_do_move_page_copies_and_deletes tests/test_edit_tools.py::test_do_move_page_raises_on_collision tests/test_edit_tools.py::test_do_move_page_rewrites_backlinks -v
```

Expected: `FAILED` — `_do_move_page` not defined.

- [ ] **Step 3: Implement `_do_move_page`**

Add after `_remove_from_index` in `api/app/agents/tools.py`:

```python
async def _do_move_page(self, old_slug: str, new_slug: str) -> None:
    result = await self.session.execute(
        select(Page).where(Page.slug == new_slug, Page.workspace_id == self.workspace_id)
    )
    if result.scalar_one_or_none() is not None:
        raise ValueError(f"Destination slug '{new_slug}' already exists.")

    result = await self.session.execute(
        select(Page).where(Page.slug == old_slug, Page.workspace_id == self.workspace_id)
    )
    old_page = result.scalar_one_or_none()
    if old_page is None:
        raise ValueError(f"Page '{old_slug}' not found.")

    await self.write_page(new_slug, old_page.body_md, old_page.summary, title=old_page.title)

    result = await self.session.execute(
        select(PageLink).where(PageLink.to_page_id == old_page.id)
    )
    incoming_links = result.scalars().all()
    for link in incoming_links:
        result = await self.session.execute(
            select(Page).where(Page.id == link.from_page_id)
        )
        linking_page = result.scalar_one_or_none()
        if linking_page:
            linking_page.body_md = linking_page.body_md.replace(
                f"[[{old_slug}]]", f"[[{new_slug}]]"
            )
            self.session.add(linking_page)
            await sync_links(self.session, linking_page)

    await self.session.execute(
        delete(PageLink).where(
            (PageLink.from_page_id == old_page.id) | (PageLink.to_page_id == old_page.id)
        )
    )
    await self.session.delete(old_page)
    await self._remove_from_index(old_slug)
    await self.session.commit()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd api && python -m pytest tests/test_edit_tools.py::test_do_move_page_copies_and_deletes tests/test_edit_tools.py::test_do_move_page_raises_on_collision tests/test_edit_tools.py::test_do_move_page_rewrites_backlinks -v
```

Expected: `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add api/app/agents/tools.py api/tests/test_edit_tools.py
git commit -m "feat: add _do_move_page to AgentTools"
```

---

### Task 4: Add `move_page` public tool

**Files:**
- Modify: `api/app/agents/tools.py`
- Modify: `api/tests/test_edit_tools.py`

- [ ] **Step 1: Write failing tests**

Append to `api/tests/test_edit_tools.py`:

```python
@pytest.mark.asyncio
async def test_move_page_invalid_slug_returns_error(tools):
    result = await tools.move_page("people/alice", "PEOPLE/ALICE")
    assert "invalid" in result.lower()


@pytest.mark.asyncio
async def test_move_page_collision_returns_error(tools):
    tools._do_move_page = AsyncMock(side_effect=ValueError("Destination slug 'people/bob' already exists."))
    result = await tools.move_page("people/alice", "people/bob")
    assert "already exists" in result


@pytest.mark.asyncio
async def test_move_page_broadcasts_and_returns_success(tools):
    tools._do_move_page = AsyncMock()
    broadcaster = AsyncMock()
    tools.broadcaster = broadcaster

    result = await tools.move_page("people/alice", "people/alice-jones")

    tools._do_move_page.assert_called_once_with("people/alice", "people/alice-jones")
    broadcaster.publish.assert_called_once_with(
        {"event": "agent:moving", "from": "people/alice", "to": "people/alice-jones"}
    )
    assert "people/alice-jones" in result
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd api && python -m pytest tests/test_edit_tools.py::test_move_page_invalid_slug_returns_error tests/test_edit_tools.py::test_move_page_collision_returns_error tests/test_edit_tools.py::test_move_page_broadcasts_and_returns_success -v
```

Expected: `FAILED` — `move_page` not defined.

- [ ] **Step 3: Implement `move_page`**

Add after `_do_move_page` in `api/app/agents/tools.py`:

```python
async def move_page(self, old_slug: str, new_slug: str) -> str:
    if not _SLUG_RE.match(new_slug):
        return (
            f"Error: '{new_slug}' is not a valid slug. "
            "Use lowercase letters, digits, hyphens, and at least one '/' "
            "(e.g. 'people/alice-jones')."
        )
    try:
        await self._do_move_page(old_slug, new_slug)
    except ValueError as e:
        return f"Error: {e}"
    await self._broadcast({"event": "agent:moving", "from": old_slug, "to": new_slug})
    return f"Moved '{old_slug}' → '{new_slug}'."
```

- [ ] **Step 4: Add `move_page` to `as_litellm_tools()`**

In the `all_tools` list inside `as_litellm_tools()`, append after the `create_page` entry:

```python
{
    "type": "function",
    "function": {
        "name": "move_page",
        "description": "Move (rename) a wiki page to a new slug. Automatically rewrites all backlinks. Fails if new_slug already exists.",
        "parameters": {
            "type": "object",
            "properties": {
                "old_slug": {"type": "string", "description": "Current slug of the page"},
                "new_slug": {"type": "string", "description": "Destination slug (must not already exist)"},
            },
            "required": ["old_slug", "new_slug"],
        },
    },
},
```

- [ ] **Step 5: Add `move_page` to `dispatch()`**

Before the final `return f"Unknown tool: {name}"` line in `dispatch()`:

```python
if name == "move_page":
    return await self.move_page(args["old_slug"], args["new_slug"])
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
cd api && python -m pytest tests/test_edit_tools.py::test_move_page_invalid_slug_returns_error tests/test_edit_tools.py::test_move_page_collision_returns_error tests/test_edit_tools.py::test_move_page_broadcasts_and_returns_success -v
```

Expected: `PASSED`.

- [ ] **Step 7: Commit**

```bash
git add api/app/agents/tools.py api/tests/test_edit_tools.py
git commit -m "feat: add move_page tool to AgentTools"
```

---

### Task 5: Add `delete_page` tool

**Files:**
- Modify: `api/app/agents/tools.py`
- Modify: `api/tests/test_edit_tools.py`

- [ ] **Step 1: Write failing tests**

Append to `api/tests/test_edit_tools.py`:

```python
@pytest.mark.asyncio
async def test_delete_page_not_found_returns_error(tools, session):
    session.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    result = await tools.delete_page("people/ghost")
    assert "not found" in result.lower()


@pytest.mark.asyncio
async def test_delete_page_marks_backlinks(tools, session):
    from app.models import Page, PageLink

    target = MagicMock(spec=Page)
    target.id = "t-id"
    target.slug = "people/alice"
    target.title = "Alice"

    linker = MagicMock(spec=Page)
    linker.id = "l-id"
    linker.slug = "projects/alpha"
    linker.body_md = "See [[people/alice]] for details."
    linker.workspace_id = "ws-1"

    link = MagicMock(spec=PageLink)
    link.from_page_id = "l-id"

    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=target)),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[link])))),
        MagicMock(scalar_one_or_none=MagicMock(return_value=linker)),
        MagicMock(),  # delete PageLinks
    ]

    tools._remove_from_index = AsyncMock()
    tools.write_page = AsyncMock(return_value="saved")

    with pytest.mock.patch("app.wikilinks.sync_links", new_callable=AsyncMock):
        await tools.delete_page("people/alice")

    assert "[[people/alice]] *(page deleted)*" in linker.body_md


@pytest.mark.asyncio
async def test_delete_page_logs_to_deleted_log(tools, session):
    from app.models import Page

    target = MagicMock(spec=Page)
    target.id = "t-id"
    target.slug = "people/alice"
    target.title = "Alice"

    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=target)),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        MagicMock(),  # delete PageLinks
    ]

    tools._remove_from_index = AsyncMock()
    written: list[tuple] = []

    async def capture(slug, body, *a, **kw):
        written.append((slug, body))
        return "saved"

    tools.read_page = AsyncMock(return_value="[Page 'meta/deleted-log' not found]")
    tools.write_page = AsyncMock(side_effect=capture)

    await tools.delete_page("people/alice")

    log_entries = [(s, b) for s, b in written if s == "meta/deleted-log"]
    assert log_entries, "Expected write to meta/deleted-log"
    assert "people/alice" in log_entries[0][1]
    assert "Alice" in log_entries[0][1]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd api && python -m pytest tests/test_edit_tools.py::test_delete_page_not_found_returns_error tests/test_edit_tools.py::test_delete_page_marks_backlinks tests/test_edit_tools.py::test_delete_page_logs_to_deleted_log -v
```

Expected: `FAILED` — `delete_page` not defined.

- [ ] **Step 3: Implement `delete_page`**

Add after `move_page` in `api/app/agents/tools.py`:

```python
async def delete_page(self, slug: str) -> str:
    result = await self.session.execute(
        select(Page).where(Page.slug == slug, Page.workspace_id == self.workspace_id)
    )
    page = result.scalar_one_or_none()
    if page is None:
        return f"Error: Page '{slug}' not found."

    title = page.title

    result = await self.session.execute(
        select(PageLink).where(PageLink.to_page_id == page.id)
    )
    incoming_links = result.scalars().all()
    for link in incoming_links:
        result = await self.session.execute(
            select(Page).where(Page.id == link.from_page_id)
        )
        linking_page = result.scalar_one_or_none()
        if linking_page:
            linking_page.body_md = linking_page.body_md.replace(
                f"[[{slug}]]", f"[[{slug}]] *(page deleted)*"
            )
            self.session.add(linking_page)
            await sync_links(self.session, linking_page)

    await self.session.execute(
        delete(PageLink).where(
            (PageLink.from_page_id == page.id) | (PageLink.to_page_id == page.id)
        )
    )
    await self.session.delete(page)
    await self.session.commit()

    await self._remove_from_index(slug)

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    existing_log = await self.read_page("meta/deleted-log")
    new_row = f"| {timestamp} | [[{slug}]] *(page deleted)* | {title} |\n"
    if existing_log.startswith("[Page 'meta/deleted-log' not found]"):
        log_body = f"# Deleted Pages\n\n| Deleted At | Page | Title |\n|---|---|---|\n{new_row}"
    else:
        log_body = existing_log + new_row
    await self.write_page(
        "meta/deleted-log", log_body, summary="Audit log of deleted pages", title="Deleted Pages"
    )

    await self._broadcast({"event": "agent:deleting", "slug": slug})
    return f"Deleted '{slug}'. Backlinks marked. Logged to [[meta/deleted-log]]."
```

- [ ] **Step 4: Add `delete_page` to `as_litellm_tools()`**

After the `move_page` entry in `all_tools`:

```python
{
    "type": "function",
    "function": {
        "name": "delete_page",
        "description": "Delete a wiki page. Backlinks in other pages are marked '*(page deleted)*'. Deletion is logged to meta/deleted-log.",
        "parameters": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Slug of the page to delete"},
            },
            "required": ["slug"],
        },
    },
},
```

- [ ] **Step 5: Add `delete_page` to `dispatch()`**

```python
if name == "delete_page":
    return await self.delete_page(args["slug"])
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
cd api && python -m pytest tests/test_edit_tools.py::test_delete_page_not_found_returns_error tests/test_edit_tools.py::test_delete_page_marks_backlinks tests/test_edit_tools.py::test_delete_page_logs_to_deleted_log -v
```

Expected: `PASSED`.

- [ ] **Step 7: Commit**

```bash
git add api/app/agents/tools.py api/tests/test_edit_tools.py
git commit -m "feat: add delete_page tool to AgentTools"
```

---

### Task 6: Add `move_folder` tool

**Files:**
- Modify: `api/app/agents/tools.py`
- Modify: `api/tests/test_edit_tools.py`

- [ ] **Step 1: Write failing tests**

Append to `api/tests/test_edit_tools.py`:

```python
@pytest.mark.asyncio
async def test_move_folder_invalid_prefix_returns_error(tools):
    result = await tools.move_folder("PROJECTS/2025", "archive/2025")
    assert "invalid" in result.lower()


@pytest.mark.asyncio
async def test_move_folder_empty_source_returns_error(tools, session):
    session.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    )
    result = await tools.move_folder("projects/2025", "archive/2025")
    assert "no pages" in result.lower()


@pytest.mark.asyncio
async def test_move_folder_collision_returns_error(tools, session):
    from app.models import Page

    src = MagicMock(spec=Page)
    src.slug = "projects/2025/alpha"
    conflict = MagicMock(spec=Page)
    conflict.slug = "archive/2025/alpha"

    session.execute.side_effect = [
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[src])))),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[conflict])))),
    ]
    result = await tools.move_folder("projects/2025", "archive/2025")
    assert "conflict" in result.lower() or "already" in result.lower()


@pytest.mark.asyncio
async def test_move_folder_moves_all_and_broadcasts(tools, session):
    from app.models import Page

    page_a = MagicMock(spec=Page)
    page_a.slug = "projects/2025/alpha"
    page_b = MagicMock(spec=Page)
    page_b.slug = "projects/2025/beta"

    session.execute.side_effect = [
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[page_a, page_b])))),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),  # no collisions
    ]

    tools._do_move_page = AsyncMock()
    broadcaster = AsyncMock()
    tools.broadcaster = broadcaster

    result = await tools.move_folder("projects/2025", "archive/2025")

    assert tools._do_move_page.call_count == 2
    tools._do_move_page.assert_any_call("projects/2025/alpha", "archive/2025/alpha")
    tools._do_move_page.assert_any_call("projects/2025/beta", "archive/2025/beta")
    broadcaster.publish.assert_called_once_with({
        "event": "agent:moved_folder",
        "from": "projects/2025",
        "to": "archive/2025",
        "count": 2,
    })
    assert "2 pages" in result
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd api && python -m pytest tests/test_edit_tools.py::test_move_folder_invalid_prefix_returns_error tests/test_edit_tools.py::test_move_folder_empty_source_returns_error tests/test_edit_tools.py::test_move_folder_collision_returns_error tests/test_edit_tools.py::test_move_folder_moves_all_and_broadcasts -v
```

Expected: `FAILED` — `move_folder` not defined.

- [ ] **Step 3: Implement `move_folder`**

Add after `delete_page` in `api/app/agents/tools.py`:

```python
async def move_folder(self, old_prefix: str, new_prefix: str) -> str:
    if not _FOLDER_RE.match(new_prefix):
        return (
            f"Error: '{new_prefix}' is not a valid folder prefix. "
            "Use lowercase letters, digits, and hyphens (e.g. 'archive/2025')."
        )

    result = await self.session.execute(
        select(Page).where(
            Page.slug.like(f"{old_prefix}/%"),
            Page.workspace_id == self.workspace_id,
        )
    )
    pages = result.scalars().all()
    if not pages:
        return f"Error: No pages found under '{old_prefix}/'."

    new_slugs = [p.slug.replace(old_prefix, new_prefix, 1) for p in pages]

    result = await self.session.execute(
        select(Page).where(
            Page.slug.in_(new_slugs),
            Page.workspace_id == self.workspace_id,
        )
    )
    collisions = result.scalars().all()
    if collisions:
        conflict_list = ", ".join(p.slug for p in collisions)
        return f"Error: Destination already has conflicting pages: {conflict_list}."

    for page, new_slug in zip(pages, new_slugs):
        await self._do_move_page(page.slug, new_slug)

    count = len(pages)
    await self._broadcast({
        "event": "agent:moved_folder",
        "from": old_prefix,
        "to": new_prefix,
        "count": count,
    })
    return f"Moved {count} pages from '{old_prefix}/' to '{new_prefix}/'."
```

- [ ] **Step 4: Add `move_folder` to `as_litellm_tools()`**

After the `delete_page` entry in `all_tools`:

```python
{
    "type": "function",
    "function": {
        "name": "move_folder",
        "description": "Move all pages under a folder prefix to a new prefix. E.g. move_folder('projects/2025', 'archive/2025') moves every page whose slug starts with 'projects/2025/'. Fails if any destination slug already exists.",
        "parameters": {
            "type": "object",
            "properties": {
                "old_prefix": {"type": "string", "description": "Source folder prefix (e.g. 'projects/2025')"},
                "new_prefix": {"type": "string", "description": "Destination folder prefix (e.g. 'archive/2025')"},
            },
            "required": ["old_prefix", "new_prefix"],
        },
    },
},
```

- [ ] **Step 5: Add `move_folder` to `dispatch()`**

```python
if name == "move_folder":
    return await self.move_folder(args["old_prefix"], args["new_prefix"])
```

- [ ] **Step 6: Run all edit tool tests**

```bash
cd api && python -m pytest tests/test_edit_tools.py -v
```

Expected: all `PASSED`.

- [ ] **Step 7: Commit**

```bash
git add api/app/agents/tools.py api/tests/test_edit_tools.py
git commit -m "feat: add move_folder tool to AgentTools"
```

---

### Task 7: Create `edit_agent.py` and `prompts/edit.md`

**Files:**
- Create: `api/app/agents/prompts/edit.md`
- Create: `api/app/agents/edit_agent.py`
- Modify: `api/tests/test_prompts.py`

- [ ] **Step 1: Create the system prompt**

Create `api/app/agents/prompts/edit.md`:

```markdown
You are the **Wiki Editor**: you restructure and edit the user's personal wiki on their instruction. Execute immediately — no confirmation needed.

## Your tools
- `list_pages`, `search_pages`, `read_page` — read the wiki
- `write_page`, `create_page` — edit or create page content
- `move_page(old_slug, new_slug)` — rename/move one page; rewrites all backlinks automatically
- `move_folder(old_prefix, new_prefix)` — move an entire folder subtree (e.g. `projects/2025` → `archive/2025`)
- `delete_page(slug)` — delete a page; backlinks are marked `*(page deleted)*` and the deletion is logged to `meta/deleted-log`

## How to work
1. Call `read_page("meta/index")` first to understand the current structure.
2. For folder-level moves use `move_folder`. For single pages use `move_page`.
3. For content edits: read the page first, then write the updated version.
4. Slugs must be lowercase, use hyphens, contain at least one `/` (e.g. `people/alice-jones`).
5. `move_page` fails if the destination already exists — check `meta/index` first if unsure.
6. Never edit `meta/index` directly — it maintains itself automatically.
```

- [ ] **Step 2: Create `edit_agent.py`**

Create `api/app/agents/edit_agent.py`:

```python
import json
import re
from pathlib import Path

import litellm
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.assistant_message import assistant_message_for_litellm
from app.agents.tools import AgentTools
from app.config import settings
from app.sse import broadcaster


_PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS / "edit.md").read_text()

EDIT_TOOLS = [
    "list_pages",
    "search_pages",
    "read_page",
    "write_page",
    "create_page",
    "move_page",
    "move_folder",
    "delete_page",
]


async def run(
    workspace_id: str,
    question: str,
    history: list[dict],
    session: AsyncSession,
) -> tuple[str, list[str]]:
    tools = AgentTools(session=session, workspace_id=workspace_id, broadcaster=broadcaster)
    tool_defs = tools.as_litellm_tools(allowed=EDIT_TOOLS)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history[-10:],
        {"role": "user", "content": question},
    ]

    touched_pages: list[str] = []

    for _ in range(20):
        resp = await litellm.acompletion(
            model=settings.litellm_model,
            messages=messages,
            tools=tool_defs,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        messages.append(assistant_message_for_litellm(msg))

        if not msg.tool_calls:
            answer = msg.content or ""
            touched_pages = re.findall(r"\[\[([^\]]+)\]\]", answer)
            await broadcaster.publish({"event": "agent:done", "pages_touched": touched_pages})
            return answer, touched_pages

        for tc in msg.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments or "{}")
            result_str = await tools.dispatch(name, args)
            if name == "read_page":
                touched_pages.append(args.get("slug", ""))
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

    await broadcaster.publish({"event": "agent:done", "pages_touched": touched_pages})
    return "I wasn't able to complete the edit operation.", touched_pages
```

The loop limit is 20 (vs 10 in query_agent) — a folder move of 15 pages needs 15+ tool calls.

- [ ] **Step 3: Update `test_prompts.py`**

In `api/tests/test_prompts.py`:

Add `"edit.md"` to `STATIC_PROMPTS`:

```python
STATIC_PROMPTS = [
    "query.md",
    "edit.md",
    "ingest_small.md",
    "ingest_large.md",
    "health.md",
    "chat_monitor.md",
    "sub_agent.md",
    "vision_describe.md",
]
```

Update `test_agent_modules_load_prompts` to include `edit_agent`:

```python
def test_agent_modules_load_prompts():
    from app.agents import query_agent, health_agent, chat_monitor, sub_agent, edit_agent
    assert query_agent.SYSTEM_PROMPT.strip()
    assert health_agent.SYSTEM_PROMPT.strip()
    assert chat_monitor.SYSTEM_PROMPT.strip()
    assert sub_agent.SYSTEM_PROMPT.strip()
    assert edit_agent.SYSTEM_PROMPT.strip()
```

- [ ] **Step 4: Run prompt tests**

```bash
cd api && python -m pytest tests/test_prompts.py -v
```

Expected: all `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add api/app/agents/edit_agent.py api/app/agents/prompts/edit.md api/tests/test_prompts.py
git commit -m "feat: add edit_agent with system prompt and EDIT_TOOLS list"
```

---

### Task 8: Wire edit mode into `/chat/message`

**Files:**
- Modify: `api/app/routes/chat.py`

- [ ] **Step 1: Add `mode` field to `MessageRequest`**

In `api/app/routes/chat.py`, add `Literal` to the typing import at the top:

```python
from typing import Literal
```

Update the `MessageRequest` model (currently has `message` and `session_id`):

```python
class MessageRequest(BaseModel):
    message: str
    session_id: str | None = None
    mode: Literal["query", "edit"] = "query"
```

- [ ] **Step 2: Dispatch based on mode**

In the `send_message` handler, replace:

```python
    answer, cited = await run_query(ws.id, body.message, history[:-1], db)
```

With:

```python
    if body.mode == "edit":
        from app.agents.edit_agent import run as run_edit
        answer, cited = await run_edit(ws.id, body.message, history[:-1], db)
    else:
        answer, cited = await run_query(ws.id, body.message, history[:-1], db)
```

- [ ] **Step 3: Run all backend tests**

```bash
cd api && python -m pytest tests/ -v
```

Expected: all `PASSED`.

- [ ] **Step 4: Commit**

```bash
git add api/app/routes/chat.py
git commit -m "feat: add mode param to /chat/message, route to edit_agent when mode=edit"
```

---

### Task 9: Frontend — `sendMessage` mode param

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add `mode` param to `sendMessage`**

In `frontend/src/api/client.ts`, replace:

```typescript
export async function sendMessage(message: string, sessionId?: string) {
  const r = await fetch(`${BASE}/chat/message`, {
    method: 'POST', headers: headers(),
    body: JSON.stringify({ message, session_id: sessionId })
  })
  return r.json()
}
```

With:

```typescript
export async function sendMessage(message: string, sessionId?: string, mode: 'query' | 'edit' = 'query') {
  const r = await fetch(`${BASE}/chat/message`, {
    method: 'POST', headers: headers(),
    body: JSON.stringify({ message, session_id: sessionId, mode })
  })
  return r.json()
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat: add mode param to sendMessage API client"
```

---

### Task 10: Frontend — edit mode toggle in `ChatPanel`

**Files:**
- Modify: `frontend/src/components/ChatPanel.tsx`

- [ ] **Step 1: Add `editMode` state**

In `frontend/src/components/ChatPanel.tsx`, add state alongside the existing state declarations:

```typescript
const [editMode, setEditMode] = useState(false)
```

- [ ] **Step 2: Pass mode to `sendMessage`**

In the `submit` function, update the `sendMessage` call:

```typescript
const resp = await sendMessage(text, sessionId, editMode ? 'edit' : 'query')
```

- [ ] **Step 3: Replace the input row div**

Replace the existing bottom `<div>` (the one with `padding: 12, borderTop...`):

```tsx
<div style={{ padding: 12, borderTop: '1px solid #30363d', display: 'flex', flexDirection: 'column', gap: 8 }}>
  <div style={{ display: 'flex', gap: 8 }}>
    <input
      value={input}
      onChange={e => setInput(e.target.value)}
      onKeyDown={e => e.key === 'Enter' && !e.shiftKey && submit()}
      placeholder={editMode ? 'Instruct the editor…' : 'Ask your wiki…'}
      style={{
        flex: 1, padding: '8px 12px', background: '#161b22',
        border: `1px solid ${editMode ? '#d29922' : '#30363d'}`,
        borderRadius: 6, color: '#e6edf3', fontSize: 13,
      }}
    />
    <button
      onClick={submit}
      disabled={loading}
      style={{
        padding: '8px 16px', background: '#238636', border: 'none',
        borderRadius: 6, color: '#fff',
        cursor: loading ? 'not-allowed' : 'pointer', fontSize: 13,
      }}
    >
      Send
    </button>
  </div>
  <button
    type="button"
    onClick={() => setEditMode(m => !m)}
    style={{
      padding: '4px 10px', alignSelf: 'flex-start',
      background: editMode ? '#d29922' : '#21262d',
      border: `1px solid ${editMode ? '#d29922' : '#30363d'}`,
      borderRadius: 6,
      color: editMode ? '#0d1117' : '#8b949e',
      cursor: 'pointer', fontSize: 11,
      fontWeight: editMode ? 600 : 400,
    }}
  >
    {editMode ? '✎ Edit Mode ON' : 'Edit Mode'}
  </button>
</div>
```

- [ ] **Step 4: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ChatPanel.tsx
git commit -m "feat: add edit mode toggle to ChatPanel"
```

---

### Task 11: Frontend — SSE events for edit agent actions

**Files:**
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: Add new SSE cases**

In `frontend/src/components/Layout.tsx`, inside the `createSSE` callback, after the `agent:writing` block and before the `agent:done` block, add:

```typescript
} else if (event.event === 'agent:moving') {
  const e = event as { event: string; from?: string; to?: string }
  setHighlightedSlug(e.to || null)
  setAgentStatus(e.from && e.to ? `Moving ${e.from} → ${e.to}…` : 'Moving page…')
} else if (event.event === 'agent:deleting') {
  setHighlightedSlug(null)
  setAgentStatus(event.slug ? `Deleting ${event.slug}…` : 'Deleting page…')
} else if (event.event === 'agent:moved_folder') {
  const e = event as { event: string; from?: string; to?: string; count?: number }
  setHighlightedSlug(null)
  setAgentStatus(
    e.from && e.to
      ? `Moved ${e.count ?? '?'} pages: ${e.from} → ${e.to}`
      : 'Folder move complete'
  )
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Layout.tsx
git commit -m "feat: handle agent:moving, agent:deleting, agent:moved_folder SSE events"
```

---

### Task 12: Integration verification

- [ ] **Step 1: Run all backend tests**

```bash
cd api && python -m pytest tests/ -v
```

Expected: all `PASSED`.

- [ ] **Step 2: Start the dev stack**

```bash
docker-compose up
```

- [ ] **Step 3: Manual smoke test — edit mode toggle**

1. Open the app in a browser.
2. In the chat panel, click "Edit Mode" — button turns amber, input border turns amber, placeholder changes to "Instruct the editor…".
3. Click again — returns to default state.

- [ ] **Step 4: Manual smoke test — move a page**

1. Toggle edit mode ON.
2. Send: `"Move meta/index to meta/wiki-index"` — the edit agent will error because `meta/index` is in the protected folder; verify the agent explains this gracefully.
3. Send: `"Move people/some-existing-page to people/renamed-page"` (use a real slug from your wiki).
4. Watch the topbar show `Moving people/some-existing-page → people/renamed-page…`.
5. Confirm the page appears at the new slug in the sidebar.

- [ ] **Step 5: Manual smoke test — query mode still works**

1. Toggle edit mode OFF.
2. Send a query — confirm the read-only query agent responds normally.

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat: complete edit agent — move, delete, folder moves, UI toggle"
```
