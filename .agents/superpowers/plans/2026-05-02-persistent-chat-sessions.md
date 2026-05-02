# Persistent Chat Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist chat sessions across page refresh and add a right-anchored session history drawer inside the chat pane.

**Architecture:** Add one backend endpoint (`GET /chat/sessions`). On the frontend, split `ChatPanel.tsx` into three components: `ChatPanel` (orchestrator + state), `ChatConversation` (message thread + input), and `SessionDrawer` (history overlay). Session ID is persisted in `localStorage` and messages are reloaded from the API on mount.

**Tech Stack:** FastAPI, SQLAlchemy async, React 18, TypeScript, CSS transitions (no extra libraries)

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `api/app/routes/chat.py` | Add `GET /chat/sessions` endpoint |
| Modify | `api/tests/test_chat_routing.py` | Add test for new endpoint |
| Modify | `frontend/src/api/client.ts` | Add `listSessions`, `getSessionMessages` |
| Create | `frontend/src/components/ChatConversation.tsx` | Message thread + input (extracted from ChatPanel) |
| Create | `frontend/src/components/SessionDrawer.tsx` | Right-anchored history drawer |
| Modify | `frontend/src/components/ChatPanel.tsx` | Orchestrator: owns state, renders children |

---

### Task 1: Backend — `GET /chat/sessions` endpoint

**Files:**
- Modify: `api/app/routes/chat.py`
- Modify: `api/tests/test_chat_routing.py`

- [ ] **Step 1: Write the failing test**

Add to `api/tests/test_chat_routing.py` after the existing imports and `chat_api_client` fixture:

```python
def test_list_sessions_returns_sessions_newest_first(chat_api_client):
    from datetime import datetime
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_ws = MagicMock()
    mock_ws.id = "ws-1"

    s1 = MagicMock()
    s1.id = "sess-old"
    s1.created_at = datetime(2026, 5, 1, 10, 0, 0)
    s2 = MagicMock()
    s2.id = "sess-new"
    s2.created_at = datetime(2026, 5, 2, 12, 0, 0)

    db_result = MagicMock()
    db_result.scalars.return_value.all.return_value = [s2, s1]

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.chat._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = chat_api_client.get("/chat/sessions")
            assert r.status_code == 200
            data = r.json()
            assert len(data) == 2
            assert data[0]["id"] == "sess-new"
            assert data[1]["id"] == "sess-old"
            assert "created_at" in data[0]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_list_sessions_returns_empty_when_none(chat_api_client):
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_ws = MagicMock()
    mock_ws.id = "ws-1"

    db_result = MagicMock()
    db_result.scalars.return_value.all.return_value = []

    session = MagicMock()
    session.execute = AsyncMock(return_value=db_result)

    async def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    try:
        with patch(
            "app.routes.chat._ensure_workspace",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            r = chat_api_client.get("/chat/sessions")
            assert r.status_code == 200
            assert r.json() == []
    finally:
        app.dependency_overrides.pop(get_db, None)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose run --rm api pytest tests/test_chat_routing.py::test_list_sessions_returns_sessions_newest_first tests/test_chat_routing.py::test_list_sessions_returns_empty_when_none -v
```

