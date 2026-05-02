# User Memory & Session History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the chat agent persistent memory of the user and a searchable chronological history of past sessions, maintained automatically by the chat monitor.

**Architecture:** Three new tools (`append_to_page`, `patch_page`, `grep_page`) are added to `AgentTools`. `ChatSession` gains a `last_monitored_message_id` cursor column. The chat monitor uses delta-based processing (bail if delta < 4 new messages) and maintains `system/memory` and `system/history` wiki pages. The query agent reads `system/memory` at startup for personalisation and gains access to `grep_page` for history lookups.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic, litellm, pytest-asyncio

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `api/app/models.py` | Add `last_monitored_message_id` to `ChatSession` |
| Create | `api/alembic/versions/<rev>_add_monitor_cursor.py` | Migration for new column |
| Modify | `api/app/agents/tools.py` | Add `append_to_page`, `patch_page`, `grep_page` methods + register in `as_litellm_tools()` and `dispatch()` |
| Create | `api/tests/test_memory_tools.py` | Unit tests for the three new tools |
| Modify | `api/app/agents/chat_monitor.py` | Cursor load, delta slice, threshold bail-out, system/memory + system/history upsert |
| Modify | `api/app/agents/prompts/chat_monitor.md` | Describe memory/history responsibilities and new tools |
| Modify | `api/app/agents/query_agent.py` | Inject `system/memory` into system prompt; add `grep_page` to allowed tools |
| Modify | `api/app/agents/prompts/query.md` | Reference the injected user context block |

---

## Task 1: Add `last_monitored_message_id` to `ChatSession`

**Files:**
- Modify: `api/app/models.py`
- Create: `api/alembic/versions/<rev>_add_monitor_cursor.py`

- [ ] **Step 1: Add the column to the model**

In `api/app/models.py`, find `class ChatSession` and add the nullable FK column:

```python
class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_monitored_message_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("chat_messages.id"), nullable=True, default=None
    )

    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session")
```

- [ ] **Step 2: Generate the migration**

```bash
docker compose run --rm api alembic revision --autogenerate -m "add_monitor_cursor"
```

Verify the generated file in `api/alembic/versions/` contains an `add_column` for `last_monitored_message_id` on `chat_sessions`.

- [ ] **Step 3: Apply the migration**

```bash
docker compose run --rm api alembic upgrade head
```

Expected: `Running upgrade ... -> <rev>, add_monitor_cursor`

- [ ] **Step 4: Commit**

```bash
git add api/app/models.py api/alembic/versions/
git commit -m "feat: add last_monitored_message_id cursor to ChatSession"
```

---

## Task 2: Add `append_to_page` tool

**Files:**
- Modify: `api/app/agents/tools.py`
- Create: `api/tests/test_memory_tools.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_memory_tools.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools import AgentTools


@pytest.fixture
def session():
    s = AsyncMock(spec=AsyncSession)
    s.add = MagicMock()
    s.delete = MagicMock()
    return s


@pytest.fixture
def tools(session):
    return AgentTools(session=session, workspace_id="ws-1", broadcaster=None)


@pytest.mark.asyncio
async def test_append_to_existing_page(tools):
    tools.read_page = AsyncMock(return_value="# Existing\n\nOld content.")
    tools.write_page = AsyncMock(return_value="Page 'system/history' saved.")

    result = await tools.append_to_page("system/history", "## New Entry\nSome text.")

    tools.write_page.assert_called_once()
    written_body = tools.write_page.call_args[0][1]
    assert "Old content." in written_body
    assert "## New Entry" in written_body
    assert written_body.index("Old content.") < written_body.index("## New Entry")


@pytest.mark.asyncio
async def test_append_to_missing_page_creates_it(tools):
    tools.read_page = AsyncMock(return_value="[Page 'system/history' not found]")
    tools.write_page = AsyncMock(return_value="Page 'system/history' saved.")

    await tools.append_to_page("system/history", "## First Entry\nContent.")

    written_body = tools.write_page.call_args[0][1]
    assert written_body == "## First Entry\nContent."
```

- [ ] **Step 2: Run to verify failure**

```bash
docker compose run --rm api pytest tests/test_memory_tools.py -v
```

Expected: `AttributeError: 'AgentTools' object has no attribute 'append_to_page'`

- [ ] **Step 3: Implement `append_to_page` in `tools.py`**

Add this method to `AgentTools`, after `write_page`:

```python
async def append_to_page(self, slug: str, content: str) -> str:
    existing = await self.read_page(slug)
    if existing.startswith(f"[Page '{slug}' not found]"):
        new_body = content
    else:
        new_body = existing.rstrip() + "\n\n" + content
    return await self.write_page(slug, new_body)
```

