# PA Browser Agent — Design

## Overview

Evolve the existing browser chat agent into a persistent personal assistant (PA). The PA stays logged into the user's accounts via a shared Chrome profile, remembers context across sessions via structured `system/PA/` wiki pages, and opens every session with genuine continuity rather than a blank slate. No new agent, no new DB models, no new UI — the intelligence comes from persistent state doing the work.

---

## 1. Persistent Browser Profile

### Approach
A single shared Chrome profile directory used by all browser chat sessions. Configured via `PA_PROFILE_DIR` env var on the browser-agent service, defaulting to `/data/pa-profile`. Created on first launch if absent.

**`browser-agent/main.py` changes:**
- Remove per-session temp dir creation
- On `session_new`: call `clear_profile_locks(PA_PROFILE_DIR)` first, then `launch_persistent_context(user_data_dir=PA_PROFILE_DIR, ...)`
- On `session_recover`: same dir, just replace the dead context object
- On `session_close`: do NOT delete the profile dir — only close the browser/context objects

**`browser-agent/Dockerfile`:**
- Add `PA_PROFILE_DIR` env var defaulting to `/data/pa-profile`
- Create the dir at image build time

**`docker-compose.yml` / `docker-compose.prod.yml`:**
- Named Docker volume (`pa-profile`) mounted at `/data/pa-profile` on the browser-agent service so it survives container restarts and rebuilds

### Profile lock clearing (`clear_profile_locks`)

Chrome writes a `SingletonLock` file (and occasionally `lockfile`, `.com.google.Chrome.*` temp locks) inside the profile dir. After a crash or ungraceful shutdown these linger and cause patchright to hang on the next `launch_persistent_context`.

Add a `clear_profile_locks(profile_dir: str)` helper in `browser-agent/main.py` that runs before every `launch_persistent_context`:

```python
import glob, os

def clear_profile_locks(profile_dir: str) -> None:
    patterns = [
        "SingletonLock", "SingletonCookie", "SingletonSocket",
        "lockfile", ".com.google.Chrome.*",
    ]
    for pattern in patterns:
        for path in glob.glob(os.path.join(profile_dir, pattern)):
            try:
                os.remove(path)
            except OSError:
                pass
```

The existing 409 guard ensures no live process is using the profile when `session_new` is called, so unconditional deletion is safe.

---

## 2. `system/PA/` Wiki Structure

The PA maintains structured markdown pages under `system/PA/`. The agent creates, reads, and updates these itself. The `system/PA/` namespace is cleanly separate from `system/memory` (user knowledge) and `system/history` (chat logs).

### Seed pages (created by agent on first session if absent)

| Page | Purpose |
|---|---|
| `system/PA/context` | Updated at end of every session: what was done, in-progress tasks, loose ends. Primary warm-handoff source. Includes a `Last updated:` timestamp so the agent knows how long ago it was written. |
| `system/PA/accounts` | Sites the PA has access to. Columns: URL, login method, auth strategy (e.g. "OAuth via GitHub", "password + 2FA"), last verified date, notes. Tracking last verified lets the agent anticipate expired sessions and ask the user for help rather than looping on a broken login. |
| `system/PA/preferences` | Standing user preferences discovered during sessions (e.g. "summarise emails as bullets", "always check unread first", "flag anything from recruiter@domain.com"). |

### Growth
The agent freely creates new pages under `system/PA/` as it takes on new domains — e.g. `system/PA/job-search`, `system/PA/subscriptions`, `system/PA/finances`. Only domain pages the user has actually worked on get created.

### Maintenance rules (baked into system prompt)
- Immediately write to `system/PA/accounts` when successfully logging into a new site; include auth strategy and today's date as `Last verified`
- Immediately write to `system/PA/preferences` when the user states or implies a standing preference
- Always update `system/PA/context` before the session ends — including on disconnect (see Section 3)
- Never delete PA pages; append and update instead

---

## 3. Warm Session Handoff

### Boot sequence (`browser_chat_agent.py`)

Before the first LLM call in `run_turn`, the agent:

1. Calls `list_pages` filtered to `system/PA/` to discover all PA pages
2. Always reads the three seed pages in full: `context`, `accounts`, `preferences`
3. For any additional domain pages (e.g. `system/PA/job-search`): injects only the page name and slug — the agent fetches the full content with `read_page` only when the current task is relevant to it
4. Injects everything as a `<pa_context>` block appended to the system prompt, along with the current datetime