Expected: FAIL with `404` (route doesn't exist yet).

- [ ] **Step 3: Add the endpoint to `api/app/routes/chat.py`**

Add after the `get_messages` route (around line 110), before the `sse_stream` route:

```python
@router.get("/sessions")
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    user: str = Depends(get_current_user),
):
    ws = await _ensure_workspace(db, user)
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.workspace_id == ws.id)
        .order_by(ChatSession.created_at.desc())
    )
    sessions = result.scalars().all()
    return [{"id": s.id, "created_at": s.created_at.isoformat()} for s in sessions]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose run --rm api pytest tests/test_chat_routing.py::test_list_sessions_returns_sessions_newest_first tests/test_chat_routing.py::test_list_sessions_returns_empty_when_none -v
```

Expected: PASS.

- [ ] **Step 5: Run full test suite to check no regressions**

```bash
docker compose run --rm api pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add api/app/routes/chat.py api/tests/test_chat_routing.py
git commit -m "feat: add GET /chat/sessions endpoint"
```

---

### Task 2: Frontend — API client additions

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add `listSessions` and `getSessionMessages` to `frontend/src/api/client.ts`**

Add at the end of the file (after `runHealthCheck`):

```typescript
export async function listSessions(): Promise<{ id: string; created_at: string }[]> {
  const r = await fetch(`${BASE}/chat/sessions`, { headers: headers() })
  if (!r.ok) throw new Error('Failed to load sessions')
  return r.json()
}

export async function getSessionMessages(
  sessionId: string
): Promise<{ id: string; role: string; content: string }[]> {
  const r = await fetch(`${BASE}/chat/sessions/${sessionId}/messages`, { headers: headers() })
  if (!r.ok) return []
  return r.json()
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat: add listSessions and getSessionMessages to API client"
```

---

### Task 3: Frontend — Extract `ChatConversation.tsx`

**Files:**
- Create: `frontend/src/components/ChatConversation.tsx`

Extract the message list, loading indicator, and input area out of `ChatPanel.tsx` into a new focused component.

- [ ] **Step 1: Create `frontend/src/components/ChatConversation.tsx`**

```typescript
import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'

export interface Message { role: 'user' | 'assistant'; content: string; cited?: string[] }

interface ChatConversationProps {
  messages: Message[]
  loading: boolean
  activeSseEvent: { event: string; slug?: string } | null
  editMode: boolean
  onSubmit: (text: string) => void
  onNavigate: (slug: string) => void
  onEditModeToggle: () => void
}

function processWikilinks(text: string): string {
  return text.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, slug, display) =>
    `[${display ?? slug}](wiki://${slug})`
  )
}

function isExternalHref(href: string): boolean {
  return /^(https?:\/\/|mailto:|tel:)/i.test(href)
}

