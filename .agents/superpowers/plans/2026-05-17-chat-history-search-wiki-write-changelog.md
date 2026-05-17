# Chat History Search, Query Agent Wiki Writes, and Changelog — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the query agent the ability to search raw past conversations, write to the wiki mid-conversation, and maintain an atomic changelog of all wiki changes visible to both agent and user.

**Architecture:** Three changes to `AgentTools` (new `search_chat_history` tool, atomic `_append_changelog` helper, changelog hooks in write/delete/move), corresponding updates to the query agent's allowed tool list and prompts, a stripped-down `chat_monitor` prompt, and a new "Changes" tab in the frontend `ActivityLog` panel.

**Tech Stack:** Python/FastAPI, SQLAlchemy async, PostgreSQL (raw `text()` for atomic UPDATE), React 18/TypeScript, pytest-asyncio for integration tests.

---

## File map

| File | What changes |
|------|-------------|
| `api/app/agents/tools.py` | Add `search_chat_history()`, `_append_changelog()`, `_suppress_changelog` flag; hook changelog into `write_page`, `delete_page`, `move_page`, `move_folder` |
| `api/app/agents/query_agent.py` | Rename `READ_ONLY_TOOLS` → `QUERY_TOOLS`, add write + search tools |
| `api/app/agents/prompts/query.md` | Add wiki-write guidance, search_chat_history priority, system/changelog mention |
| `api/app/agents/prompts/chat_monitor.md` | Remove section 3 (wiki saves) and its order-of-operations reference |
| `tests/test_chat_history_search.py` | New integration tests for `search_chat_history` |
| `tests/test_changelog.py` | New integration tests for `_append_changelog` and changelog hooks |
| `frontend/src/components/ActivityLog.tsx` | Add "Changes" tab filtered to page_created / page_updated / page_deleted |

---

## Task 1: `search_chat_history` method

**Files:**
- Modify: `api/app/agents/tools.py`
- Create: `tests/test_chat_history_search.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_chat_history_search.py`:

```python
import pytest
from app.agents.tools import AgentTools
from app.models import ChatMessage, ChatSession, Workspace
from sqlalchemy import select


@pytest.fixture
def tools(db_session, workspace_id):
    return AgentTools(session=db_session, workspace_id=workspace_id, broadcaster=None)


@pytest.mark.asyncio
async def test_search_finds_matching_message(tools, db_session, workspace_id):
    session_obj = ChatSession(workspace_id=workspace_id)
    db_session.add(session_obj)
    await db_session.flush()
    db_session.add(ChatMessage(session_id=session_obj.id, role="user", content="Paris road trip plan"))
    db_session.add(ChatMessage(session_id=session_obj.id, role="assistant", content="Route: Lyon → Paris"))
    await db_session.commit()

    result = await tools.search_chat_history("Paris road trip")
    assert "Paris road trip plan" in result
    assert "USER:" in result


@pytest.mark.asyncio
async def test_search_returns_no_match_message(tools, db_session, workspace_id):
    session_obj = ChatSession(workspace_id=workspace_id)
    db_session.add(session_obj)
    await db_session.flush()
    db_session.add(ChatMessage(session_id=session_obj.id, role="user", content="Hello world"))
    await db_session.commit()

    result = await tools.search_chat_history("xyznotfound")
    assert result == "No matching messages found in chat history."


@pytest.mark.asyncio
async def test_search_respects_workspace_isolation(db_session, workspace_id):
    ws2 = Workspace(user_id="other-user")
    db_session.add(ws2)
    await db_session.flush()
    other_session = ChatSession(workspace_id=ws2.id)
    db_session.add(other_session)
    await db_session.flush()
    db_session.add(ChatMessage(session_id=other_session.id, role="user", content="secret content xyz"))
    await db_session.commit()

    tools = AgentTools(session=db_session, workspace_id=workspace_id, broadcaster=None)
    result = await tools.search_chat_history("secret content xyz")
    assert result == "No matching messages found in chat history."


@pytest.mark.asyncio
async def test_search_char_window_excludes_long_neighbours(tools, db_session, workspace_id):
    session_obj = ChatSession(workspace_id=workspace_id)
    db_session.add(session_obj)
    await db_session.flush()
    db_session.add(ChatMessage(session_id=session_obj.id, role="user", content="find me please"))
    db_session.add(ChatMessage(session_id=session_obj.id, role="assistant", content="z" * 1000))
    await db_session.commit()

    # With a 50-char window, the 1000-char adjacent message should be excluded
    result = await tools.search_chat_history("find me please", context_window_chars=50)
    assert "find me please" in result
    assert "z" * 100 not in result


@pytest.mark.asyncio
async def test_search_includes_surrounding_context_within_budget(tools, db_session, workspace_id):
    session_obj = ChatSession(workspace_id=workspace_id)
    db_session.add(session_obj)
    await db_session.flush()
    db_session.add(ChatMessage(session_id=session_obj.id, role="user", content="before message"))
    db_session.add(ChatMessage(session_id=session_obj.id, role="assistant", content="match here"))
    db_session.add(ChatMessage(session_id=session_obj.id, role="user", content="after message"))
    await db_session.commit()

    result = await tools.search_chat_history("match here", context_window_chars=2000)
    assert "before message" in result
    assert "match here" in result
    assert "after message" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose run --rm api pytest tests/test_chat_history_search.py -v
```

