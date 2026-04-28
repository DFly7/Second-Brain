# Marker Document Pipeline — Design Spec

**Date:** 2026-04-28
**Status:** Approved for implementation

---

## Overview

Replace the current simple text extractors with a Marker-powered pipeline that converts uploaded documents to structured markdown + extracted images, stores everything in S3, and gives the ingest agent multi-turn paginated access to large documents via an orchestrator/sub-agent pattern.

---

## Goals

- Support PDF, DOCX, PPTX, XLSX, and image uploads (not just PDF + DOCX)
- No hard 12k-char truncation — agents can navigate arbitrarily large documents
- Agent can view images extracted from documents (via a dedicated vision model)
- Original file + converted markdown both stored in S3
- Self-hosted Marker container (no per-page cost), with a clean abstraction to swap to the hosted Datalab API later via a single config change

---

## Architecture

### New service: `marker_service`

A new Docker container running a custom FastAPI app that wraps the Marker Python library. It exposes one endpoint:

```
POST /convert   multipart file upload → JSON list of pages
GET  /health    health check
```

Models are loaded **once at startup** (`create_model_dict()`) and reused for every request. A named Docker volume (`marker_models`) persists the model cache (~4–5 GB) across container restarts so models are only downloaded once.

`TORCH_DEVICE` is left unset — Marker auto-detects MPS on M2 Mac, CPU on cloud.

**LLM enhancement config** is passed through from the API container to the Marker container via the `/convert` request body. When `MARKER_USE_LLM=true`, the API includes `llm_service`, `llm_model`, and `llm_api_key` in the request. The Marker container builds a `ConfigParser` with these values and passes it to the converter. This keeps all secrets in the API container — the Marker container holds no keys itself.

### Pipeline stages

Upload triggers two sequential async background stages:

**Stage 1 — Converting** (`SSE: agent:converting`)
1. Original file uploaded to S3 (unchanged, as today)
2. `Source` row created with `status = "converting"`
3. File bytes POSTed to Marker container via `MarkerClient`
4. Marker returns JSON: `[{page_num, markdown, images: [{filename, b64}]}, ...]`
5. Each image uploaded to S3 at `{workspace_id}/{source_id}/p{n}-img{i}.{ext}`
6. One `SourcePage` row created per page (`page_num`, `markdown`, `image_s3_keys`, `preview`)
7. Full combined markdown uploaded to S3 as `{workspace_id}/{source_id}/converted.md` → stored in `Source.markdown_s3_key`
8. `Source.status` → `"ingesting"`

**Stage 2 — Ingesting** (`SSE: agent:ingesting → agent:done`)
- Orchestrator ingest agent runs (see Agent Design below)

**Plain text / markdown bypass**
`.md` and `.txt` files skip Marker entirely. Text is chunked at ~4k chars per `SourcePage`. Same DB structure, same agent interface.

---

## Data Model Changes

### New table: `source_pages`

```python
class SourcePage(Base):
    __tablename__ = "source_pages"

    id: Mapped[str]                   # PK
    source_id: Mapped[str]            # FK → sources.id
    page_num: Mapped[int]             # 1-indexed
    markdown: Mapped[str]             # full page markdown
    preview: Mapped[str]              # first ~200 chars, used by list_source_pages()
    image_s3_keys: Mapped[list]       # JSONB, e.g. ["ws/src/p1-img0.png"]
    created_at: Mapped[datetime]
```

### Changes to `Source`

Two new columns:

```python
status: Mapped[str]              # "pending" | "converting" | "ingesting" | "done" | "error"
markdown_s3_key: Mapped[str | None]  # S3 key for full combined markdown
```

---

## Marker Client

`api/app/marker_client.py` — thin HTTP client, one backend today, swappable via config:

```python
class MarkerClient:
    def __init__(self, base_url: str):
        self.base_url = base_url   # MARKER_URL env var

    async def convert(self, data: bytes, filename: str) -> list[PageData]:
        # multipart POST to {base_url}/convert
        # returns structured list of pages with markdown + base64 images
```

Swapping to the hosted Datalab API later = change `MARKER_URL` and update the response parsing if needed. The rest of the codebase is untouched.

---

## Agent Design

### Supported file types via Marker

| Format | Via Marker | Notes |
|--------|-----------|-------|
| PDF | ✓ | |
| DOCX | ✓ | requires `marker-pdf[full]` |
| PPTX | ✓ | requires `marker-pdf[full]` |
| XLSX | ✓ | requires `marker-pdf[full]` |
| PNG / JPG / WEBP | ✓ | |
| .md / .txt | ✗ | chunked directly, no Marker needed |

### New agent tools

