# Automation Agent — Design Spec
**Date:** 2026-05-18  
**Status:** Approved

## Overview

A dedicated Automations page where the user gives an LLM agent a goal, the agent controls a real browser to carry it out, and the user watches live via an embedded noVNC stream. Runs are persisted with a full action log and a screen recording saved to MinIO for later playback.

---

## 1. Architecture

```
Browser (React frontend)
        ↕  REST + SSE
API Container (existing)
  ├── AutomationAgent       — litellm tool-loop, new
  ├── routes/automations.py — REST + SSE, new
  └── AgentTools (wiki)     — existing, reused
        ↓ HTTP tool calls        ↕ Redis SSE      ↓ SQL
browser-agent (new)         Redis (existing)   Postgres (existing)
  ├── Playwright + Chromium                     ├── AutomationRun (new)
  ├── Xvfb :99 @ 1280×800                       └── AutomationAction (new)
  ├── x11vnc → noVNC :6080
  ├── FastAPI tool server :8001
  └── Playwright video → MinIO (existing)

noVNC WebSocket (:6080) → embedded iframe in frontend (bypasses API)
```

**Flow:** User types goal → API creates `AutomationRun`, starts `AutomationAgent` as background task → agent calls browser tools (HTTP → `browser-agent:8001`) → Chromium executes in Xvfb virtual display → frontend embeds noVNC iframe for live view → SSE streams action events to the activity feed → recording saved to MinIO on completion → run + actions persisted to Postgres.

---

## 2. browser-agent Container

**Location:** `browser-agent/` at repo root (alongside `api/`, `frontend/`)

**Contents:**
- `Dockerfile` — Ubuntu 22.04, installs: Xvfb, x11vnc, websockify (noVNC), Python, Playwright + Chromium, FastAPI + uvicorn. Exposes ports 6080 and 8001.
- `start.sh` — startup sequence:
  1. Xvfb on `:99` at 1280×800×24
  2. x11vnc watching `:99`, no password, localhost-only
  3. websockify on `0.0.0.0:6080` proxying VNC port (noVNC WebSocket)
  4. uvicorn on `0.0.0.0:8001` serving the tool API
- `main.py` — FastAPI tool server
- `requirements.txt`

**Tool API endpoints:**

| Endpoint | Behaviour |
|---|---|
| `POST /session/new` | Launch Chromium with `record_video_dir` set, return `session_id` |
| `POST /session/{id}/navigate` | Navigate to URL, return page title |
| `POST /session/{id}/click` | Click by CSS selector or x/y coordinates |
| `POST /session/{id}/type` | Type text into focused element |
| `POST /session/{id}/scroll` | Scroll by direction + amount |
| `POST /session/{id}/extract` | Return full visible page text for LLM |
| `POST /session/{id}/screenshot` | Return base64 PNG |
| `POST /session/{id}/close` | Stop recording, upload `.webm` to MinIO, return recording URL |
| `GET /health` | Health check |

**Video recording:** Playwright's built-in `record_video_dir`. No ffmpeg needed. On `close`, the `.webm` is uploaded to MinIO and the URL returned to the API.

---

## 3. API Changes

### AutomationAgent (`api/app/agents/automation_agent.py`)

Same litellm tool-loop pattern as `query_agent.py`. Gets two tool sets:

**Browser tools** — HTTP wrappers to `browser-agent:8001`. Each successful call also:
- Saves an `AutomationAction` row to Postgres
- Broadcasts an `automation:action` SSE event

| Tool | Maps to |
|---|---|
| `browser_navigate(url)` | `POST /session/{id}/navigate` |
| `browser_click(selector)` | `POST /session/{id}/click` |
| `browser_type(text)` | `POST /session/{id}/type` |
| `browser_scroll(direction, amount)` | `POST /session/{id}/scroll` |
| `browser_read()` | `POST /session/{id}/extract` |
| `browser_screenshot()` | `POST /session/{id}/screenshot` → SSE `automation:screenshot` |