Expected: `AttributeError: 'AgentTools' object has no attribute 'search_chat_history'`

- [ ] **Step 3: Add imports and the method to `tools.py`**

In `api/app/agents/tools.py`, update the sqlalchemy import line:

```python
from sqlalchemy import delete, select, text
```

Update the models import line:

```python
from app.models import ActivityLog, ChatMessage, ChatSession, Page, PageLink, Revision, SourcePage
```

Add `_CHANGELOG_EXCLUDED` as a **module-level constant** (after `_LOG = structlog.get_logger()`, matching the existing `_SLUG_RE` / `_FOLDER_RE` pattern — NOT inside the class):

```python
_CHANGELOG_EXCLUDED = frozenset({
    "system/changelog",
    "system/memory",
    "system/history",
    "meta/index",
    "meta/deleted-log",
})
```

Add `search_chat_history` as a method on `AgentTools` (after `grep_page`, before `create_page`):

```python
async def search_chat_history(
    self, query: str, context_window_chars: int = 2000
) -> str:
    matches_result = await self.session.execute(
        select(ChatMessage)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.workspace_id == self.workspace_id)
        .where(ChatMessage.content.ilike(f"%{query}%"))
        .order_by(ChatMessage.created_at.desc())
        .limit(20)
    )
    matches = matches_result.scalars().all()

    if not matches:
        return "No matching messages found in chat history."

    # Collect up to 5 unique sessions, preserving order of relevance
    seen_sessions: dict[str, list[str]] = {}
    for m in matches:
        if m.session_id not in seen_sessions:
            seen_sessions[m.session_id] = []
        seen_sessions[m.session_id].append(m.id)
        if len(seen_sessions) >= 5:
            break

    excerpts: list[str] = []
    for session_id, match_ids in seen_sessions.items():
        session_msgs_result = await self.session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
        all_msgs = session_msgs_result.scalars().all()

        match_id_set = set(match_ids)
        first_match_idx = next(
            (i for i, m in enumerate(all_msgs) if m.id in match_id_set), 0
        )

        selected = [first_match_idx]
        chars_used = len(all_msgs[first_match_idx].content)
        left = first_match_idx - 1
        right = first_match_idx + 1

        while chars_used < context_window_chars:
            grew = False
            if left >= 0:
                c = len(all_msgs[left].content)
                if chars_used + c <= context_window_chars:
                    selected.append(left)
                    chars_used += c
                    left -= 1
                    grew = True
                else:
                    left = -1
            if right < len(all_msgs):
                c = len(all_msgs[right].content)
                if chars_used + c <= context_window_chars:
                    selected.append(right)
                    chars_used += c
                    right += 1
                    grew = True
                else:
                    right = len(all_msgs)
            if not grew:
                break

        session_date = all_msgs[0].created_at.strftime("%Y-%m-%d")
        lines = [f"[Session {session_date}]"]
        for i in sorted(set(selected)):
            msg = all_msgs[i]
            lines.append(f"{msg.role.upper()}: {msg.content}")
        excerpts.append("\n".join(lines))

    return "\n---\n".join(excerpts)
```

- [ ] **Step 4: Add tool definition to `as_litellm_tools`**

In `as_litellm_tools`, add after the `grep_page` tool definition (before `move_page`):

```python
{
    "type": "function",
    "function": {
        "name": "search_chat_history",
        "description": (
            "Search raw past conversation messages by keyword. "
            "Use ONLY when the user explicitly references a past conversation "
            "(e.g. 'remember when we discussed X', 'what were those plans from last month') "
            "AND grep_page('system/history', ...) did not have enough detail. "
            "Do not call speculatively — check wiki pages and system/history first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or phrase to search for in past messages",
                }
            },
            "required": ["query"],
        },
    },
},
```