This lazy-loading strategy keeps the `<pa_context>` block lean as the PA accumulates domain pages over time. The core three pages stay small by design (accounts = a table, preferences = a list, context = last session summary).

The `<pa_context>` block format:
```
<pa_context>
Current datetime: 2026-05-25T14:32:00

[system/PA/context]
<full content>

[system/PA/accounts]
<full content>

[system/PA/preferences]
<full content>

Additional domain pages available (fetch with read_page if relevant to current task):
- system/PA/job-search
- system/PA/subscriptions
</pa_context>
```

If no PA pages exist yet (first ever session), the agent introduces itself and creates the seed pages with placeholder content before greeting the user.

### Opening message behaviour

The agent opens with a natural, contextual greeting using the current datetime and `system/PA/context` to gauge time elapsed and surface relevant loose ends. The right tone:

- *"Last session we were halfway through your inbox — want to pick that up, or something else?"*
- *"It's been a few days — anything urgent before we continue with the job search?"*
- *"I've got your Gmail and Notion logged in. What are we doing today?"*

Not a data dump — the most relevant 1-2 things from context, then open floor.

### Disconnect / session-close context save

When the session ends — whether the user clicks Disconnect or the connection drops — the backend must ensure `system/PA/context` is updated before tearing down the browser. The risk: if `session_close` immediately kills the container, the agent has no chance to write its state.

**Implementation in `api/app/routes/browser_chat.py` `session_close` handler:**

1. Set a `disconnecting` flag on the session record
2. Fire one final hidden `run_turn` call with a special injected system message:
   `[System: The user has disconnected. Write a summary of this session to system/PA/context now — what was accomplished, what is in progress, any loose ends. Then stop.]`
3. Await that turn to complete (with a hard 30s timeout)
4. Then close the browser-agent session

This is a hidden turn — it never emits SSE events to the frontend and the user never sees it. The 30s timeout ensures we don't hang indefinitely on a broken connection.

---

## 4. System Prompt Changes (`browser_chat.md`)

New section prepended to the existing prompt:

```markdown
## Your identity

You are a persistent personal assistant with access to a real browser. You maintain memory across sessions via wiki pages under `system/PA/`. You are not a fresh agent — you have history with this user. Your PA context is injected at the top of each session.

## PA memory rules

- **On session start:** Read your injected `<pa_context>`. Greet the user with genuine continuity — reference what's relevant, not everything.
- **Accounts:** Update `system/PA/accounts` immediately when you log into a new site. Always record the auth strategy (OAuth provider, password+2FA, SSO, etc.) and today's date as `Last verified`. If you hit an auth failure on a known account, check when it was last verified and ask the user for help rather than retrying blindly.
- **Preferences:** Update `system/PA/preferences` immediately when the user tells you how they like something done, or when you infer a clear preference from their behaviour.
- **Context:** Update `system/PA/context` when the session ends. Include: what was accomplished, what is in progress, any follow-ups needed. Write the current date as `Last updated:` at the top.
- **Domain pages:** Create new pages under `system/PA/` freely as work expands. Fetch them with `read_page` when relevant to the current task.

## Tone

You know this user. Act like it. Surface what matters. Anticipate. Keep it brief.
```

---

## 5. File Map

| File | Change |
|---|---|
| `browser-agent/main.py` | `clear_profile_locks()` helper; use `PA_PROFILE_DIR` for all sessions; remove temp dir logic |
| `browser-agent/Dockerfile` | Add `PA_PROFILE_DIR=/data/pa-profile` env; create dir at build time |
| `docker-compose.yml` | Named volume `pa-profile` mounted at `/data/pa-profile` on browser-agent service |
| `docker-compose.prod.yml` | Same named volume mount |
| `api/app/agents/browser_chat_agent.py` | Boot sequence: lazy-load `system/PA/*`; inject `<pa_context>` with datetime; disconnect intercept turn |
| `api/app/routes/browser_chat.py` | `session_close` fires hidden context-save turn before teardown |
| `api/app/agents/prompts/browser_chat.md` | PA identity section, memory rules, auth failure handling, tone |

---

## Out of Scope

- Heartbeat / background monitor tool (future spec)
- PA UI changes (existing browser chat UI is sufficient)
- Credentials storage (PA uses the browser profile's saved sessions — no explicit secrets management)
- Multi-user PA (single-user app, not relevant)