**Wiki tools** — reuses existing `AgentTools` (write_page, create_page, read_page, search_pages). `wiki_write` actions are also logged to `AutomationAction`.

**SSE events broadcast:**

```
automation:action     { run_id, type, detail, timestamp }
automation:status     { run_id, status }
automation:screenshot { run_id, image_b64 }   # fallback / debug
```

### New Routes (`api/app/routes/automations.py`)

| Route | Behaviour |
|---|---|
| `POST /automations/run` | Create `AutomationRun`, start agent as `BackgroundTask` |
| `POST /automations/runs/{id}/stop` | Set run status → `stopped` in Postgres; agent checks status between every tool call and exits the loop if stopped |
| `GET /automations/runs` | List all runs for workspace, newest first |
| `GET /automations/runs/{id}` | Full run detail with all actions |
| `GET /automations/novnc-url` | Return noVNC iframe URL from config |

### Config

One new env var on the API container: `BROWSER_AGENT_URL=http://browser-agent:8001`

---

## 4. Data Models

New Alembic migration adding two tables.

### `AutomationRun`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `workspace_id` | UUID FK | → workspaces |
| `goal` | Text | User's original prompt |
| `status` | Enum | `pending` / `running` / `completed` / `failed` / `stopped` |
| `created_at` | Timestamp | |
| `completed_at` | Timestamp | Nullable |
| `recording_url` | Text | MinIO path, set on clean completion/stop |

### `AutomationAction`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `run_id` | UUID FK | → automation_runs |
| `type` | Text | `navigate` / `click` / `type` / `scroll` / `read` / `wiki_write` |
| `detail` | Text | Human-readable ("Navigated to google.com") |
| `timestamp` | Timestamp | |

Actions are written as they happen — history is preserved even if the agent crashes mid-run.

---

## 5. Frontend

### New `AutomationsPage` (`frontend/src/components/AutomationsPage.tsx`)

Registered as a new route at `/automations`. Two states managed by SSE:

**Idle state** (no active run): Shows run history list. Each run card displays:
- Status dot (green/red/yellow)
- Goal text (truncated)
- Duration, action count, wiki pages written
- Expandable action log
- "Watch" button → plays recording in a `<video>` modal from MinIO URL
- "New Run" CTA at top

**Running state** (active run): Three-panel layout (per approved mockup):
- **Left panel** (300px): Goal input (disabled while run is active), current run progress badge showing step count and status
- **Center panel** (flex): Styled browser chrome bar with URL + LIVE badge, noVNC iframe filling the viewport
- **Right panel** (260px): Live action feed via SSE, Stop button

**noVNC iframe URL:** `http://<host>:6080/vnc.html?autoconnect=1&view_only=1&resize=scale` — fetched from `GET /automations/novnc-url` on mount.

### Navigation

Add "Automations" link to `TopBar.tsx` alongside existing nav items.

---

## 6. Docker & Deployment

### docker-compose.yml + docker-compose.prod.yml

```yaml
browser-agent:
  build: browser-agent/
  environment:
    - DISPLAY=:99
    - MINIO_ENDPOINT=${MINIO_ENDPOINT}
    - MINIO_ACCESS_KEY=${MINIO_ACCESS_KEY}
    - MINIO_SECRET_KEY=${MINIO_SECRET_KEY}
  ports:
    - "6080:6080"   # noVNC — embedded by frontend
    - "8001:8001"   # tool API — internal, exposed for local dev
  restart: unless-stopped
```

New env var on the `api` service: `BROWSER_AGENT_URL=http://browser-agent:8001`

### Pi deployment note

Port 6080 must be reachable from the user's browser. Direct exposure is fine for single-user. The `browser-agent` container is moderately heavy (Chromium + Xvfb) — expected to run on Pi 4/5 but browser-heavy pages will be slower than on desktop.

---

## Out of scope (this spec)

- Agent authentication to third-party sites (login walls will cause failures)
- Multiple concurrent automation runs
- Scheduled / cron-triggered automations
- Mobile UI for the Automations page
