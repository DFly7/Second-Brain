# Browser Chat — Design Spec

**Date:** 2026-05-18
**Status:** Approved

## Overview

A new `/browser-chat` page where the user connects to a live browser session and chats with an agent that controls it in real time. Unlike the one-shot Automations page, the browser session persists for the entire conversation and the user drives it message-by-message.

---

## User flow

1. User navigates to `/browser-chat`.
2. Clicks **Connect** — browser session starts, chat session created in DB.
3. User types a message (e.g. "Go to Hacker News and summarise the top 5 stories").
4. Agent takes as many browser actions as needed (navigate, click, read, etc.), streaming live action events via SSE while doing so.
5. Agent sends a final text reply summarising what it did.
6. User sends the next message — browser stays on the same page, conversation history is carried into every agent call.
7. User clicks **Disconnect** — browser session closed, DB session marked complete.
8. Past sessions listed below the browser when disconnected; user can view full message history for any past session.

---

## Architecture

Reuses the existing `browser-agent` container (no changes). Adds:

- Two new DB models
- New routes under `/browser-chat/`
- A new `BrowserChatAgent`
- A new `BrowserChatPage.tsx` frontend component
- TopBar nav link

---

## Data models

### `BrowserChatSession`

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | UUID |
| `workspace_id` | FK → workspaces | |
| `status` | String | `active` / `completed` |
| `browser_session_id` | String nullable | browser-agent session ID while active |
| `user_interrupted` | Boolean | set to `true` when frontend detects iframe interaction mid-run; cleared after agent acknowledges |
| `last_activity_at` | DateTime | updated on every message send and agent reply; used by the reaper |
| `created_at` | DateTime | |
| `completed_at` | DateTime nullable | set on disconnect or reaper cleanup |

### `BrowserChatMessage`

| Column | Type | Notes |
|---|---|---|
| `id` | String PK | UUID |
| `session_id` | FK → browser_chat_sessions | |
| `role` | String | `user` / `assistant` |
| `content` | Text | |
| `created_at` | DateTime | |

---

