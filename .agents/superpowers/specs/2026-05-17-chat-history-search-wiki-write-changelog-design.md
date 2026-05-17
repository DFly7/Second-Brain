# Design: Chat History Search, Query Agent Wiki Writes, and Changelog

**Date:** 2026-05-17

## Overview

Three interconnected improvements to the Second Brain agent architecture:

1. **Chat history search** — query agent can search raw past conversation messages, not just `system/history` summaries
2. **Query agent wiki writes** — agent can write to the wiki mid-conversation when it judges something is worth keeping; write authority moves from the background `chat_monitor` to the agent the user is actively talking to
3. **`system/changelog`** — lightweight file-level audit trail of wiki changes, readable by both agent and user

---

## Thread 1 — `search_chat_history` tool

### What it does

A new `AgentTools` method and tool definition that searches raw `ChatMessage` content across all sessions for the workspace, returning windowed excerpts with surrounding context.

### Implementation

**`AgentTools.search_chat_history(query: str, context_window_chars: int = 2000)`**

1. Query: `SELECT cm.* FROM chat_messages cm JOIN chat_sessions cs ON cm.session_id = cs.id WHERE cs.workspace_id = ? AND cm.content ILIKE '%query%' ORDER BY cm.created_at DESC LIMIT 20`
2. For each matched message, fetch all messages in that session ordered by `created_at`
3. Find the matched message's index in the session, then expand outward (earlier + later messages) until the excerpt reaches `context_window_chars` — so short messages get more neighbours, long messages get fewer
4. Deduplicate overlapping windows from the same session (if two matches are close together, merge their windows)
5. Cap at 5 excerpts total (~10k chars max injected into context)
6. Return formatted blocks:
   ```
   [Session 2026-04-12]
   USER: so for the paris trip...
   ASSISTANT: Right, the route was Lyon → Burgundy → Paris...
   USER: yeah and we said we'd leave on the 20th
   ---
   ```

**Wiring:**
- Add `search_chat_history` to `AgentTools.as_litellm_tools()` with description and parameters
- Add dispatch case in `AgentTools._execute_tool()`
- Add `"search_chat_history"` to `READ_ONLY_TOOLS` in `query_agent.py`

**No new DB table, no migration** — queries existing `chat_messages` and `chat_sessions`.

### Prompt guidance (`query.md`)

The tool ordering for past-conversation references must be explicit:

1. **Wiki pages first** — `meta/index` then relevant `read_page` calls (existing behaviour, unchanged)
2. **`system/history` second** — `grep_page("system/history", keyword)` for session summaries; this is fast and often sufficient
3. **`search_chat_history` last resort** — only when the user explicitly references something from a past conversation ("remember when we discussed X", "what were those plans from last month") AND the `system/history` summaries don't contain enough detail

Do not call `search_chat_history` speculatively, as a default step, or before checking `system/history` first.

---

## Thread 2 — Query agent wiki writes

### What changes

**`query_agent.py`:** Expand the allowed tools list beyond `READ_ONLY_TOOLS` to include write tools: `write_page`, `create_page`, `append_to_page`, `patch_page`. Delete tools (`delete_page`, `move_page`, `move_folder`) remain excluded — too destructive for a conversational agent.

**`query.md` prompt:** Add a section:
> You may write to the wiki mid-conversation when you encounter something genuinely durable — a concrete plan, a decision, a fact or preference worth keeping permanently. Use judgment: not every conversation warrants a save. When you do save something, briefly mention it in your reply: "I've saved this to [[trips/paris-road-trip]]."
>
> Only write to the wiki when a piece of information has reached a natural conclusion or the user explicitly agrees to save it. Avoid creating pages for highly fluid or half-formed ideas unless the user requests it — save the settled version, not the draft.

**`chat_monitor.md`:** Remove section 3 ("Save wiki-worthy content") entirely. The monitor's sole remaining responsibilities are:
1. Update `system/memory` with durable user facts
2. Upsert `system/history` with a session summary

**`chat_monitor.py`:** No code changes needed.

### Rationale

Write authority moves from a background ghost process (that the user never sees deciding) to the agent the user is actively talking to. The user sees what gets saved via the existing `agent:writing` SSE event and the agent's own reply. The changelog (Thread 3) provides the permanent audit trail.

---

## Thread 3 — `system/changelog`

### What it is

A wiki page at `system/changelog` that records a one-line entry for every create, update, delete, or move of a wiki page. Maintained automatically by `AgentTools`.

### Format

```markdown
# Wiki Changelog

| When | Action | Page |
| --- | --- | --- |
| 2026-05-17 14:32 | updated | [[trips/paris-road-trip]] |
| 2026-05-17 14:30 | created | [[trips/paris-road-trip]] |
| 2026-05-16 09:11 | deleted | notes/scratch |
| 2026-05-16 09:10 | moved | [[projects/old]] → [[archive/old]] |
```

### Implementation

In `AgentTools`, after every `write_page`, `delete_page`, and `move_page` call, append a row to `system/changelog`.

**Excluded from changelog** (to avoid recursive noise):
- `system/changelog` itself
- `system/memory`, `system/history`
- `meta/index`, `meta/deleted-log`

**Append logic:** Wiki pages are stored in Postgres (`Page.body_md`), so appending must be atomic at the DB level. Use a single `UPDATE pages SET body_md = body_md || $row WHERE slug = 'system/changelog' AND workspace_id = ?` rather than the read-modify-write pattern used by `_append_deleted_log`. If the page doesn't exist yet, fall back to an `INSERT` with the header + first row. This avoids the classic race condition where two concurrent agent writes (e.g. query agent and chat monitor both saving at the same moment) overwrite each other's entry.

### Agent access

No new tool needed — the agent reads it naturally via `read_page("system/changelog")` or `grep_page("system/changelog", ...)`.

`query.md` prompt: mention that `system/changelog` exists and the agent should check it when the user asks what has changed recently or what was recently added.

### User UI

The existing `/activity` API already logs `page_created` and `page_updated` events with the slug in payload. The frontend gets a "Recent changes" panel filtered to these event types — no new API endpoint needed.

---

## What does NOT change

- `chat_monitor.py` code — only its prompt changes (section 3 removed)
- `edit_agent` — already has write access, unchanged
- `system/memory` and `system/history` maintenance — still owned by `chat_monitor`
- `meta/deleted-log` — still maintained by `delete_page`, unchanged
- All existing tool signatures — new tool added, nothing modified

---

## File changes summary

| File | Change |
|------|--------|
| `api/app/agents/tools.py` | Add `search_chat_history()` method, `system/changelog` append logic in write/delete/move, new tool definition + dispatch case |
| `api/app/agents/query_agent.py` | Expand allowed tools to include write tools + `search_chat_history` |
| `api/app/agents/prompts/query.md` | Add wiki-write guidance + `search_chat_history` usage guidance + mention `system/changelog` |
| `api/app/agents/prompts/chat_monitor.md` | Remove section 3 (wiki saves) |
| `frontend/` | Add "Recent changes" panel consuming existing `/activity` API |
