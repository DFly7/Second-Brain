# Persistent Chat Sessions Design

**Date:** 2026-05-02

## Goal

Persist chat sessions to the database so conversations survive page refresh, and provide a session history drawer so the user can navigate back to old chats.

## Current State

- `ChatSession` and `ChatMessage` models already exist in Postgres.
- `POST /chat/message` creates sessions and persists all messages correctly.
- `GET /chat/sessions/{session_id}/messages` fetches a session's messages.
- `ChatPanel.tsx` holds messages in React `useState` only — lost on refresh.
- No session list UI. No `GET /chat/sessions` endpoint.

## What We're Building

### Backend

**New endpoint:** `GET /chat/sessions`
- Scoped to the authenticated user's workspace.
- Returns sessions ordered newest-first.
- Response shape: `[{ id: string, created_at: string }]`
- No model changes required.

### Frontend: Component Split

`ChatPanel.tsx` becomes the orchestrator. Two new child components:

**`SessionDrawer.tsx`**
- Right-anchored overlay within the chat pane.
- Slides in from the right via CSS `transform: translateX` (200ms transition).
- Shows a list of past sessions labelled by `created_at` (e.g. "May 2, 14:32").
- "New Chat" button at the top of the list.
- Closes when user selects a session or clicks the toggle.

**`ChatConversation.tsx`**
- The message thread + input, extracted from the current `ChatPanel.tsx`.
- Props: `messages`, `loading`, `activeSseEvent`, `editMode`, `onSubmit`, `onNavigate`, `onEditModeToggle`.
- No session awareness — purely presentational.

**`ChatPanel.tsx` (orchestrator)**
- Owns: `sessionId`, `messages`, `drawerOpen`, `editMode`.
- Header contains: history toggle button (right-aligned, opens/closes drawer) and "New Chat" button beside it.
- Renders `SessionDrawer` and `ChatConversation`.

### Data Flow & Lifecycle

**On mount:**
1. Read `sessionId` from `localStorage`.
2. If found, call `GET /chat/sessions/{id}/messages` to restore conversation.
3. Call `GET /chat/sessions` to populate the drawer list.
4. If session not found (empty/404), silently clear `localStorage` and start fresh.

**Sending a message:**
- `POST /chat/message` with current `sessionId` (or omit for new chat).
- Write returned `session_id` to state and `localStorage`.
- If this was the first message of a new session, refresh the drawer session list.

**Selecting a session from the drawer:**
1. Set `sessionId` in state and `localStorage`.
2. Fetch messages via `GET /chat/sessions/{id}/messages`.
3. Close the drawer.

**New Chat (header button or drawer button):**
1. Clear `messages`.
2. Clear `sessionId` from state and `localStorage`.
3. Close the drawer if open.

### Drawer Animation

- Positioned absolutely within the chat pane, full height, right-anchored.
- `transform: translateX(100%)` when closed → `translateX(0)` when open.
- CSS transition: 200ms ease.
- Overlays the conversation — no layout shift.

## Error Handling

| Scenario | Behaviour |
|---|---|
| `sessionId` in localStorage no longer exists in DB | Silently clear, start fresh |
| `GET /chat/sessions` fails | Drawer shows "Failed to load" — chat still works |
| No sessions exist | Drawer shows "No previous chats" empty state |
| Send fails | Existing behaviour, no change |

## Out of Scope

- Session titles (using `created_at` timestamp only for now)
- Session deletion
- URL-based session routing
- AI-generated session summaries