## API routes

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/browser-chat/sessions` | Connect — create DB session, call `POST /session/new` on browser-agent, return `session_id` |
| `POST` | `/browser-chat/sessions/{id}/message` | Send message — persist user message, spawn background task, return `202 Accepted` immediately |
| `POST` | `/browser-chat/sessions/{id}/interrupt` | Frontend signals user interacted with iframe — sets `user_interrupted = true` on session |
| `POST` | `/browser-chat/sessions/{id}/disconnect` | Disconnect — call `POST /session/{browser_session_id}/close` on browser-agent, mark session `completed` |
| `GET` | `/browser-chat/sessions` | List sessions for workspace (newest first, limit 50) |
| `GET` | `/browser-chat/sessions/{id}` | Session + full message list |

### Message flow (202 + SSE pattern)

`POST /message` returns `202` immediately and drops the agent run into a `BackgroundTask` (same pattern as `POST /automations/run`). The agent publishes all events — actions, final reply, status — to the global SSE broadcaster. The frontend receives them via the existing `useSse` hook. This avoids proxy timeout issues on long-running agent loops.

---

## BrowserChatAgent

**File:** `api/app/agents/browser_chat_agent.py`
**Prompt:** `api/app/agents/prompts/browser_chat.md`

Same LiteLLM tool loop pattern as `AutomationAgent`. Key differences:

- Accepts full `conversation_history` (list of `{role, content}`) so the model has context across messages.
- Runs tool loop until no tool calls remain, then returns the final assistant text as the reply.
- Does **not** create/close browser sessions — those are managed by the routes.
- Between each turn, reloads `user_interrupted` from DB. If `true`, injects a system message into the context: `"[System: the user interacted with the browser while you were working — browser state may have changed]"`, then clears the flag. The agent can take a screenshot to reorient if needed, and acknowledges the interruption in its final reply.
- SSE events published during the run:
  - `browser_chat:action` — `{session_id, type, detail}` — one per browser tool call
  - `browser_chat:reply` — `{session_id, content}` — final assistant reply
  - `browser_chat:status` — `{session_id, status}` — `thinking` / `idle`
- Same browser tools as `AutomationAgent` + same wiki tools.
- Max 20 turns per message (prevents runaway loops on a single user message).
- Updates `last_activity_at` on the session at the start and end of each run.

---

## Session reaper

A startup background task (registered in `api/app/main.py` lifespan) runs every 5 minutes. Any `BrowserChatSession` with `status=active` and `last_activity_at` older than 20 minutes gets:

1. `POST /session/{browser_session_id}/close` on browser-agent (best-effort, errors swallowed).
2. `status` set to `completed`, `completed_at` set to now.

This handles tab closes, network drops, and idle sessions without requiring explicit disconnect.

---

## User interrupt flow

When the agent is running (`agentRunning === true`), the frontend attaches a `window.blur` listener. This event fires when focus shifts into the iframe (i.e. user clicked in the browser). On blur:

1. Frontend fires `POST /browser-chat/sessions/{id}/interrupt`.
2. API sets `user_interrupted = true` on the session.
3. Between the agent's next turns, it reads the flag, injects the system context note, clears the flag, and may call `browser_screenshot()` to see the new state.
4. Agent acknowledges the interruption in its reply (e.g. "Looks like you clicked on X — I've updated my context").

---

## Frontend

### Layout (connected state)

```
┌──────────────────┬──────────────────────────────────────┐
│  Chat panel      │  Browser (noVNC iframe)               │
│  (320px fixed)   │                                       │
│                  │  ┌─────────────────────────────────┐  │
│  [messages]      │  │ toolbar: URL bar | Disconnect   │  │
│                  │  ├─────────────────────────────────┤  │
│                  │  │                                 │  │
│                  │  │        noVNC iframe             │  │
│                  │  │                                 │  │
│  ─────────────   │  └─────────────────────────────────┘  │
│  [input + Send]  │                                       │
└──────────────────┴──────────────────────────────────────┘
```

- Input disabled + "thinking…" indicator while agent is running.
- Agent reply appears as an assistant bubble when the run completes.
- User messages appear immediately on send (optimistic).
- noVNC iframe is always interactive — the interrupt flow handles mid-run clicks rather than locking it.

### Layout (disconnected / idle state)

Full-width view with a **Connect** button centred. Below it, a list of past sessions (date, first user message preview, duration). Clicking a past session expands its message history inline.

### Component file

`frontend/src/components/BrowserChatPage.tsx`

### State

| State | Type | Notes |
|---|---|---|
| `connectionState` | `disconnected \| connecting \| connected` | |
| `activeSessionId` | `string \| null` | |
| `messages` | `BrowserChatMessage[]` | grows as conversation progresses |
| `agentRunning` | `boolean` | disables input, activates blur listener |
| `novncUrl` | `string \| null` | fetched from `/automations/novnc-url` (reused) |
| `pastSessions` | `BrowserChatSession[]` | loaded on mount |

### SSE

Reuses the existing `useSse` hook. Listens for `browser_chat:action`, `browser_chat:reply`, `browser_chat:status` events. On `browser_chat:reply`, appends the assistant message to the list and sets `agentRunning = false`.

---

## Files changed / created

### New
```
api/app/agents/browser_chat_agent.py
api/app/agents/prompts/browser_chat.md
api/app/routes/browser_chat.py
api/alembic/versions/<rev>_add_browser_chat_tables.py
api/tests/test_browser_chat_routes.py
frontend/src/components/BrowserChatPage.tsx
```

### Modified
```
api/app/models.py                  — add BrowserChatSession, BrowserChatMessage
api/app/main.py                    — register browser_chat router + reaper startup task
frontend/src/App.tsx               — add /browser-chat route
frontend/src/components/TopBar.tsx — add Browser Chat nav link
frontend/src/api/client.ts         — add browser chat API functions
```

---

## Out of scope

- Video recording of browser chat sessions
- Multiple concurrent browser chat sessions
- Mobile layout
