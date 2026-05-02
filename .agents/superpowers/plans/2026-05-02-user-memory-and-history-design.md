# User Memory & Session History — Design

## Overview

Two persistent wiki pages (`system/memory`, `system/history`) give the chat agent continuity across sessions. The chat monitor maintains both. Three new tools (`append_to_page`, `patch_page`, `grep_page`) make targeted page manipulation and search possible without full rewrites.

---

## System Pages

### `system/memory`
The agent's running understanding of the user — preferences, background, recurring topics, facts worth remembering. Written and updated by the chat monitor. Read by the query agent at the start of every query to personalise responses. User can view and edit it like any other wiki page.

### `system/history`
Chronological log of session summaries. One entry per session, appended when the session is new, patched when an existing session gets updated. Format:

```markdown
## 2026-05-02 · {session_id}
**Summary:** One or two sentence overview of what was discussed.
**Notes:**
- Key decisions, facts, or outcomes worth recalling later
- ...
```

---

## Data Model

Add two nullable columns to `ChatSession`:

| Column | Type | Purpose |
|---|---|---|
| `last_monitored_message_id` | `UUID \| null` | FK to `ChatMessage` — cursor for delta processing |

One Alembic migration required.

---

## New Tools (`AgentTools`)

### `append_to_page(slug, content)`
Appends `content` to the end of the named page. Creates the page if it doesn't exist. No read required. Used by the monitor to add new session entries to `system/history`.

### `patch_page(slug, old_text, new_text)`
Reads the page, finds the exact `old_text` string, replaces it with `new_text`. Agent must have read the page first to know the exact text to target. Used by the monitor to update an existing session entry in `system/history`, and available to any agent for surgical edits on any page.

Failure return strings are explicit so the agent knows how to recover:
- `"patch failed: old_text not found in '{slug}'"` — agent re-reads the page and retargets
- `"patch failed: old_text matches {n} locations in '{slug}', be more specific"` — agent widens the target string until unique

No retry logic inside the tool — the agent's own tool loop (up to 10 iterations) handles re-read and retry naturally.

### `grep_page(slug, query, context_lines=5, regex=False)`
Line-by-line search within a page. When `regex=False` (default), does a case-insensitive literal match. When `regex=True`, treats `query` as a Python `re` pattern (e.g. `## 2026-04-.*` to find all April 2026 session headers). Returns each matching line plus `context_lines` lines above and below, separated by `---` if multiple matches. Returns `"no matches"` or `"page not found"` if nothing found. Invalid regex returns `"grep failed: invalid pattern: {error}"`. Available to all agents.

All three tools are registered in `as_litellm_tools()` and `dispatch()`.

---

## Chat Monitor Changes

### Trigger logic
The monitor already fires as a background task after every message. New behaviour at the top of `run()`:

1. Load `ChatSession` and read `last_monitored_message_id`
2. Fetch all `ChatMessage` rows created after the cursor (or all if cursor is null)
3. If `len(delta) < MONITOR_THRESHOLD` (constant, default `4`), return immediately
4. Otherwise proceed and update cursor to the last message in the delta at the end

### What the monitor does per run
1. `read_page("system/memory")` — inject current user understanding into prompt as context
2. Process delta messages
3. **Update `system/memory`** if the delta reveals new facts about the user — rewrite via `write_page`
4. **Upsert `system/history`**:
   - If no entry for this session exists → `append_to_page("system/history", new_block)`
   - If entry exists → `read_page("system/history")`, locate the block, `patch_page(...)` with updated content
5. **Existing wiki extraction** — unchanged, still saves noteworthy content to regular pages

### Prompt update
`prompts/chat_monitor.md` gains a new section describing:
- The `system/memory` page and how to update it
- The `system/history` page format and upsert pattern
- When to use `append_to_page` vs `read_page` + `patch_page`

---

## Query Agent Changes

At the start of each `run()`, attempt `read_page("system/memory")`. If the page exists and has content, prepend it to the system prompt as a `<user_context>` block. If the page doesn't exist yet, skip silently.

`grep_page` is available in the query agent's tool list so it can search history for prior context when relevant.

---

## File Map

| Action | Path |
|---|---|
| Modify | `api/app/models.py` — add `last_monitored_message_id` to `ChatSession` |
| Create | `api/alembic/versions/<rev>_add_chat_session_monitor_cursor.py` |
| Modify | `api/app/agents/tools.py` — add `append_to_page`, `patch_page`, `grep_page` |
| Modify | `api/app/agents/chat_monitor.py` — cursor logic, delta threshold, new responsibilities |
| Modify | `api/app/agents/prompts/chat_monitor.md` — describe memory/history responsibilities |
| Modify | `api/app/agents/query_agent.py` — inject `system/memory` into context |
| Modify | `api/app/agents/prompts/query.md` — reference user context block |

---

## Error Handling

- `system/memory` or `system/history` not found → create on first write, skip on first read
- `patch_page` old_text not found → return clear error string so agent can fall back to `append_to_page`
- `grep_page` page not found → return "page not found" string, not an exception
- Delta fetch returns 0 messages → return early before any LLM call

---

## Out of Scope (v1)

- Time-based fallback trigger (process even if delta < threshold after X minutes idle)
- User-facing "clear memory" or "clear history" UI
- Per-session memory vs global memory distinction
- Embedding / vector search over history (plain grep is enough for now)