- [ ] **Step 5: Add dispatch case to `_execute_tool`**

In `_execute_tool`, add after the `grep_page` case (before `move_page`):

```python
if name == "search_chat_history":
    return await self.search_chat_history(
        args["query"],
        context_window_chars=args.get("context_window_chars", 2000),
    )
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
docker compose run --rm api pytest tests/test_chat_history_search.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add api/app/agents/tools.py tests/test_chat_history_search.py
git commit -m "feat(tools): add search_chat_history tool with char-windowed excerpts"
```

---

## Task 2: Wire query agent — new tools + prompt updates

**Files:**
- Modify: `api/app/agents/query_agent.py`
- Modify: `api/app/agents/prompts/query.md`

- [ ] **Step 1: Update `query_agent.py`**

Replace:

```python
READ_ONLY_TOOLS = ["list_pages", "search_pages", "read_page", "grep_page"]
```

With:

```python
QUERY_TOOLS = [
    "list_pages",
    "search_pages",
    "read_page",
    "grep_page",
    "search_chat_history",
    "write_page",
    "create_page",
    "append_to_page",
    "patch_page",
]
```

Replace both occurrences of `READ_ONLY_TOOLS` with `QUERY_TOOLS` in the file (there will be one in `tool_defs = tools.as_litellm_tools(allowed=READ_ONLY_TOOLS)`).

- [ ] **Step 2: Replace `query.md` content**

Replace the entire contents of `api/app/agents/prompts/query.md` with:

```markdown
You are a knowledgeable assistant with access to the user's personal wiki.

A `<user_context>` block may appear above these instructions containing what the wiki knows about the user. Use it to personalise your answers without being asked.

## Answering questions

1. Call read_page("meta/index") first to see the full wiki structure and find relevant pages.
2. Use search_pages() to narrow down if needed.
3. Use read_page() to read up to 5 of the most relevant pages in full.
4. If the user references something that might have been discussed before, use grep_page("system/history", <keyword>) to search past session summaries.
5. Answer based on what you find. Cite pages using their full slug: [[people/alice-jones]].
6. If the wiki doesn't contain the answer, say so clearly.

## Searching past conversations

Use search_chat_history() only when:
- The user explicitly references a past conversation ("remember when we discussed X", "what were those plans from last month", "we talked about this before"), AND
- grep_page("system/history", ...) does not contain enough detail.

Do not call search_chat_history speculatively or before checking wiki pages and system/history first — it is expensive and should be a last resort.

## Writing to the wiki

You may write to the wiki mid-conversation when you encounter something genuinely durable — a concrete plan, a decision, a fact or preference worth keeping permanently. Use judgment: not every conversation warrants a save. When you do save something, briefly mention it in your reply: "I've saved this to [[trips/paris-road-trip]]."

Only write when information has reached a natural conclusion or the user explicitly asks you to save it. Do not create pages for fluid or half-formed ideas — save the settled version, not the draft.

## Recent wiki changes

To see what has been added or changed recently in the wiki, call read_page("system/changelog"). Check it when the user asks what has changed or what was recently added.
```

- [ ] **Step 3: Verify the agent still imports correctly**

```bash
docker compose run --rm api python -c "from app.agents.query_agent import run; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add api/app/agents/query_agent.py api/app/agents/prompts/query.md
git commit -m "feat(query-agent): unlock write tools and search_chat_history, update prompt"
```

---

## Task 3: Atomic `_append_changelog` method

**Files:**
- Modify: `api/app/agents/tools.py`
- Create: `tests/test_changelog.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_changelog.py`:

```python
import pytest
from sqlalchemy import select
from app.agents.tools import AgentTools
from app.models import Page


@pytest.fixture
def tools(db_session, workspace_id):
    return AgentTools(session=db_session, workspace_id=workspace_id, broadcaster=None)


@pytest.mark.asyncio
async def test_append_changelog_creates_page_on_first_call(tools, db_session, workspace_id):
    await tools._append_changelog("created", "[[trips/paris]]")

    result = await db_session.execute(
        select(Page).where(
            Page.slug == "system/changelog", Page.workspace_id == workspace_id
        )
    )
    page = result.scalar_one_or_none()
    assert page is not None
    assert "| When | Action | Page |" in page.body_md
    assert "created" in page.body_md
    assert "trips/paris" in page.body_md


@pytest.mark.asyncio
async def test_append_changelog_appends_subsequent_calls(tools, db_session, workspace_id):
    await tools._append_changelog("created", "[[trips/paris]]")
    await tools._append_changelog("updated", "[[trips/paris]]")

    result = await db_session.execute(
        select(Page).where(
            Page.slug == "system/changelog", Page.workspace_id == workspace_id
        )
    )
    page = result.scalar_one_or_none()
    assert page.body_md.count("trips/paris") == 2
    assert "created" in page.body_md
    assert "updated" in page.body_md


@pytest.mark.asyncio
async def test_append_changelog_deleted_entry(tools, db_session, workspace_id):
    await tools._append_changelog("deleted", "notes/scratch")

    result = await db_session.execute(
        select(Page).where(
            Page.slug == "system/changelog", Page.workspace_id == workspace_id
        )
    )
    page = result.scalar_one_or_none()
    assert "deleted" in page.body_md
    assert "notes/scratch" in page.body_md


@pytest.mark.asyncio
async def test_append_changelog_moved_entry(tools, db_session, workspace_id):
    await tools._append_changelog("moved", "[[archive/old]] ← [[projects/old]]")

    result = await db_session.execute(
        select(Page).where(
            Page.slug == "system/changelog", Page.workspace_id == workspace_id
        )
    )
    page = result.scalar_one_or_none()
    assert "moved" in page.body_md
    assert "archive/old" in page.body_md
    assert "projects/old" in page.body_md
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose run --rm api pytest tests/test_changelog.py -v
```

Expected: `AttributeError: 'AgentTools' object has no attribute '_append_changelog'`

- [ ] **Step 3: Add `_append_changelog` to `AgentTools`**

Add the method to `api/app/agents/tools.py` (after `_append_deleted_log`, before `_do_delete_page`):

```python
async def _append_changelog(self, action: str, page_display: str) -> None:
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    row = f"\n| {ts} | {action} | {page_display} |"

    result = await self.session.execute(
        text(
            "UPDATE pages SET body_md = body_md || :row "
            "WHERE slug = 'system/changelog' AND workspace_id = :workspace_id "
            "RETURNING id"
        ),
        {"row": row, "workspace_id": self.workspace_id},
    )
    updated = result.fetchone()
    await self.session.commit()

    if not updated:
        header = "# Wiki Changelog\n\n| When | Action | Page |\n| --- | --- | --- |"
        changelog_page = Page(
            workspace_id=self.workspace_id,
            slug="system/changelog",
            title="Wiki Changelog",
            body_md=header + row,
            summary="Audit trail of wiki page changes",
        )
        self.session.add(changelog_page)
        await self.session.commit()
```

Note: `datetime` is already imported at the top of `tools.py` as `from datetime import datetime`. The `text` import was added in Task 1.

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose run --rm api pytest tests/test_changelog.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/agents/tools.py tests/test_changelog.py
git commit -m "feat(tools): add atomic _append_changelog via SQL UPDATE"
```

---

## Task 4: Hook changelog into write/delete/move

**Files:**
- Modify: `api/app/agents/tools.py`
- Modify: `tests/test_changelog.py` (add hook tests)

- [ ] **Step 1: Add failing tests for hooks**

Append to `tests/test_changelog.py`:

```python
@pytest.mark.asyncio
async def test_write_page_logs_to_changelog(db_session, workspace_id):
    tools = AgentTools(session=db_session, workspace_id=workspace_id, broadcaster=None)
    await tools.write_page("trips/paris", "# Paris\n\nRoad trip notes.", summary="Paris trip")

    result = await db_session.execute(
        select(Page).where(
            Page.slug == "system/changelog", Page.workspace_id == workspace_id
        )
    )
    page = result.scalar_one_or_none()
    assert page is not None
    assert "trips/paris" in page.body_md


@pytest.mark.asyncio
async def test_write_page_excluded_slugs_not_logged(db_session, workspace_id):
    tools = AgentTools(session=db_session, workspace_id=workspace_id, broadcaster=None)
    await tools.write_page("system/memory", "# Memory\n\nSome facts.")

    result = await db_session.execute(
        select(Page).where(
            Page.slug == "system/changelog", Page.workspace_id == workspace_id
        )
    )
    # system/memory writes must not create a changelog entry
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_page_logs_to_changelog(db_session, workspace_id):
    tools = AgentTools(session=db_session, workspace_id=workspace_id, broadcaster=None)
    await tools.write_page("notes/scratch", "# Scratch\n\nTemp.")
    await tools.delete_page("notes/scratch")

    result = await db_session.execute(
        select(Page).where(
            Page.slug == "system/changelog", Page.workspace_id == workspace_id
        )
    )
    page = result.scalar_one_or_none()
    assert page is not None
    assert "deleted" in page.body_md
    assert "notes/scratch" in page.body_md