- [ ] **Step 4: Register in `as_litellm_tools()`**

In the `all_tools` list inside `as_litellm_tools()`, add after the `create_page` entry:

```python
{
    "type": "function",
    "function": {
        "name": "append_to_page",
        "description": "Append content to the end of an existing wiki page. Creates the page if it does not exist. Use this to add new entries to log-style pages like system/history.",
        "parameters": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Page slug"},
                "content": {"type": "string", "description": "Markdown content to append"},
            },
            "required": ["slug", "content"],
        },
    },
},
```

- [ ] **Step 5: Register in `dispatch()`**

Add after the `create_page` dispatch block:

```python
if name == "append_to_page":
    return await self.append_to_page(args["slug"], args["content"])
```

- [ ] **Step 6: Run tests to verify passing**

```bash
docker compose run --rm api pytest tests/test_memory_tools.py::test_append_to_existing_page tests/test_memory_tools.py::test_append_to_missing_page_creates_it -v
```

Expected: both PASS

- [ ] **Step 7: Commit**

```bash
git add api/app/agents/tools.py api/tests/test_memory_tools.py
git commit -m "feat: add append_to_page tool"
```

---

## Task 3: Add `patch_page` tool

**Files:**
- Modify: `api/app/agents/tools.py`
- Modify: `api/tests/test_memory_tools.py`

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_memory_tools.py`:

```python
@pytest.mark.asyncio
async def test_patch_page_replaces_unique_match(tools):
    tools.read_page = AsyncMock(return_value="## 2026-05-01 · abc\nOld summary.\n\n## 2026-05-02 · def\nOther.")
    tools.write_page = AsyncMock(return_value="Page 'system/history' saved.")

    result = await tools.patch_page("system/history", "Old summary.", "New summary.")

    written_body = tools.write_page.call_args[0][1]
    assert "New summary." in written_body
    assert "Old summary." not in written_body


@pytest.mark.asyncio
async def test_patch_page_fails_on_not_found(tools):
    tools.read_page = AsyncMock(return_value="Some content without the target.")
    tools.write_page = AsyncMock()

    result = await tools.patch_page("system/history", "missing text", "replacement")

    assert result == "patch failed: old_text not found in 'system/history'"
    tools.write_page.assert_not_called()


@pytest.mark.asyncio
async def test_patch_page_fails_on_multiple_matches(tools):
    tools.read_page = AsyncMock(return_value="duplicate\nduplicate\n")
    tools.write_page = AsyncMock()

    result = await tools.patch_page("system/history", "duplicate", "replacement")

    assert result == "patch failed: old_text matches 2 locations in 'system/history', be more specific"
    tools.write_page.assert_not_called()


@pytest.mark.asyncio
async def test_patch_page_fails_on_missing_page(tools):
    tools.read_page = AsyncMock(return_value="[Page 'system/history' not found]")
    tools.write_page = AsyncMock()

    result = await tools.patch_page("system/history", "anything", "replacement")

    assert result == "patch failed: page 'system/history' not found"
    tools.write_page.assert_not_called()
```

- [ ] **Step 2: Run to verify failure**

```bash
docker compose run --rm api pytest tests/test_memory_tools.py -k "patch" -v
```

Expected: `AttributeError: 'AgentTools' object has no attribute 'patch_page'`

- [ ] **Step 3: Implement `patch_page` in `tools.py`**

Add after `append_to_page`:

```python
async def patch_page(self, slug: str, old_text: str, new_text: str) -> str:
    existing = await self.read_page(slug)
    if existing.startswith(f"[Page '{slug}' not found]"):
        return f"patch failed: page '{slug}' not found"
    count = existing.count(old_text)
    if count == 0:
        return f"patch failed: old_text not found in '{slug}'"
    if count > 1:
        return f"patch failed: old_text matches {count} locations in '{slug}', be more specific"
    new_body = existing.replace(old_text, new_text, 1)
    return await self.write_page(slug, new_body)
```

- [ ] **Step 4: Register in `as_litellm_tools()`**

Add after the `append_to_page` tool definition:

```python
{
    "type": "function",
    "function": {
        "name": "patch_page",
        "description": (
            "Surgically replace an exact string in a wiki page. "
            "You must read_page first to know the exact text to target. "
            "Returns an error if old_text is not found or matches multiple locations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Page slug"},
                "old_text": {"type": "string", "description": "Exact string to replace (must be unique in the page)"},
                "new_text": {"type": "string", "description": "Replacement string"},
            },
            "required": ["slug", "old_text", "new_text"],
        },
    },
},
```

- [ ] **Step 5: Register in `dispatch()`**

```python
if name == "patch_page":
    return await self.patch_page(args["slug"], args["old_text"], args["new_text"])