**`list_source_pages()`**
Returns all pages for the current source with their preview and image flag. Agent uses this to understand document structure and decide how to partition work.

```json
[
  {"page_num": 1, "has_images": false, "preview": "# Introduction\nThis paper presents..."},
  {"page_num": 2, "has_images": true,  "preview": "## Methodology\nWe sampled 400..."}
]
```

**`read_source_page(page_num)`**
Fetches full markdown for the page from DB. If the page has images:
1. Fetches each image from S3
2. Calls `VISION_MODEL` with the image(s) and surrounding markdown as context
3. Appends vision description inline before returning

The ingest agent never interacts with `VISION_MODEL` directly — it just gets enriched markdown back.

### Orchestrator / sub-agent pattern

**Threshold:** ≤ 20 pages → orchestrator reads directly (no sub-agents).

**> 20 pages:**
- Orchestrator calls `list_source_pages()`, reviews all previews
- Decides partition boundaries based on content (not fixed chunks)
- Spawns sub-agents concurrently via `asyncio.gather`

**Sub-agents** are read-only — they have access to `read_source_page(n)` only, no wiki tools. They read their assigned page range, may read 1–2 adjacent pages for context, and return a structured knowledge summary.

**Orchestrator** collects all summaries, then uses the existing wiki tools (`list_pages`, `search_pages`, `read_page`, `write_page`, `create_page`) to integrate knowledge. Only the orchestrator writes.

**Cost ceilings:** Each sub-agent has its own ceiling (`COST_CEILING_USD`). Orchestrator has its own. Total cost for a large doc = orchestrator + sum of sub-agent costs.

---

## Environment Variables

```bash
# Existing
LITELLM_MODEL=...                # chat agent + orchestrator ingest agent

# Marker service
MARKER_URL=http://marker:8001    # swap to Datalab hosted API URL to go managed

# Marker LLM enhancement (off by default)
MARKER_USE_LLM=false             # set true to enable Marker's second-pass LLM accuracy boost
MARKER_LLM_SERVICE=marker.services.gemini.GoogleGeminiService
                                 # which provider Marker uses for its enhancement pass:
                                 #   marker.services.gemini.GoogleGeminiService  (default)
                                 #   marker.services.claude.ClaudeService
                                 #   marker.services.openai.OpenAIService
                                 #   marker.services.ollama.OllamaService
MARKER_LLM_MODEL=                # optional model override (e.g. gemini-2.0-flash, claude-3-5-haiku)
MARKER_LLM_API_KEY=              # API key for the chosen MARKER_LLM_SERVICE

# Vision model (for pages with extracted images)
VISION_MODEL=gpt-4o              # must be vision-capable; used only when a page has images
                                 # litellm routes by prefix — also set the matching provider key:
                                 #   gpt-4o            → OPENAI_API_KEY
                                 #   claude-3-5-sonnet → ANTHROPIC_API_KEY
                                 #   gemini/gemini-...  → GEMINI_API_KEY

# Provider keys (set whichever your VISION_MODEL and MARKER_LLM_SERVICE need)
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
```

---

## Docker Compose Changes

```yaml
services:
  marker:
    build: ./marker_service
    volumes:
      - marker_models:/root/.cache
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 30s
      start_period: 120s

  api:
    depends_on:
      marker:
        condition: service_healthy
    environment:
      - MARKER_URL=http://marker:8001
      - VISION_MODEL=${VISION_MODEL}

volumes:
  marker_models:
```

---

## New Files

```
marker_service/
  Dockerfile
  main.py          # FastAPI app: POST /convert, GET /health
  requirements.txt # marker-pdf[full], fastapi, uvicorn, python-multipart

api/app/
  marker_client.py          # MarkerClient HTTP wrapper
  agents/ingest_agent.py    # updated: orchestrator + sub-agent pattern
  agents/sub_agent.py       # new: read-only page reader sub-agent
```

### Modified files

```
api/app/models.py           # SourcePage model, Source.status + markdown_s3_key
api/app/routes/ingest.py    # two-stage pipeline, expanded file type support
api/app/agents/tools.py     # list_source_pages(), read_source_page() tools
api/requirements.txt        # httpx (for MarkerClient async HTTP)
docker-compose.yml          # marker service + volume
docker-compose.prod.yml     # same marker service
.env.example                # MARKER_URL, VISION_MODEL
alembic/                    # new migration for SourcePage + Source columns
```

---

## Out of Scope

- Per-page embeddings for semantic search within a source document
- Frontend progress UI for the converting stage (SSE events are emitted; UI wiring is separate)
- Frontend config UI for switching MARKER_USE_LLM / VISION_MODEL (env-var only for now)
