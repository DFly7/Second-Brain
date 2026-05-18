# LLM Wiki v0 — Architecture

This document describes what is **running in this repository** and how pieces connect. It complements the [design spec](../.agents/superpowers/plans/2026-04-28-llm-wiki-v0-design.md).

---

## 1. System context (dev)

```mermaid
flowchart TB
  User([User / browser])
  subgraph local["Docker Compose (dev)"]
    FE[Frontend\nReact + Vite :5173]
    API[API\nFastAPI :8000]
    DB[(Postgres\npgvector + FTS)]
    MINIO[(MinIO\nS3 API :9000)]
  end
  GEMINI[[Google Gemini\nvia LiteLLM]]

  User --> FE
  FE -->|"REST + SSE\n(Vite proxies /api)"| API
  API --> DB
  API --> MINIO
  API --> GEMINI
```

---

## 2. Compose services (development)

```mermaid
flowchart LR
  subgraph compose["docker compose"]
    FE["frontend :5173"]
    API["api :8000"]
    DB["db :5432\nPostgres + pgvector"]
    S3["minio :9000"]
  end
  Browser((Browser))
  Browser --> FE
  FE -->|"Vite proxy /api → api:8000"| API
  API --> DB
  API --> S3
```

Volumes: Postgres data and MinIO data persist in named volumes until removed.

---

## 3. Backend modules (logical)

```mermaid
flowchart TB
  subgraph http["FastAPI routers"]
    A["/auth"]
    W["/wiki"]
    I["/ingest"]
    C["/chat"]
    AC["/activity"]
    AU["/automations"]
  end
  subgraph agents["Agents (LiteLLM loops)"]
    ING["ingest_agent"]
    QRY["query_agent"]
    MON["chat_monitor"]
    AUTO["automation_agent"]
  end
  BA["browser-agent\nPlaywright + noVNC"]
  subgraph core["Shared"]
    T["AgentTools\nlist/search/read/write"]
    SSE["SSE broadcaster"]
    SRCH["search.py\nFTS + vector SQL"]
  end
  DB[(Postgres)]
  S3[(MinIO)]

  I --> ING
  C --> QRY
  C --> MON
  AU --> AUTO
  ING --> T
  QRY --> T
  MON --> T
  AUTO --> T
  AUTO -->|HTTP :8001| BA
  ING --> SSE
  QRY --> SSE
  MON --> SSE
  AUTO --> SSE
  T --> DB
  T --> SRCH
  W --> DB
  I --> S3
  I --> DB
  C --> DB
  AC --> DB
```

Background work: ingest and chat monitor are triggered from route handlers (e.g. FastAPI `BackgroundTasks`) after rows are committed.

---

## 4. Ingest pipeline

```mermaid
sequenceDiagram
  participant U as User
  participant FE as Frontend
  participant API as FastAPI /ingest
  participant DB as Postgres
  participant S3 as MinIO
  participant AG as ingest_agent
  participant LLM as LiteLLM / Gemini

  U->>FE: Upload / paste / URL
  FE->>API: POST /ingest/*
  API->>API: Extract text (pdf/docx/url/md/txt)
  API->>S3: put_object (if file)
  API->>DB: INSERT source
  API-->>FE: 200 source_id
  API->>AG: background run(source_id)
  loop tool rounds
    AG->>LLM: acompletion + tools
    LLM-->>AG: tool_calls
    AG->>DB: read/write pages via AgentTools
  end
  AG->>DB: activity_log + commit
  AG->>SSE: agent:done
```

---

## 5. Chat + SSE

```mermaid
sequenceDiagram
  participant U as User
  participant FE as Frontend
  participant API as FastAPI
  participant AG as query_agent
  participant LLM as LiteLLM / Gemini

  U->>FE: Send message
  FE->>API: POST /chat/message
  API->>AG: run(question, history)
  loop until answer
    AG->>LLM: acompletion (read-only tools)
    LLM-->>AG: tool_calls or content
    AG->>API: tool results in memory
  end
  AG-->>API: answer, cited_pages
  API-->>FE: JSON

  Note over FE,API: Parallel: EventSource cannot set Authorization header
  FE->>API: GET /chat/sse?token=JWT
  API-->>FE: text/event-stream
  Note over API,SSE: Agent publishes agent:reading / agent:writing / agent:done
```

---

## 6. Data stores (conceptual)

| Store | Contents |
|-------|-----------|
| **Postgres** | Workspaces, pages, revisions, `page_links`, sources, activity_log, chat sessions/messages; generated `tsv` on pages; optional `embedding` (1536-d) for hybrid search |
| **MinIO** | Raw binaries for file ingests (PDF, DOCX, etc.) |
| **Env** | `GEMINI_API_KEY`, `LITELLM_MODEL`, JWT and S3 settings — see `.env.example` |

---

## 7. Known integration notes

- **Gemini + tool history:** Assistant turns with **empty** JSON tool arguments (`{}`) used to break LiteLLM’s Gemini serializer on the *next* request. This repo normalizes those payloads in `api/app/agents/assistant_message.py` and pins a **newer LiteLLM** than the original plan where practical — see `api/requirements.txt`.
- **Pytest in Docker:** `tests/` is bind-mounted into the API container; `tests/conftest.py` forces test DB URL and credentials so a host `.env` does not break CI-style runs.

---

## 8. Automations (browser agent)

LLM-driven browser control with live noVNC and run recordings. **Full write-up:** [automation-agent.md](automation-agent.md).

---

## 9. Production

Use `docker-compose.prod.yml` (API + DB + MinIO + **browser-agent** + nginx-built frontend). Ensure `.env` includes Postgres init variables if the DB volume is new. Build: `docker compose -f docker-compose.prod.yml build`.

Pi: build `browser-agent` with `--build-arg ARCH=arm64` when using `CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium-browser` — see [automation-agent.md](automation-agent.md).
