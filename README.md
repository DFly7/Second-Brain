# Second Brain — LLM Wiki (v0)

Single-user web app: ingest documents and notes, let an LLM merge them into a **markdown wiki** with `[[wikilinks]]`, then **chat** over that wiki with citations. Postgres holds state; MinIO holds raw uploads; **LiteLLM** talks to **Google Gemini** by default (model is env-configurable).

**Design spec:** [.agents/superpowers/plans/2026-04-28-llm-wiki-v0-design.md](.agents/superpowers/plans/2026-04-28-llm-wiki-v0-design.md)  
**Implementation checklist:** [.agents/superpowers/plans/2026-04-28-llm-wiki-v0-implementation.md](.agents/superpowers/plans/2026-04-28-llm-wiki-v0-implementation.md)  
**Architecture diagrams:** [docs/architecture.md](docs/architecture.md)

---

## What is implemented

| Area | Notes |
|------|--------|
| **Stack** | FastAPI (async SQLAlchemy + Alembic), React 18 + Vite + TypeScript, Docker Compose, Postgres 16 + pgvector, MinIO |
| **Auth** | Single user, JWT (`/auth/login`) |
| **Wiki** | CRUD, revisions on update, `[[wikilinks]]` → `page_links`, hybrid **FTS + vector** search (vector leg only if `VECTOR_SEARCH_ENABLED` and at least one page has `embedding` set) |
| **Ingest** | PDF, DOCX, URL, pasted text, **Markdown / `.txt` files**; background **ingest agent** with cost ceiling |
| **Chat** | Query agent (read-only tools), messages + sessions, **SSE** for live tool activity (`/chat/sse?token=…`) |
| **Monitor** | Background **chat monitor** agent can write to wiki from notable chat content |
| **Activity** | `/activity` feed |
| **Prod** | `docker-compose.prod.yml`, Gunicorn API image, nginx frontend (see compose file) |

---

## Quick start

1. **Environment**

   ```bash
   cp .env.example .env
   ```

   Set at least `GEMINI_API_KEY`, and align `SINGLE_USER_EMAIL` / `SINGLE_USER_PASSWORD` with what you type at login. Use a strong `JWT_SECRET` outside local-only use.

   **Search / embeddings:** `VECTOR_SEARCH_ENABLED` (default `true`) gates the **query** embedding API for hybrid search. Even when `true`, the app **skips** that call if no pages in the workspace have a stored `embedding` (the usual case until you add embedding-on-save). Set `VECTOR_SEARCH_ENABLED=false` to force **full-text only** and never call the embedding API for search.

2. **Run**

   ```bash
   docker compose up --build
   ```

3. **Database (first time or after new migrations)**

   ```bash
   docker compose run --rm api alembic upgrade head
   ```

4. **Open**

   - Frontend: [http://localhost:5173](http://localhost:5173)  
   - API: [http://localhost:8000](http://localhost:8000) (e.g. `GET /health`)

---

## Repo layout (high level)

| Path | Role |
|------|------|
| `api/` | FastAPI app, Alembic, agents, routes, extractors |
| `api/alembic/versions/` | DB migrations |
| `frontend/` | Vite + React UI |
| `tests/` | Pytest (mounted into API container — see `docker-compose.yml`) |
| `docs/architecture.md` | Mermaid diagrams and system description |

---

## Development

- **API tests:** `docker compose run --rm api pytest tests/ -v`
- **Migrations:** add a revision under `api/alembic/versions/`, then `alembic upgrade head` inside the API container context.

---

## License / status

Private / personal project unless you add a license file.
