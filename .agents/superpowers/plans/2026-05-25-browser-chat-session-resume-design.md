# Browser Chat Session Resume — Design

## Overview

Users need to re-enter past browser chat sessions from the session list. Clicking a past session should either reconnect to a live session or resume a completed one with full message context passed to the new agent.

## Backend

**File:** `api/app/routes/browser_chat.py`

Add optional `prior_session_id: str | None = None` to the `ConnectRequest` body (or create one if the POST body is currently empty).

After creating the new `BrowserChatSession` row, if `prior_session_id` is provided:
1. Query all `BrowserChatMessage` rows for `prior_session_id`, ordered by `created_at asc`
2. Insert copies into the new session (same `role` + `content`, new `session_id`, new `id`)

The agent already reads message history from the DB by `session_id` on every turn (`_run_turn_task` lines 82–88), so no agent code changes are needed.

## Frontend

### `src/api/client.ts`

`connectBrowserChat` gains an optional `priorSessionId?: string` param, passed as `{ prior_session_id: priorSessionId }` in the POST body.

### `BrowserChatPage.tsx`

**On mount**, read `?session` from the URL search params:

- **Active session** (`status === 'active'`):
  - Call `getBrowserChatSession(sessionId)` to load messages
  - Set `activeSessionId = sessionId`, `messages = session.messages`, `connectionState = 'connected'`
  - Do NOT call `connectBrowserChat` — browser is still live

- **Completed session** (`status !== 'active'`):
  - Call `connectBrowserChat(priorSessionId = sessionId)`
  - Get back new `session_id`; set `activeSessionId = new session_id`, `connectionState = 'connected'`
  - Load old messages via `getBrowserChatSession(sessionId)` and display them with a visual divider before any new messages

**Visual divider** for resumed sessions: a centered muted line reading `── Resumed from [date of prior session] ──`, rendered between the old messages and the new message input area. Old messages use the same existing styles (no extra muting needed — the divider provides enough context).

**Session rows on the landing page** — make the main row content (date + status text) a navigable element pointing to `/browser-chat?session=<id>`. The existing "Messages ▾" dropdown and "Disconnect" button keep their current click handlers (stop propagation to avoid double-navigation). The sidebar links (`BrowserSessionsList.tsx`) already generate this URL shape and need no changes.

### URL behaviour

- Navigating to `/browser-chat` (no param) → existing new-session flow, unchanged
- Navigating to `/browser-chat?session=<id>` → resume flow as above
- After resuming, the URL stays as-is (no redirect to a new session ID); the `activeSessionId` in state diverges from the URL for the resumed-completed case, which is acceptable

## Data flow summary

```
User clicks session row
  → navigate to /browser-chat?session=<id>
  → BrowserChatPage mounts / param changes
  → getBrowserChatSession(id)
    → active?  set state, show connected UI
    → completed? connectBrowserChat(priorSessionId=id)
                  → backend copies messages → new session_id
                  → load old messages, insert divider
                  → show connected UI with history
```

## Out of scope

- Renaming sessions
- Pagination of session history
- Copying browser state / cookies between sessions
