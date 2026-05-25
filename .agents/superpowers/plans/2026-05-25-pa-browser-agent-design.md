# PA Browser Agent — Design

## Overview

Evolve the existing browser chat agent into a persistent personal assistant (PA). The PA stays logged into the user's accounts via a shared Chrome profile, remembers context across sessions via structured `system/PA/` wiki pages, and opens every session with genuine continuity rather than a blank slate. No new agent, no new DB models, no new UI — the intelligence comes from persistent state doing the work.

---

## 1. Persistent Browser Profile

### Problem
Today each browser session gets a fresh profile directory (or temp dir). The PA has no memory of cookies, saved sessions, or site state between sessions.

### Approach
A single shared Chrome profile directory is used for all browser chat sessions. Configured via `PA_PROFILE_DIR` env var on the browser-agent service, defaulting to `/data/pa-profile`. The dir is created on first launch if absent.

**`browser-agent/main.py` changes:**
- Remove per-session temp dir creation
- On `session_new`: `launch_persistent_context(user_data_dir=PA_PROFILE_DIR, ...)` — all sessions share this one dir
- On `session_recover`: same dir, just replace the dead context object
- On `session_close`: do NOT delete the profile dir — only close the browser/context objects

**`browser-agent/Dockerfile`:**
- Add `VOLUME /data/pa-profile` and create the dir at image build time
- Ensure `/data/pa-profile` is in the Docker volume mount in `docker-compose.yml` / `docker-compose.prod.yml` so it survives container restarts

**Concurrency:** The existing 409 guard (`"A browser chat session is already active"`) already enforces single-session — no conflict risk.

---

## 2. `system/PA/` Wiki Structure

The PA maintains a set of structured markdown pages under `system/PA/`. The agent creates, reads, and updates these itself. No fixed schema — just well-organised markdown. The `system/PA/` namespace is cleanly separate from `system/memory` (user knowledge) and `system/history` (chat logs).

### Seed pages (created by agent on first use if absent)

| Page | Purpose |
|---|---|
| `system/PA/accounts` | Sites the PA knows how to access: URL, login method, status, notes. Updated whenever it successfully authenticates somewhere new. |
| `system/PA/preferences` | Standing instructions and user preferences discovered during sessions (e.g. "summarise emails as bullets", "always check unread first", "flag anything from recruiter@company.com"). |
| `system/PA/context` | Written at the end of every session: what was done, what's in progress, any loose ends or follow-ups. This is the primary warm-handoff source. |

### Growth
The agent freely creates new pages under `system/PA/` as work expands — e.g. `system/PA/job-search`, `system/PA/subscriptions`, `system/PA/finances`. These are just wiki pages; the existing `write_page` / `create_page` tools handle them.

### Maintenance rules (baked into system prompt)
- Immediately write to `system/PA/accounts` when successfully logging into a new site
- Immediately write to `system/PA/preferences` when the user states or implies a standing preference
- Always update `system/PA/context` before the session ends — even if the user disconnects mid-task, write what was in progress
- Never delete PA pages; append and update instead

---

## 3. Warm Session Handoff

### Boot sequence (changes to `browser_chat_agent.py`)

Before the first LLM call in `run_turn`, the agent:

1. Calls `list_pages` filtered to `system/PA/` to discover all PA pages
2. Reads each page via `read_page`
3. Injects the combined content as a `<pa_context>` block appended to the system prompt for this session

The `<pa_context>` block format:
```
<pa_context>
[system/PA/context]
<content of context page>

[system/PA/accounts]
<content of accounts page>

[system/PA/preferences]
<content of preferences page>

[... any other system/PA/* pages ...]
</pa_context>
```

If no PA pages exist yet (first ever session), the agent introduces itself, explains it will start building a picture of the user's accounts and preferences, and creates the seed pages.

### Opening message behaviour (system prompt instructions)

The agent should open with a natural, contextual greeting — not a data dump. Examples of the right tone:

- *"Last session we were halfway through your inbox — want to pick that up, or something else?"*
- *"I've got your Gmail and Notion logged in. What are we doing today?"*
- *"It's been a few days — anything urgent you want to get through first?"*

The agent checks `system/PA/context` for time elapsed since the last session and surfaces the most relevant loose ends, not everything.

### Session close behaviour

When the session ends (user disconnects or agent turn completes):
- Agent calls `patch_page` or `write_page` on `system/PA/context` with a structured update:
  - What was accomplished
  - What's in progress / next steps
  - Any new accounts or preferences discovered this session

---

## 4. System Prompt Changes (`browser_chat.md`)

New section added to the existing prompt:

```markdown
## Your identity

You are a persistent personal assistant with access to a real browser. You maintain memory across sessions via wiki pages under `system/PA/`. You are not a fresh agent — you have history with this user.

## PA memory rules

- On session start: your PA context is injected above. Read it. Greet the user with genuine continuity.
- Immediately update `system/PA/accounts` when you log into a new site.
- Immediately update `system/PA/preferences` when you learn how the user likes things done.
- Before this session ends: update `system/PA/context` with what was done and any loose ends.
- Create new pages under `system/PA/` freely as you take on new domains of work.

## Tone

Act like a PA who knows the user, not a tool awaiting instructions. Surface relevant context. Anticipate. Keep it brief.
```

---

## 5. File Map

| File | Change |
|---|---|
| `browser-agent/main.py` | Use `PA_PROFILE_DIR` for all sessions; remove temp dir creation |
| `browser-agent/Dockerfile` | Add `PA_PROFILE_DIR` env, create `/data/pa-profile` dir |
| `docker-compose.yml` | Add volume mount for `pa-profile` on browser-agent service |
| `docker-compose.prod.yml` | Same volume mount |
| `api/app/agents/browser_chat_agent.py` | Boot sequence: read `system/PA/*` pages, inject `<pa_context>` block |
| `api/app/agents/prompts/browser_chat.md` | Add PA identity section, memory rules, tone instructions |

---

## Out of Scope

- Heartbeat / background monitor tool (future spec)
- PA UI changes (existing browser chat UI is sufficient)
- Credentials storage (PA uses the browser profile's saved sessions — no explicit secrets management)
- Multi-user PA (single-user app, not relevant)
