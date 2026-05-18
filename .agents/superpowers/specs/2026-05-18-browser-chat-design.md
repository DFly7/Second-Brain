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
| `created_at` | DateTime | |
| `completed_at` | DateTime nullable | set on disconnect |

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
| `POST` | `/browser-chat/sessions` | Connect — create DB session, call `POST /session/new` on browser-agent, return `session_id` + `browser_session_id` |
| `POST` | `/browser-chat/sessions/{id}/message` | Send a message — persist user message, trigger agent loop, stream SSE events, persist assistant reply, return `{reply}` |
| `POST` | `/browser-chat/sessions/{id}/disconnect` | Disconnect — call `POST /session/{browser_session_id}/close` on browser-agent, mark session `completed` |
| `GET` | `/browser-chat/sessions` | List sessions for workspace (newest first, limit 50) |
| `GET` | `/browser-chat/sessions/{id}` | Session + full message list |

---

## BrowserChatAgent

**File:** `api/app/agents/browser_chat_agent.py`
**Prompt:** `api/app/agents/prompts/browser_chat.md`

Same LiteLLM tool loop pattern as `AutomationAgent`. Key differences:

- Accepts full `conversation_history` (list of `{role, content}`) so the model has context across messages.
- Runs tool loop until no tool calls remain, then returns the final assistant text as the reply.
- Does **not** create/close browser sessions — those are managed by the routes.
- SSE events published during the run:
  - `browser_chat:action` — `{session_id, type, detail}` — one per browser tool call
  - `browser_chat:reply` — `{session_id, content}` — final assistant reply
  - `browser_chat:status` — `{session_id, status}` — `thinking` / `idle`
- Same browser tools as `AutomationAgent` + same wiki tools.
- Max 20 turns per message (prevents runaway loops on a single user message).

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
| `agentRunning` | `boolean` | disables input while true |
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
api/app/config.py                  — no changes needed (reuses browser_agent_url, novnc_url)
api/app/main.py                    — register browser_chat router
frontend/src/App.tsx               — add /browser-chat route
frontend/src/components/TopBar.tsx — add Browser Chat nav link
frontend/src/api/client.ts         — add browser chat API functions
```

---

## Out of scope

- Video recording of browser chat sessions
- Multiple concurrent browser chat sessions
- Mobile layout