```

- [ ] **Step 6: Run tests**

```bash
docker compose run --rm api pytest tests/test_memory_tools.py -k "patch" -v
```

Expected: all 4 PASS

- [ ] **Step 7: Commit**

```bash
git add api/app/agents/tools.py api/tests/test_memory_tools.py
git commit -m "feat: add patch_page tool with explicit failure messages"
```

---

## Task 4: Add `grep_page` tool

**Files:**
- Modify: `api/app/agents/tools.py`
- Modify: `api/tests/test_memory_tools.py`

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_memory_tools.py`:

```python
@pytest.mark.asyncio
async def test_grep_page_literal_match(tools):
    tools.read_page = AsyncMock(return_value=(
        "line 1\nline 2\nfoo bar baz\nline 4\nline 5"
    ))

    result = await tools.grep_page("system/history", "foo bar", context_lines=1)

    assert "foo bar baz" in result
    assert "line 2" in result  # context before
    assert "line 4" in result  # context after


@pytest.mark.asyncio
async def test_grep_page_case_insensitive(tools):
    tools.read_page = AsyncMock(return_value="Hello World\nnothing\n")

    result = await tools.grep_page("system/history", "hello world")

    assert "Hello World" in result


@pytest.mark.asyncio
async def test_grep_page_regex_match(tools):
    tools.read_page = AsyncMock(return_value=(
        "## 2026-04-01 · abc\nApril session.\n"
        "## 2026-05-01 · def\nMay session.\n"
    ))

    result = await tools.grep_page("system/history", r"## 2026-04-.*", context_lines=1, regex=True)

    assert "## 2026-04-01" in result
    assert "## 2026-05-01" not in result


@pytest.mark.asyncio
async def test_grep_page_no_matches(tools):
    tools.read_page = AsyncMock(return_value="Some content here.")

    result = await tools.grep_page("system/history", "nonexistent")

    assert result == "no matches"


@pytest.mark.asyncio
async def test_grep_page_invalid_regex(tools):
    tools.read_page = AsyncMock(return_value="Some content.")

    result = await tools.grep_page("system/history", "[invalid", regex=True)

    assert result.startswith("grep failed: invalid pattern:")


@pytest.mark.asyncio
async def test_grep_page_missing_page(tools):
    tools.read_page = AsyncMock(return_value="[Page 'system/history' not found]")

    result = await tools.grep_page("system/history", "anything")

    assert result == "page not found: 'system/history'"


@pytest.mark.asyncio
async def test_grep_page_multiple_matches_separated(tools):
    tools.read_page = AsyncMock(return_value=(
        "a\nfoo\nb\nc\nfoo\nd"
    ))

    result = await tools.grep_page("system/history", "foo", context_lines=1)

    assert "---" in result  # separator between matches
```

- [ ] **Step 2: Run to verify failure**

```bash
docker compose run --rm api pytest tests/test_memory_tools.py -k "grep" -v
```

Expected: `AttributeError: 'AgentTools' object has no attribute 'grep_page'`

- [ ] **Step 3: Implement `grep_page` in `tools.py`**

Add after `patch_page` (note: `re` is already imported at the top of `tools.py`):

```python
async def grep_page(self, slug: str, query: str, context_lines: int = 5, regex: bool = False) -> str:
    content = await self.read_page(slug)
    if content.startswith(f"[Page '{slug}' not found]"):
        return f"page not found: '{slug}'"

    if regex:
        try:
            pattern = re.compile(query, re.IGNORECASE)
            match_fn = lambda line: bool(pattern.search(line))
        except re.error as exc:
            return f"grep failed: invalid pattern: {exc}"
    else:
        match_fn = lambda line: query.lower() in line.lower()

    lines = content.split("\n")
    matched_indices = [i for i, line in enumerate(lines) if match_fn(line)]

    if not matched_indices:
        return "no matches"

    results = []
    for idx in matched_indices:
        start = max(0, idx - context_lines)
        end = min(len(lines), idx + context_lines + 1)
        results.append("\n".join(lines[start:end]))

    return "\n---\n".join(results)
```

- [ ] **Step 4: Register in `as_litellm_tools()`**

Add after the `patch_page` tool definition:

```python
{
    "type": "function",
    "function": {
        "name": "grep_page",
        "description": (
            "Search within a wiki page for lines matching a query, returning each match "
            "with surrounding context lines. Use regex=true for pattern matching "
            "(e.g. '## 2026-04-.*' to find all April 2026 session headers)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Page slug to search within"},
                "query": {"type": "string", "description": "Search string or regex pattern"},
                "context_lines": {
                    "type": "integer",
                    "description": "Lines of context above and below each match (default 5)",
                    "default": 5,
                },
                "regex": {
                    "type": "boolean",
                    "description": "Treat query as a regex pattern (default false = case-insensitive literal match)",
                    "default": False,
                },
            },
            "required": ["slug", "query"],
        },
    },
},
```

- [ ] **Step 5: Register in `dispatch()`**

```python
if name == "grep_page":
    return await self.grep_page(
        args["slug"],
        args["query"],
        context_lines=args.get("context_lines", 5),
        regex=args.get("regex", False),
    )
```

- [ ] **Step 6: Run all memory tool tests**

```bash
docker compose run --rm api pytest tests/test_memory_tools.py -v
```

Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add api/app/agents/tools.py api/tests/test_memory_tools.py
git commit -m "feat: add grep_page tool with literal and regex search"
```

---

## Task 5: Chat monitor — cursor + delta threshold

**Files:**
- Modify: `api/app/agents/chat_monitor.py`

- [ ] **Step 1: Add the threshold constant and update imports**

At the top of `api/app/agents/chat_monitor.py`, add `MONITOR_THRESHOLD` and import `ChatSession`:

```python
import json
from pathlib import Path

import litellm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.assistant_message import assistant_message_for_litellm
from app.agents.tools import AgentTools
from app.config import settings
from app.models import ActivityLog, ChatMessage, ChatSession
from app.sse import broadcaster

_PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS / "chat_monitor.md").read_text()

MONITOR_THRESHOLD = 4
```

- [ ] **Step 2: Replace the message fetch at the top of `run()` with cursor-based delta logic**

Replace the existing start of `run()`:

```python
async def run(session_id: str, workspace_id: str, session: AsyncSession) -> None:
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    messages = result.scalars().all()
    if not messages:
        return
```

With:

```python
async def run(session_id: str, workspace_id: str, session: AsyncSession) -> None:
    # Load session for cursor
    session_result = await session.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    chat_session = session_result.scalar_one_or_none()
    if not chat_session:
        return

    # Fetch all messages then slice from cursor
    all_result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    all_messages = all_result.scalars().all()
    if not all_messages:
        return

    if chat_session.last_monitored_message_id:
        cursor_ids = [m.id for m in all_messages]
        try:
            cursor_idx = cursor_ids.index(chat_session.last_monitored_message_id)
            messages = all_messages[cursor_idx + 1:]
        except ValueError:
            messages = all_messages
    else:
        messages = all_messages

    if len(messages) < MONITOR_THRESHOLD:
        return
```

- [ ] **Step 3: Update the cursor at the end of `run()`**

The existing `run()` ends with a conditional commit inside `if pages_saved:`. Replace that entire block with one that always updates the cursor and conditionally logs activity:

```python
    chat_session.last_monitored_message_id = messages[-1].id
    session.add(chat_session)
    if pages_saved:
        session.add(
            ActivityLog(
                workspace_id=workspace_id,
                event_type="chat_ingested",
                payload={"session_id": session_id, "pages_saved": pages_saved},
            )
        )
    await session.commit()
```

- [ ] **Step 4: Update the transcript variable name**

The rest of `run()` builds a `transcript` from `messages`. Since `messages` is now the delta slice, this still works — no other changes needed in the body.

- [ ] **Step 5: Run existing tests to check nothing broke**

```bash
docker compose run --rm api pytest tests/ -v
```

Expected: all existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add api/app/agents/chat_monitor.py
git commit -m "feat: cursor-based delta processing in chat monitor"
```

---

## Task 6: Chat monitor — maintain `system/memory` and `system/history`

**Files:**
- Modify: `api/app/agents/chat_monitor.py`
- Modify: `api/app/agents/prompts/chat_monitor.md`

- [ ] **Step 1: Update the monitor prompt**

Replace the full content of `api/app/agents/prompts/chat_monitor.md` with:

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

### 3. Save wiki-worthy content
As before: identify decisions, facts, insights, or plans worth keeping permanently in the wiki.
- Use `search_pages()` to check if content already exists.
- Use `write_page()` to update an existing page, or `create_page()` for a new topic.
- Do NOT ingest casual back-and-forth, clarifying questions, or content already well-covered.