@pytest.mark.asyncio
async def test_move_page_logs_single_moved_entry(db_session, workspace_id):
    tools = AgentTools(session=db_session, workspace_id=workspace_id, broadcaster=None)
    await tools.write_page("projects/old", "# Old\n\nContent.")
    # Reset changelog so we have a clean slate for the move
    result = await db_session.execute(
        select(Page).where(
            Page.slug == "system/changelog", Page.workspace_id == workspace_id
        )
    )
    changelog = result.scalar_one_or_none()
    if changelog:
        changelog.body_md = "# Wiki Changelog\n\n| When | Action | Page |\n| --- | --- | --- |"
        await db_session.commit()

    await tools.move_page("projects/old", "archive/old")

    result = await db_session.execute(
        select(Page).where(
            Page.slug == "system/changelog", Page.workspace_id == workspace_id
        )
    )
    page = result.scalar_one_or_none()
    assert page is not None
    assert "moved" in page.body_md
    assert "archive/old" in page.body_md
    assert "projects/old" in page.body_md
    # Should have exactly one "moved" entry, not a "created" entry from the internal write
    assert page.body_md.count("| moved |") == 1
    assert "| created |" not in page.body_md.split("# Wiki Changelog")[1]
```

- [ ] **Step 2: Run failing tests**

```bash
docker compose run --rm api pytest tests/test_changelog.py::test_write_page_logs_to_changelog tests/test_changelog.py::test_write_page_excluded_slugs_not_logged tests/test_changelog.py::test_delete_page_logs_to_changelog tests/test_changelog.py::test_move_page_logs_single_moved_entry -v
```

Expected: all 4 FAIL (changelog not yet hooked in).

- [ ] **Step 3: Add `_suppress_changelog` flag to `__init__`**

In `AgentTools.__init__`, after `self._suppress_agent_writing_sse = False`, add:

```python
self._suppress_changelog: bool = False
```

- [ ] **Step 4: Hook into `write_page`**

At the end of `write_page`, after `await self.update_index(slug, page.title, page.summary)`, add:

```python
if not self._suppress_changelog and slug not in _CHANGELOG_EXCLUDED:
    action = "updated" if (page and not getattr(page, '_is_new', False)) else "created"
    await self._append_changelog(action, f"[[{slug}]]")
```

Wait — there's a cleaner way to track whether the page was new. Before the `if page:` / `else:` block in `write_page`, capture:

```python
was_new = page is None
```

Then at the end:

```python
if not self._suppress_changelog and slug not in _CHANGELOG_EXCLUDED:
    await self._append_changelog("created" if was_new else "updated", f"[[{slug}]]")
```

The full updated `write_page` should look like this — replace the existing method:

```python
async def write_page(
    self, slug: str, body_md: str, summary: str = "", title: str | None = None
) -> str:
    if not self._suppress_agent_writing_sse:
        await self._broadcast({"event": "agent:writing", "slug": slug})
    result = await self.session.execute(
        select(Page).where(Page.slug == slug, Page.workspace_id == self.workspace_id)
    )
    page = result.scalar_one_or_none()
    was_new = page is None
    if page:
        self.session.add(Revision(page_id=page.id, body_md=page.body_md))
        page.body_md = body_md
        if title:
            page.title = title
        page.summary = summary or page.summary
        page.updated_at = datetime.utcnow()
        await sync_links(self.session, page)
        self.session.add(
            ActivityLog(
                workspace_id=self.workspace_id,
                event_type="page_updated",
                payload={"slug": slug},
            )
        )
    else:
        page = Page(
            workspace_id=self.workspace_id,
            slug=slug,
            title=title or slug.replace("-", " ").title(),
            body_md=body_md,
            summary=summary,
        )
        self.session.add(page)
        await self.session.flush()
        await sync_links(self.session, page)
        self.session.add(
            ActivityLog(
                workspace_id=self.workspace_id,
                event_type="page_created",
                payload={"slug": slug},
            )
        )
    await self.session.commit()
    await self.session.refresh(page)
    await self.update_index(slug, page.title, page.summary)
    if not self._suppress_changelog and slug not in _CHANGELOG_EXCLUDED:
        await self._append_changelog("created" if was_new else "updated", f"[[{slug}]]")
    return f"Page '{slug}' saved."
