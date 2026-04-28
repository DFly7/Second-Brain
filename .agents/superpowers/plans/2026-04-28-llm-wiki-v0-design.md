# LLM Wiki — v0 Design Spec

**Date:** 2026-04-28
**Status:** Approved
**Author:** Darragh Flynn

---

## 1. What we're building

A single-user, web-only, LLM-maintained markdown wiki that acts as a personal second brain. The user ingests anything — PDFs, Word docs, URLs, plain text — and the agent automatically organises it into a structured, interlinked wiki. A chat interface lets the user query their knowledge base, and a background agent continuously monitors conversations to capture anything worth retaining.

This is built for the builder first. The ICP is a solo founder/operator who wants a living store for everything they think about, read, see, and do — not a narrow business tool.

---

## 2. Scope

### In

| Feature | Detail |
|---|---|
| Ingest pipeline | PDF, Word (.docx), plain text paste, URL fetch → agent auto-writes to wiki |
| Wiki | Markdown pages, CRUD, `[[wikilinks]]`, auto-maintained `index.md` |
| Chat interface | Agent reads relevant wiki pages and answers in context with citations |
| Background chat agent | Reads conversation transcript, auto-ingests anything noteworthy |
| Activity log | Feed of every page created/updated, what source triggered it |
| Agent transparency | SSE streaming of tool calls — wiki panel highlights pages as agent reads/writes them live |
| Auth | Single user, simple login. No teams, no sharing. |

### Out

| Cut | Reason |
|---|---|
| Diff review UI | Adds friction before there's a reason to distrust the agent. Add after v0 if needed. |
| ZIP export | Post-v0 |
| Voice notes | Requires mobile; mobile is post-v0 |
| Mobile app | Post-PMF |
| Graph view | Post-v0 |
| Multi-user / sharing | Post-PMF |

---

## 3. Architecture

Five components. One Postgres instance, one app process. Nothing exotic.

```
┌──────────────────────────────────────────────────────────┐
│                    React Frontend                        │
│   Wiki panel (left) · Chat panel (right) · Activity log │
│   Ingest button · Live agent highlights via SSE          │
└──────────────────────┬───────────────────────────────────┘
                       │ REST + SSE
┌──────────────────────┴───────────────────────────────────┐
│                      FastAPI                             │
│   Auth · Ingest · Chat · Wiki CRUD · Activity log · SSE  │
└────────┬─────────────────────────────┬────────────────────┘
         │                             │
┌────────┴────────┐          ┌─────────┴──────────┐
│   Postgres      │          │  Background workers │
│  pages          │          │                     │
│  revisions      │          │  Ingest agent       │
│  sources        │          │  Query agent        │
│  activity_log   │          │  Chat monitor agent │
│  chat_sessions  │          │                     │
│  chat_messages  │          └─────────┬──────────┘
│  pgvector       │                    │
│  tsvector FTS   │          ┌─────────┴──────────┐
└─────────────────┘          │  LiteLLM            │
                             │  Gemini (default)   │
                             │  swap via config    │
                             └────────────────────┘

S3: raw uploads only (PDFs, Word docs)
```

### Frontend layout

Split view — wiki and chat always visible simultaneously.

- **Left:** page list sidebar + current page viewer/editor
- **Right:** chat interface
- **Live:** as the agent runs, the wiki panel highlights the page being read (blue ring) or written (spinner). This is driven by SSE tool-call events streamed from the backend.
- **Activity log:** collapsible drawer, accessible from both panels

### Model abstraction

LiteLLM wraps all LLM calls. Model is set in config (`LITELLM_MODEL=gemini/gemini-2.0-flash`). Switching providers requires no code changes.

---

## 4. Data model

```sql
workspaces(id, user_id, created_at)

pages(
  id, workspace_id, slug, title, summary,
  body_md, embedding vector(1536), tsv tsvector,
  updated_at
)

page_links(from_page_id, to_page_id)
-- materialised from [[wikilinks]] on every page write

revisions(id, page_id, parent_revision_id, body_md, created_at)
-- rollback: UPDATE pages SET body_md = (SELECT body_md FROM revisions WHERE id = ?)

sources(id, workspace_id, kind, s3_key, extracted_text, created_at)
-- kind: pdf | docx | text | url

activity_log(id, workspace_id, event_type, payload_json, created_at)
-- event_type: page_created | page_updated | source_ingested | chat_ingested

chat_sessions(id, workspace_id, created_at)
chat_messages(id, session_id, role, content, created_at)
```

No DAG, no branches, no merge resolution. Revision history is a linked list. Rollback is one SQL statement.

---

## 5. The three agents

All three share one tool surface. They differ only in system prompt and which tools they may call.

### Shared tool surface

