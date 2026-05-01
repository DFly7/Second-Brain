# Edit Agent Design

**Date:** 2026-05-01
**Status:** Approved

## Overview

Add an edit-mode agent that can restructure and edit wiki pages on user instruction. The query agent stays read-only. A mode toggle in the chat UI switches between query and edit agents. Both agents share the same chat session and history.

---

## Architecture

Five changes:

1. **`api/app/agents/edit_agent.py`** (new) — mirrors `query_agent.py` structure, uses `EDIT_TOOLS` list, has its own system prompt.
2. **`api/app/agents/prompts/edit.md`** (new) — instructs the agent to plan structural changes, prefer `move_page` over delete+recreate, and rewrite backlinks as part of any move.
3. **`AgentTools`** — two new methods: `move_page` and `delete_page`, with tool definitions in `as_litellm_tools()` and dispatch cases in `dispatch()`.
4. **`/chat/message` request body** — gains `mode: Literal["query", "edit"] = "query"`. The chat route dispatches to `run_query` or `run_edit` accordingly.
5. **Frontend** — edit mode toggle button near the message input (amber/orange when active). Sends same `session_id` with `mode: "edit"` when toggled on.

---

## New Tools

### `move_page(old_slug: str, new_slug: str) -> str`

**Pre-conditions (fail fast):**
- Validate `new_slug` against the existing slug regex before doing anything. Return an error string if invalid (e.g. uppercase, spaces, double slashes).
- Check if `new_slug` already exists in the DB. If it does, return an error — do not overwrite. The agent must surface this to the user rather than silently clobbering a page.

**Execution:**
1. Read old page content and metadata from DB.
2. Call `write_page(new_slug, body_md, summary, title)` — creates new page and auto-updates `meta/index` with new entry.
3. Query the `PageLink` table for all pages where `target_slug = old_slug`. Rewrite `[[old_slug]]` → `[[new_slug]]` in each page's body and save. This avoids a full table scan — only the pages that actually link to `old_slug` are touched.
4. Delete old page from DB.
5. Remove old slug's entry from `meta/index`.
6. Broadcast `{"event": "agent:moving", "from": old_slug, "to": new_slug}`.

### `delete_page(slug: str) -> str`

1. Remove page from DB.
2. Remove slug entry from `meta/index`.
3. Query the `PageLink` table for all pages where `target_slug = slug`. In each page's body, replace `[[slug]]` with `[[slug]] *(page deleted)*` — preserving the original link target so the user knows what it pointed to, while making the broken reference visually obvious.
4. Append an entry to `meta/deleted-log` (create the page if it doesn't exist): `| {timestamp} | [[slug]] | {title} |`. This gives a central audit trail of every deletion.
5. Broadcast `{"event": "agent:deleting", "slug": slug}`.

### `move_folder(old_prefix: str, new_prefix: str) -> str`

**Pre-conditions (fail fast):**
- Validate `new_prefix` against the slug regex.
- Check at least one page exists with `old_prefix/` — return an error if the folder is empty or doesn't exist.
- Check no page under `new_prefix/` would collide with a moved page — return an error listing conflicts if any exist.

**Execution:**
1. Query DB for all pages where `slug` starts with `old_prefix/`.
2. For each page, call `move_page(slug, slug.replace(old_prefix, new_prefix, 1))` — reuses all existing move logic including backlink rewrites via `PageLink`.
3. Broadcast a single coalesced event: `{"event": "agent:moved_folder", "from": old_prefix, "to": new_prefix, "count": N}` rather than N individual `agent:moving` events.

---

## Chat Session & History

- Single `ChatSession` shared across modes. No separate session per mode.
- When the user switches to edit mode and sends a message, the edit agent receives the full prior history (including query-mode messages) as context. This is intentional — the natural workflow is to query first to explore, then switch to edit to act on findings.
- Mode is sent per-message, not stored on the session.

---

## SSE Events

Extend the existing SSE event display to handle two new events:

| Event | Payload | Display |
|---|---|---|
| `agent:moving` | `{from, to}` | "Moving `from` → `to`" |
| `agent:deleting` | `{slug}` | "Deleting `slug`" |
| `agent:moved_folder` | `{from, to, count}` | "Moved `count` pages from `from` → `to`" |

**Bulk move handling:** `move_folder` emits a single coalesced `agent:moved_folder` event rather than N individual `agent:moving` events, so the frontend stays clean regardless of folder size.

---

## Frontend

- Toggle button labelled "Edit Mode" near the message input.
- Amber/orange colour when active; default style when inactive.
- Toggling does not start a new session — same `session_id` continues.
- Each message sent in edit mode includes `"mode": "edit"` in the request body; query mode sends `"mode": "query"` (or omits it, defaulting to query).

---

## Edit Agent Tool List

```
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
```

---

## Safety Notes

**Slug validation:** `move_page` must validate `new_slug` before executing. Check against the pattern already enforced elsewhere in the codebase (likely `^[a-z0-9][a-z0-9-]*(/[a-z0-9][a-z0-9-]*)+$`). Reject and return an error string if invalid — do not proceed.

**S3 versioning (ops recommendation):** Enable S3/MinIO object versioning on the wiki bucket. This is a silent safety net at the infrastructure level — no agent code changes required, no UI impact — but recovers from cases where the agent moves or deletes something unintended. Particularly valuable given there is no in-app undo.

---

## Out of Scope

- Bulk-rename by prefix (the agent handles this by calling `move_page` in a loop).
- Merge pages (not needed yet).
- Confirmation before destructive actions (user explicitly wants direct execution).
- Separate chat history per mode.
- In-app undo (S3 versioning is the recovery path).