```

- [ ] **Step 5: Hook into `delete_page`**

In `delete_page`, after `await self._broadcast(...)`, add:

```python
if not self._suppress_changelog:
    await self._append_changelog("deleted", slug)
```

The full updated `delete_page`:

```python
async def delete_page(self, slug: str) -> str:
    try:
        title = await self._do_delete_page(slug)
    except ValueError as exc:
        return str(exc)
    await self._remove_from_index(slug)
    await self._append_deleted_log(slug, title)
    await self._broadcast({"event": "agent:deleting", "slug": slug})
    if not self._suppress_changelog:
        await self._append_changelog("deleted", slug)
    return f"Page '{slug}' deleted."
```

- [ ] **Step 6: Hook into `move_page` (suppress internal + log single entry)**

Replace the `move_page` method:

```python
async def move_page(self, old_slug: str, new_slug: str) -> str:
    if not _SLUG_RE.match(new_slug):
        return (
            f"Invalid new_slug '{new_slug}': use lowercase path segments with hyphens "
            f"(e.g. people/alice-jones)."
        )
    self._suppress_changelog = True
    try:
        await self._do_move_page(old_slug, new_slug)
    except ValueError as exc:
        return str(exc)
    finally:
        self._suppress_changelog = False
    await self._broadcast({"event": "agent:moving", "from": old_slug, "to": new_slug})
    await self._append_changelog("moved", f"[[{new_slug}]] ← [[{old_slug}]]")
    return f"Page moved from '{old_slug}' to '{new_slug}'."
```

- [ ] **Step 7: Suppress changelog during `move_folder`**

In `move_folder`, wrap the loop with suppress (the `_suppress_agent_writing_sse` pattern already exists there). After `self._suppress_agent_writing_sse = True`, also set `self._suppress_changelog = True`. In the `finally` block, also reset `self._suppress_changelog = False`. No need to log individual folder-move entries to changelog (the individual page moves inside are suppressed; add one folder-level entry after):

```python
self._suppress_agent_writing_sse = True
self._suppress_changelog = True
try:
    for page, new_slug in zip(pages, new_slugs, strict=True):
        await self._do_move_page(page.slug, new_slug)
finally:
    self._suppress_agent_writing_sse = False
    self._suppress_changelog = False

count = len(pages)
await self._broadcast(
    {
        "event": "agent:moved_folder",
        "from": old_prefix,
        "to": new_prefix,
        "count": count,
    }
)
await self._append_changelog("moved folder", f"`{old_prefix}/` → `{new_prefix}/` ({count} pages)")
return f"Moved {count} pages from '{old_prefix}/' to '{new_prefix}/'."
```

- [ ] **Step 8: Run all changelog tests**

```bash
docker compose run --rm api pytest tests/test_changelog.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 9: Run full test suite to check for regressions**

```bash
docker compose run --rm api pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 10: Commit**

```bash
git add api/app/agents/tools.py tests/test_changelog.py
git commit -m "feat(tools): hook system/changelog into write/delete/move with suppress flag"
```

---

## Task 5: Strip `chat_monitor.md`

**Files:**
- Modify: `api/app/agents/prompts/chat_monitor.md`

- [ ] **Step 1: Replace file contents**

Replace the entire contents of `api/app/agents/prompts/chat_monitor.md` with:

```markdown
You are a background agent that reads new chat messages and maintains the user's wiki.

You receive only the *new* messages since the last time you ran — not the full conversation history.

## Responsibilities

### 1. Update `system/memory`
This page is the wiki's persistent understanding of the user — their preferences, background, recurring topics, and facts worth remembering across sessions.

- Call `read_page("system/memory")` first to see what is already known.
- If the new messages reveal something new and durable about the user (preferences, facts, context about their life or work), update the page with `write_page("system/memory", ...)`.
- Do NOT update it for casual or ephemeral content.
- If nothing new is learned about the user, leave `system/memory` alone.

### 2. Upsert `system/history`
This page is a chronological log of session summaries. Each session has exactly one entry.

Entry format:
```
## YYYY-MM-DD · {session_id}
**Summary:** One or two sentences on what was discussed.
**Notes:**
- Key decisions, facts, or outcomes worth recalling later
```