```python
search_pages(query: str)        -> list[{slug, title, summary, score}]
read_page(slug: str)            -> str  # full markdown
write_page(slug: str, md: str)  -> None # saves revision, updates index, logs activity
create_page(slug: str, md: str) -> None # new page + logs activity
list_pages()                    -> list[{slug, title, summary}]
```

### Ingest agent

- **Trigger:** source uploaded (PDF, Word, text, URL)
- **Flow:** extract text → `list_pages()` → `search_pages()` for related pages → `read_page()` for top matches → decide: `write_page()` to update existing or `create_page()` for new → done
- **Permissions:** all tools
- **Constraint:** hard per-run cost ceiling (kill if projected spend > $2)

### Query agent

- **Trigger:** user sends chat message
- **Flow:** `search_pages()` → `read_page()` for top 5 results → compose answer with cited slugs → stream response
- **Permissions:** `search_pages`, `read_page`, `list_pages` only (read-only)
- **Output:** answer + list of cited page slugs (used to highlight in wiki panel)

### Chat monitor agent

- **Trigger:** runs in background during active chat session; also runs once when session ends
- **Flow:** reads recent `chat_messages` → decides if any exchange is noteworthy → if yes, calls ingest pipeline on the relevant excerpt
- **Permissions:** `search_pages`, `read_page`, `create_page`, `write_page`
- **Heuristic:** only ingests if the exchange contains a decision, a fact, a commitment, or a new idea — not casual back-and-forth

---

## 6. Agent transparency (SSE)

Every tool call emits an SSE event to the connected frontend client:

```json
{"event": "agent:reading", "slug": "llm-wiki"}
{"event": "agent:writing", "slug": "startup-ideas"}
{"event": "agent:done", "pages_touched": ["llm-wiki", "startup-ideas"]}
```

Frontend behaviour:
- `agent:reading` → highlight page in wiki sidebar (blue ring)
- `agent:writing` → show spinner on page title
- `agent:done` → clear highlights, refresh activity log

This is the core trust mechanism in the absence of diff review — the user always sees exactly what the agent touched.

---

## 7. Ingest pipeline detail

### Source extraction

| Kind | Library |
|---|---|
| PDF | `pypdf` or `pdfplumber` |
| Word (.docx) | `python-docx` |
| URL | `httpx` + `trafilatura` (main content extraction) |
| Plain text | No processing needed |

### Page granularity heuristic (prompt-driven)

The ingest agent is given the full list of existing pages and their summaries. Its system prompt instructs:

- **Update an existing page** if the source adds to, refines, or contradicts something already captured there
- **Create a new page** if the topic has no home yet, or if the new content is substantial enough to stand alone
- **Prefer updating** when in doubt — a wiki with 50 well-developed pages beats one with 200 stubs

This is the trickiest prompt-engineering problem in the product. Expect to iterate on it during weeks 3–5.

---

## 8. Build plan

### Weeks 1–2 — Skeleton
- Postgres schema, FastAPI setup, auth (single user JWT)
- Wiki CRUD + markdown editor
- `[[wikilinks]]` parsing + `page_links` materialisation
- S3 upload + PDF/Word/URL extraction
- Hybrid search: `tsvector` FTS + pgvector

### Weeks 3–5 — Ingest agent
- LiteLLM integration (Gemini default)
- Ingest agent loop with shared tool surface
- Background worker (asyncio or Celery)
- Activity log
- SSE tool-call streaming + frontend highlights

### Weeks 6–8 — Chat + monitor
- Query agent (read-only tool permissions)
- Chat interface (split view, right panel)
- Chat monitor agent (background, session-scoped)
- Auto-maintained `index.md`
- Cost ceiling + monthly spend cap

### Weeks 9–10 — Polish + dogfood
- Onboarding flow ("paste your first note, watch the wiki build itself")
- Empty state: 3 starter pages seeded from onboarding
- Performance pass (pgvector index, embedding batch)
- Internal cost telemetry

---

## 9. Open questions before week 1

1. **Gemini model variant** — `gemini-2.0-flash` for speed/cost or `gemini-2.5-pro` for quality? Start with flash, switch if quality is poor.
2. **Worker strategy** — asyncio background tasks (simplest) vs Celery + Redis (more robust). Start with asyncio, add Celery if job reliability becomes an issue.
3. **Embedding model** — Gemini embeddings or a dedicated model? Use `text-embedding-004` (Gemini) to stay on one provider initially.
4. **Chat monitor trigger cadence** — run every N messages during session, or only on session end? Start with on-session-end, add live monitoring if it feels too slow.

---

## 10. Success criteria

| Metric | Target |
|---|---|
| Pages created in first week of personal use | ≥ 20 |
| Queries that feel "better than ChatGPT" | Subjective — note any that don't |
| Ingest accuracy (page goes to right place) | ≥ 80% — track manually at first |
| Cost per day of personal use | < $1 |