function hrefToSlug(href: string): string | null {
  if (!href) return null
  if (href.startsWith('wiki://')) return href.slice(7)
  if (href.startsWith('#')) return null
  if (isExternalHref(href)) return null
  return href.replace(/^\.\//, '')
}

function sseStatusLabel(active: { event: string; slug?: string } | null): string {
  if (!active) return 'Thinking…'
  if (active.event === 'agent:reading') return active.slug ? `⟳ Reading ${active.slug}…` : '⟳ Reading…'
  if (active.event === 'agent:writing') return active.slug ? `⟳ Writing ${active.slug}…` : '⟳ Writing…'
  return 'Thinking…'
}

function sseStatusAnimKey(active: { event: string; slug?: string } | null): string {
  if (!active) return 'thinking'
  return active.slug ?? active.event
}

export default function ChatConversation({
  messages,
  loading,
  activeSseEvent,
  editMode,
  onSubmit,
  onNavigate,
  onEditModeToggle,
}: ChatConversationProps) {
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  function handleSubmit() {
    if (!input.trim() || loading) return
    const text = input.trim()
    setInput('')
    onSubmit(text)
  }

  return (
    <>
      <style>{`
        @keyframes fadeSlide {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
      <div style={{ flex: 1, overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {messages.length === 0 && (
          <div style={{ color: '#8b949e', fontSize: 13, textAlign: 'center', marginTop: 40 }}>
            Ask anything — the agent will search your wiki.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} style={{ maxWidth: '90%', alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
            <div style={{
              padding: '8px 12px', borderRadius: 8, fontSize: 13, lineHeight: 1.6,
              background: m.role === 'user' ? '#1f6feb' : '#161b22',
              color: '#e6edf3', border: m.role === 'assistant' ? '1px solid #30363d' : 'none',
            }}>
              {m.role === 'assistant' ? (
                <ReactMarkdown
                  remarkPlugins={[remarkGfm, remarkMath]}
                  rehypePlugins={[rehypeKatex]}
                  urlTransform={(url) => url}
                  components={{
                    a({ href, children }) {
                      const slug = href ? hrefToSlug(href) : null
                      if (href && slug) {
                        return (
                          <span
                            role="link"
                            tabIndex={0}
                            onClick={() => onNavigate(slug)}
                            onKeyDown={(e) => e.key === 'Enter' && onNavigate(slug)}
                            style={{ color: '#58a6ff', cursor: 'pointer', textDecoration: 'underline' }}
                          >
                            {children}
                          </span>
                        )
                      }
                      return <a href={href} target="_blank" rel="noreferrer">{children}</a>
                    },
                    ul({ children }) { return <ul style={{ margin: '4px 0', paddingLeft: 20 }}>{children}</ul> },
                    ol({ children }) { return <ol style={{ margin: '4px 0', paddingLeft: 20 }}>{children}</ol> },
                    p({ children }) { return <p style={{ margin: '4px 0' }}>{children}</p> },
                  }}
                >
                  {processWikilinks(m.content)}
                </ReactMarkdown>
              ) : (
                m.content
              )}
            </div>
            {m.role === 'assistant' && m.cited && m.cited.length > 0 && (
              <div style={{ fontSize: 11, color: '#6e7681', marginTop: 6, paddingLeft: 4 }}>
                searched {m.cited.length} page{m.cited.length === 1 ? '' : 's'}
              </div>
            )}
            {m.cited && m.cited.length > 0 && (
              <div style={{ fontSize: 11, color: '#8b949e', marginTop: 4, paddingLeft: 4 }}>
                Sources: {m.cited.map((slug) => (
                  <span
                    key={slug}
                    onClick={() => onNavigate(slug)}
                    style={{ color: '#58a6ff', cursor: 'pointer', marginRight: 6, textDecoration: 'underline' }}
                  >
                    {slug}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div style={{
            alignSelf: 'flex-start', padding: '8px 12px', borderRadius: 8,
            fontSize: 13, lineHeight: 1.6, background: '#21262d',
            color: '#8b949e', border: '1px solid #30363d',
          }}>
            <span
              key={sseStatusAnimKey(activeSseEvent)}
              style={{ display: 'inline-block', animation: 'fadeSlide 200ms ease' }}
            >
              {sseStatusLabel(activeSseEvent)}
            </span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <div style={{
        padding: 12, borderTop: '1px solid #30363d',
        display: 'flex', alignItems: 'center', gap: 8,
        ...(editMode ? { boxShadow: 'inset 0 0 0 1px #d29922', background: 'rgba(210, 153, 34, 0.06)' } : {}),
      }}>
        <button
          type="button"
          onClick={onEditModeToggle}
          title={editMode ? 'Switch to read-only query' : 'Allow the agent to edit wiki pages'}
          style={{
            padding: '8px 12px', borderRadius: 6, fontSize: 13, cursor: 'pointer', flexShrink: 0,
            border: editMode ? '1px solid #d29922' : '1px solid #30363d',
            background: editMode ? 'rgba(210, 153, 34, 0.22)' : '#161b22',
            color: editMode ? '#d29922' : '#8b949e', whiteSpace: 'nowrap',
          }}
        >
          Edit Mode
        </button>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleSubmit()}
          placeholder="Ask your wiki..."
          style={{
            flex: 1, padding: '8px 12px', background: '#161b22',
            border: '1px solid #30363d', borderRadius: 6, color: '#e6edf3', fontSize: 13,
          }}
        />
        <button
          onClick={handleSubmit}
          disabled={loading}
          style={{
            padding: '8px 16px', background: '#238636', border: 'none',
            borderRadius: 6, color: '#fff',
            cursor: loading ? 'not-allowed' : 'pointer', fontSize: 13, flexShrink: 0,
          }}
        >
          Send
        </button>
      </div>
    </>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ChatConversation.tsx
git commit -m "feat: extract ChatConversation component from ChatPanel"
```

---

### Task 4: Frontend — Create `SessionDrawer.tsx`

**Files:**
- Create: `frontend/src/components/SessionDrawer.tsx`

- [ ] **Step 1: Create `frontend/src/components/SessionDrawer.tsx`**

```typescript
interface Session { id: string; created_at: string }

interface SessionDrawerProps {
  open: boolean
  sessions: Session[]
  loadError: boolean
  activeSessionId: string | undefined
  onSelect: (id: string) => void
  onNewChat: () => void
  onClose: () => void
}

function formatSessionDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export default function SessionDrawer({
  open,
  sessions,
  loadError,
  activeSessionId,
  onSelect,
  onNewChat,
  onClose,
}: SessionDrawerProps) {
  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        right: 0,
        bottom: 0,
        width: 260,
        background: '#161b22',
        borderLeft: '1px solid #30363d',
        display: 'flex',
        flexDirection: 'column',
        transform: open ? 'translateX(0)' : 'translateX(100%)',
        transition: 'transform 200ms ease',
        zIndex: 10,
      }}
    >
      <div style={{
        padding: '12px 16px',
        borderBottom: '1px solid #30363d',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <span style={{ fontSize: 13, color: '#8b949e' }}>History</span>
        <button
          onClick={onClose}
          style={{
            background: 'none', border: 'none', color: '#8b949e',
            cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: 0,
          }}
          title="Close"
        >
          ×
        </button>
      </div>
      <div style={{ padding: '8px 12px', borderBottom: '1px solid #30363d' }}>
        <button
          onClick={onNewChat}
          style={{
            width: '100%', padding: '7px 12px', background: '#238636',
            border: 'none', borderRadius: 6, color: '#fff',
            cursor: 'pointer', fontSize: 13, textAlign: 'left',
          }}
        >
          + New Chat
        </button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: 8 }}>
        {loadError && (
          <div style={{ color: '#f85149', fontSize: 12, padding: '8px 4px' }}>
            Failed to load history
          </div>
        )}
        {!loadError && sessions.length === 0 && (
          <div style={{ color: '#8b949e', fontSize: 12, padding: '8px 4px' }}>
            No previous chats
          </div>
        )}
        {sessions.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            style={{
              display: 'block', width: '100%', textAlign: 'left',
              padding: '8px 10px', borderRadius: 6, marginBottom: 2,
              background: s.id === activeSessionId ? '#1f6feb22' : 'none',
              border: s.id === activeSessionId ? '1px solid #1f6feb55' : '1px solid transparent',
              color: s.id === activeSessionId ? '#58a6ff' : '#c9d1d9',
              cursor: 'pointer', fontSize: 12,
            }}
          >
            {formatSessionDate(s.created_at)}
          </button>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/SessionDrawer.tsx
git commit -m "feat: add SessionDrawer component"
```

---

### Task 5: Frontend — Refactor `ChatPanel.tsx` into orchestrator

**Files:**
- Modify: `frontend/src/components/ChatPanel.tsx`

Replace the entire contents of `ChatPanel.tsx` with the orchestrator that wires `ChatConversation` and `SessionDrawer` together, owns all state, and handles localStorage persistence.

- [ ] **Step 1: Replace `frontend/src/components/ChatPanel.tsx`**

```typescript
import { useState, useEffect, useCallback } from 'react'
import { sendMessage, listSessions, getSessionMessages } from '../api/client'
import ChatConversation, { type Message } from './ChatConversation'
import SessionDrawer from './SessionDrawer'

const SESSION_KEY = 'chat_session_id'

interface ChatPanelProps {
  onNavigate: (slug: string) => void
  activeSseEvent: { event: string; slug?: string } | null
}

interface Session { id: string; created_at: string }

export default function ChatPanel({ onNavigate, activeSseEvent }: ChatPanelProps) {
  const [sessionId, setSessionId] = useState<string | undefined>(
    () => localStorage.getItem(SESSION_KEY) ?? undefined
  )
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(false)
  const [editMode, setEditMode] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [sessions, setSessions] = useState<Session[]>([])
  const [sessionsError, setSessionsError] = useState(false)

  const loadSessions = useCallback(async () => {
    try {
      const data = await listSessions()
      setSessions(data)
      setSessionsError(false)
    } catch {
      setSessionsError(true)
    }
  }, [])

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  useEffect(() => {
    const id = localStorage.getItem(SESSION_KEY)
    if (!id) return
    getSessionMessages(id).then((msgs) => {
      if (msgs.length === 0) {
        localStorage.removeItem(SESSION_KEY)
        setSessionId(undefined)
        return
      }
      setMessages(msgs.map(m => ({ role: m.role as 'user' | 'assistant', content: m.content })))
    })
  }, [])

  function persistSession(id: string) {
    setSessionId(id)
    localStorage.setItem(SESSION_KEY, id)
  }

  async function handleSubmit(text: string) {
    setMessages(m => [...m, { role: 'user', content: text }])
    setLoading(true)
    const isNew = !sessionId
    try {
      const resp = await sendMessage(text, sessionId, editMode ? 'edit' : 'query')
      persistSession(resp.session_id)
      setMessages(m => [...m, { role: 'assistant', content: resp.answer, cited: resp.cited_pages }])
      if (isNew) await loadSessions()
    } finally {
      setLoading(false)
    }
  }

  async function handleSelectSession(id: string) {
    persistSession(id)
    const msgs = await getSessionMessages(id)
    setMessages(msgs.map(m => ({ role: m.role as 'user' | 'assistant', content: m.content })))
    setDrawerOpen(false)
  }

  function handleNewChat() {
    setMessages([])
    setSessionId(undefined)
    localStorage.removeItem(SESSION_KEY)
    setDrawerOpen(false)
  }

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100%',
      background: '#0d1117', borderLeft: '1px solid #30363d',
      position: 'relative', overflow: 'hidden',
    }}>
      <div style={{
        padding: '12px 16px', borderBottom: '1px solid #30363d',
        fontSize: 13, color: '#8b949e', background: '#161b22',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        flexShrink: 0,
      }}>
        <span>Chat</span>
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            onClick={handleNewChat}
            style={{
              padding: '4px 10px', fontSize: 12, borderRadius: 6,
              border: '1px solid #30363d', background: '#0d1117',
              color: '#8b949e', cursor: 'pointer',
            }}
            title="Start a new chat"
          >
            New Chat
          </button>
          <button
            onClick={() => setDrawerOpen(v => !v)}
            style={{
              padding: '4px 10px', fontSize: 12, borderRadius: 6,
              border: '1px solid #30363d',
              background: drawerOpen ? '#1f6feb22' : '#0d1117',
              color: drawerOpen ? '#58a6ff' : '#8b949e', cursor: 'pointer',
            }}
            title="View chat history"
          >
            History
          </button>
        </div>
      </div>
      <ChatConversation
        messages={messages}
        loading={loading}
        activeSseEvent={activeSseEvent}
        editMode={editMode}
        onSubmit={handleSubmit}
        onNavigate={onNavigate}
        onEditModeToggle={() => setEditMode(v => !v)}
      />
      <SessionDrawer
        open={drawerOpen}
        sessions={sessions}
        loadError={sessionsError}
        activeSessionId={sessionId}
        onSelect={handleSelectSession}
        onNewChat={handleNewChat}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Start dev server and manually verify**

```bash
docker compose up --build
```

Open the app in a browser and verify:
- Chat works as before (send a message, get a reply)
- Refreshing the page restores the conversation
- "History" button opens the drawer from the right
- "New Chat" in header and in drawer both clear the conversation
- Clicking a session in the drawer loads it and closes the drawer
- Drawer shows "No previous chats" when empty
- Active session is highlighted in the drawer list

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ChatPanel.tsx
git commit -m "feat: refactor ChatPanel into orchestrator with session persistence and history drawer"
```