- Call `grep_page("system/history", "{session_id}", context_lines=0)` to check if an entry for this session already exists.
- If **no entry exists**: call `append_to_page("system/history", <new entry block>)`.
- If **entry exists**: call `read_page("system/history")` to get the full content, then call `patch_page("system/history", <old entry block>, <updated entry block>)` with the improved summary.
- If `patch_page` returns a "not found" error, fall back to `append_to_page`.

## Order of operations
1. `read_page("system/memory")` — understand what is already known about the user
2. Process new messages
3. Update `system/memory` if needed
4. Upsert `system/history` entry for this session

If neither responsibility applies, do nothing.
```

- [ ] **Step 2: Verify Python still loads the prompt**

```bash
docker compose run --rm api python -c "from app.agents.chat_monitor import SYSTEM_PROMPT; print(len(SYSTEM_PROMPT), 'chars')"
```

Expected: prints a char count without error.

- [ ] **Step 3: Commit**

```bash
git add api/app/agents/prompts/chat_monitor.md
git commit -m "refactor(chat-monitor): remove auto wiki-save, keep memory and history only"
```

---

## Task 6: Frontend "Recent Changes" tab

**Files:**
- Modify: `frontend/src/components/ActivityLog.tsx`

- [ ] **Step 1: Add "Changes" tab to `ActivityLog.tsx`**

Replace the `useState` initialiser for `tab` and add the new tab button and panel. The full updated file:

```tsx
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getActivity } from '../api/client'
import type { QueueState, QueueStatus } from '../state/ingestQueue'

const labels: Record<string, string> = {
  page_created: 'Page created',
  page_updated: 'Page updated',
  source_ingested: 'Source ingested',
  chat_ingested: 'Saved from chat',
  chat_message: 'Chat message',
}

const CHANGE_EVENTS = new Set(['page_created', 'page_updated', 'page_deleted'])

const CHANGE_ACTION_LABEL: Record<string, string> = {
  page_created: 'Created',
  page_updated: 'Updated',
  page_deleted: 'Deleted',
}

const CHANGE_ACTION_COLOR: Record<string, string> = {
  page_created: '#3fb950',
  page_updated: '#58a6ff',
  page_deleted: '#f85149',
}

const QUEUE_STATUS_LABEL: Record<QueueStatus, string> = {
  pending: 'Pending',
  uploading: 'Uploading…',
  queued: 'Queued…',
  converting: 'Converting…',
  processing: 'Processing…',
  done: 'Done',
  error: 'Error',
}

const QUEUE_STATUS_COLOR: Record<QueueStatus, string> = {
  pending: '#8b949e',
  uploading: '#58a6ff',
  queued: '#a371f7',
  converting: '#d29922',
  processing: '#d29922',
  done: '#3fb950',
  error: '#f85149',
}