## Order of operations
1. `read_page("system/memory")` — understand what is already known about the user
2. Process new messages
3. Update `system/memory` if needed
4. Upsert `system/history` entry for this session
5. Save any wiki-worthy content to regular pages

If none of the three responsibilities apply, do nothing.
```

- [ ] **Step 2: Pass session_id and today's date into the monitor**

The monitor needs to know the session ID (for the history entry header) and today's date. Add the import at the top of `api/app/agents/chat_monitor.py` with the other imports:

```python
from datetime import date as _date
```

Then in `run()`, find the `llm_messages` construction and update the user message:

```python
# ...inside run(), after building transcript:
today = _date.today().isoformat()
llm_messages = [
    {"role": "system", "content": SYSTEM_PROMPT},
    {
        "role": "user",
        "content": (
            f"Session ID: {session_id}\n"
            f"Date: {today}\n\n"
            f"New messages to review:\n\n{transcript[:8000]}"
        ),
    },
]
```

- [ ] **Step 3: Add new tools to the monitor's allowed set**

Currently the monitor calls `tools_obj.as_litellm_tools()` with no `allowed` filter (gets everything). This is fine — `append_to_page`, `patch_page`, and `grep_page` are already registered and will be available automatically. No change needed here.

- [ ] **Step 4: Run all tests**

```bash
docker compose run --rm api pytest tests/ -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/agents/chat_monitor.py api/app/agents/prompts/chat_monitor.md
git commit -m "feat: chat monitor maintains system/memory and system/history"
```

---

## Task 7: Query agent — inject `system/memory` + expose `grep_page`

**Files:**
- Modify: `api/app/agents/query_agent.py`
- Modify: `api/app/agents/prompts/query.md`

- [ ] **Step 1: Add `grep_page` to the query agent's allowed tools**

In `api/app/agents/query_agent.py`, find:

```python
READ_ONLY_TOOLS = ["list_pages", "search_pages", "read_page"]
```

Replace with:

```python
READ_ONLY_TOOLS = ["list_pages", "search_pages", "read_page", "grep_page"]
```

- [ ] **Step 2: Inject `system/memory` into the system prompt**

In `run()`, after constructing `tools`, read `system/memory` and prepend it to the system prompt if it exists:

```python
async def run(
    workspace_id: str,
    question: str,
    history: list[dict],
    session: AsyncSession,
) -> tuple[str, list[str]]:
    tools = AgentTools(
        session=session, workspace_id=workspace_id, broadcaster=broadcaster, context="chat"
    )
    tool_defs = tools.as_litellm_tools(allowed=READ_ONLY_TOOLS)

    user_memory = await tools.read_page("system/memory")
    if user_memory.startswith("[Page 'system/memory' not found]"):
        system_prompt = SYSTEM_PROMPT
    else:
        system_prompt = f"<user_context>\n{user_memory}\n</user_context>\n\n{SYSTEM_PROMPT}"

    messages = [
        {"role": "system", "content": system_prompt},
        *history[-10:],
        {"role": "user", "content": question},
    ]
    # rest of function unchanged...
```

- [ ] **Step 3: Update the query prompt to reference user context**

In `api/app/agents/prompts/query.md`, prepend a note about the injected context:

```markdown
You are a knowledgeable assistant with access to the user's personal wiki.

A `<user_context>` block may appear above these instructions containing what the wiki knows about the user. Use it to personalise your answers without being asked.

When answering questions:
1. Call read_page("meta/index") first to see the full wiki structure and find relevant pages.
2. Use search_pages() to narrow down if needed.
3. Use read_page() to read up to 5 of the most relevant pages in full.
4. If the user references something that might have been discussed before, use grep_page("system/history", <keyword>) to search past session summaries.
5. Answer based on what you find. Cite pages using their full slug: [[people/alice-jones]].
6. If the wiki doesn't contain the answer, say so clearly.
You may only read pages — do not write or create anything.
```

- [ ] **Step 4: Run all tests**

```bash
docker compose run --rm api pytest tests/ -v
```

Expected: all PASS

- [ ] **Step 5: Smoke test end-to-end**

```bash
docker compose up --build -d
```

Send a few chat messages, wait for the monitor to fire (after 4+ messages in a session), then check:
- `system/memory` page exists in the wiki sidebar
- `system/history` has an entry for the session

- [ ] **Step 6: Commit**

```bash
git add api/app/agents/query_agent.py api/app/agents/prompts/query.md
git commit -m "feat: inject system/memory into query agent and expose grep_page"
```