export default function ActivityLog({
  onClose,
  queue,
  onClearQueue,
}: {
  onClose: () => void
  queue: QueueState
  onClearQueue: () => void
}) {
  const [tab, setTab] = useState<'activity' | 'changes' | 'queue'>('activity')
  const { data: events = [] } = useQuery<{ id: string; event_type: string; payload: Record<string, unknown>; created_at: string }[]>({
    queryKey: ['activity'],
    queryFn: () => getActivity(),
    refetchInterval: 5000,
  })

  const changeEvents = events.filter(e => CHANGE_EVENTS.has(e.event_type))

  const queueSortedNewestFirst = [...queue.items].sort((a, b) =>
    a.createdAt < b.createdAt ? 1 : -1,
  )

  const tabBtn = (id: typeof tab, label: string) => (
    <button
      type="button"
      onClick={() => setTab(id)}
      style={{
        padding: '4px 12px',
        background: tab === id ? '#238636' : '#21262d',
        border: '1px solid #30363d',
        borderRadius: 6,
        color: '#e6edf3',
        cursor: 'pointer',
        fontSize: 12,
      }}
    >
      {label}
    </button>
  )

  return (
    <div style={{ position: 'fixed', right: 0, top: 0, bottom: 0, width: 360, background: '#161b22',
      borderLeft: '1px solid #30363d', zIndex: 50, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '12px 16px', borderBottom: '1px solid #30363d', gap: 12 }}>
        <div style={{ display: 'flex', gap: 4 }}>
          {tabBtn('activity', 'Activity')}
          {tabBtn('changes', 'Changes')}
          {tabBtn('queue', 'Queue')}
        </div>
        <button onClick={onClose} type="button" style={{ background: 'none', border: 'none', color: '#8b949e',
          cursor: 'pointer', fontSize: 18, flexShrink: 0 }}>×</button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        {tab === 'activity' && (
          <>
            {events.map(e => (
              <div key={e.id} style={{ marginBottom: 12, padding: '8px 12px', background: '#0d1117',
                borderRadius: 6, border: '1px solid #21262d' }}>
                <div style={{ fontSize: 12, color: '#3fb950', marginBottom: 4 }}>
                  {labels[e.event_type] || e.event_type}
                </div>
                <div style={{ fontSize: 11, color: '#8b949e' }}>
                  {e.payload.slug ? `[[${e.payload.slug}]]` : ''}
                  {e.payload.pages_touched ? ` → ${(e.payload.pages_touched as string[]).join(', ')}` : ''}
                </div>
                <div style={{ fontSize: 10, color: '#484f58', marginTop: 4 }}>
                  {new Date(e.created_at).toLocaleString()}
                </div>
              </div>
            ))}
            {events.length === 0 && (
              <div style={{ color: '#8b949e', fontSize: 13, textAlign: 'center', marginTop: 40 }}>
                No activity yet. Ingest something!
              </div>
            )}
          </>
        )}
        {tab === 'changes' && (
          <>
            {changeEvents.map(e => (
              <div key={e.id} style={{ marginBottom: 12, padding: '8px 12px', background: '#0d1117',
                borderRadius: 6, border: '1px solid #21262d' }}>
                <div style={{ fontSize: 12, color: CHANGE_ACTION_COLOR[e.event_type] ?? '#8b949e', marginBottom: 4 }}>
                  {CHANGE_ACTION_LABEL[e.event_type] ?? e.event_type}
                </div>
                <div style={{ fontSize: 11, color: '#8b949e', fontFamily: 'monospace' }}>
                  {e.payload.slug ? `[[${e.payload.slug}]]` : '—'}
                </div>
                <div style={{ fontSize: 10, color: '#484f58', marginTop: 4 }}>
                  {new Date(e.created_at).toLocaleString()}
                </div>
              </div>
            ))}
            {changeEvents.length === 0 && (
              <div style={{ color: '#8b949e', fontSize: 13, textAlign: 'center', marginTop: 40 }}>
                No wiki changes yet.
              </div>
            )}
          </>
        )}
        {tab === 'queue' && (
          <>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
              <button
                type="button"
                onClick={onClearQueue}
                style={{
                  padding: '6px 12px',
                  background: '#21262d',
                  border: '1px solid #30363d',
                  borderRadius: 6,
                  color: '#e6edf3',
                  cursor: 'pointer',
                  fontSize: 12,
                }}
              >
                Clear
              </button>
            </div>
            {queueSortedNewestFirst.map(item => (
              <div
                key={item.id}
                style={{
                  marginBottom: 12,
                  padding: '10px 12px',
                  background: '#0d1117',
                  borderRadius: 6,
                  border: '1px solid #21262d',
                  display: 'flex',
                  justifyContent: 'space-between',
                  gap: 8,
                  alignItems: 'flex-start',
                }}
              >
                <div style={{ overflow: 'hidden', flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: '#e6edf3', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {item.fileName}
                  </div>
                  <div style={{ fontSize: 10, color: '#484f58', marginTop: 4 }}>
                    {new Date(item.createdAt).toLocaleString()}
                  </div>
                </div>
                <span
                  style={{
                    fontSize: 11,
                    color: QUEUE_STATUS_COLOR[item.status] ?? '#8b949e',
                    flexShrink: 0,
                  }}
                >
                  {QUEUE_STATUS_LABEL[item.status]}
                </span>
              </div>
            ))}
            {queueSortedNewestFirst.length === 0 && (
              <div style={{ color: '#8b949e', fontSize: 13, textAlign: 'center', marginTop: 40 }}>
                No ingest queue items yet.
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: build succeeds with no TypeScript errors.

- [ ] **Step 3: Manually verify in browser**

Start the dev stack with `docker compose up` and open the app. Open the ActivityLog panel, click "Changes". Verify the tab renders and shows an empty state message. Create a wiki page and verify the Changes tab shows a "Created" entry with the slug, colour-coded green.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ActivityLog.tsx
git commit -m "feat(ui): add Recent Changes tab to ActivityLog panel"
```
