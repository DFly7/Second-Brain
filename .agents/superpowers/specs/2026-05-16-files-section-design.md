# Files Section — Design Spec

**Date:** 2026-05-16
**Status:** Approved

## Overview

Add a Files section to the Second Brain app: a dedicated view where the user can browse all ingested sources, view the original file, and read the converted markdown. Accessible via a top-bar tab alongside the existing Wiki view.

---

## Architecture

### Frontend Routing

Install `react-router-dom`. `App.tsx` wraps authenticated content in `<BrowserRouter><Routes>`:

- `/` → redirect to `/wiki`
- `/wiki` → `<Layout />` (current wiki view, unchanged)
- `/files` → `<FilesView />`

The auth gate wraps the router; both routes are protected identically.

The top bar is extracted from `Layout.tsx` into a shared `<TopBar />` component used by both views. It contains Wiki/Files `<Link>` tabs (active tab highlighted) and the Sign out button. `agentStatus` is passed as a prop and only shown when on the wiki tab.

### Backend

New route file: `api/app/routes/sources.py`, registered in `main.py`.

**New endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/sources` | List all sources for the workspace, newest-first |
| `GET` | `/sources/{id}/file` | Proxy original file bytes from MinIO with correct `Content-Type` |
| `GET` | `/sources/{id}/markdown` | Proxy converted markdown text from MinIO |

**Model change:** Add `filename: str | None` column to `Source`. Populated from `file.filename` on upload in `ingest.py`. URL sources store the URL as filename. Text sources store the title. Existing rows get `null`; the frontend falls back to `{kind} · {id[:8]}`.

New Alembic migration: `alembic revision --autogenerate -m "add filename to sources"`.

---

## Components

### `FilesView.tsx`

Top-level layout for `/files`. Holds state:
- `selectedSourceId: string | null`
- `selectedView: 'original' | 'markdown'`

Renders a two-panel split: `<FilesList>` on the left (fixed width, scrollable), `<FileViewer>` on the right (fills remaining space).

### `FilesList.tsx`

Left panel. Fetches `GET /api/sources` via React Query (`['sources']`). Renders each source as a labelled group containing two clickable rows:

```
report.pdf                    ← group label (filename or fallback)
  📄 report.pdf   [original]  ← clickable row
  📝 converted.md [markdown]  ← clickable row
```

- Status badge next to the group label: `converting` / `ingesting` / `done` / `error`
- Active selection highlighted
- Query refetches on window focus

### `FileViewer.tsx`

Right panel. Receives `source` (full source object from the list) and `view: 'original' | 'markdown'`. The parent `FilesView` passes the selected source object down so `FileViewer` has `kind` and `status` without a separate fetch.

**Markdown view:**
- Fetches `GET /api/sources/{id}/markdown` with auth headers
- Renders with `ReactMarkdown` (remarkGfm + remarkMath + rehypeKatex, same as `WikiContent`)
- Header contains a Rendered/Raw toggle button
- Raw mode shows the markdown text in a `<pre>` block
- If source status is `converting` or `ingesting`: shows "Still processing…" without fetching
- If source status is `error`: shows "Conversion failed — no markdown available"

**Original view:**
- Fetches `GET /api/sources/{id}/file` via `fetch()` with auth headers
- Converts response to a blob URL (`URL.createObjectURL`)
- Cleans up blob URL on unmount via `URL.revokeObjectURL`
- Renders based on `kind`:
  - `pdf` → `<iframe src={blobUrl} />`
  - `png` / `jpg` / `jpeg` / `webp` → `<img src={blobUrl} />`
  - `docx` / `pptx` / `xlsx` and variants → download button + open-in-tab link (no embed)
  - `url` / `text` / `md` → "No original file" note
- Header always shows download and open-in-tab buttons regardless of type

### `TopBar.tsx`

Extracted from `Layout.tsx`. Props: `agentStatus: string | null`. Contains:
- App title ("LLM Wiki")
- Wiki and Files `<Link>` nav tabs (active tab highlighted via `useMatch`)
- Sign out button
- `+ Ingest` button (opens ingest modal; hidden on the files tab)

---

## Data Flow

**Source listing:** React Query query `['sources']` → `GET /api/sources`. Invalidated on `agent:done` SSE event so status badges update live. The SSE subscription currently lives in `Layout.tsx`; it needs to be accessible to `FilesView` as well — move it to a shared `useSse` hook called from both views (or from `App.tsx` above the router).

**File content:** React Query query `[sourceId, view]`. Both original and markdown fetches use the existing API client pattern (Bearer token from sessionStorage). Response converted to blob URL for use as `src`. Query is disabled when source status is not `done`.

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| Source list fails | "Failed to load files" + retry button in left panel |
| File content fails | "Could not load file" + retry button in right pane |
| Source `status: 'error'` | Red badge in list; markdown pane shows "Conversion failed" |
| Source still processing | Markdown/original pane shows "Still processing…"; no fetch attempted |
| URL/text source — original clicked | Right pane shows "Web source — no file to display" |
| Source not found / wrong workspace | API returns 404; frontend shows "File not found" in right pane |

---

## Backend API Detail

### `GET /sources`

Response:
```json
[
  {
    "id": "uuid",
    "kind": "pdf",
    "filename": "report.pdf",
    "status": "done",
    "has_file": true,
    "has_markdown": true,
    "created_at": "2026-05-16T10:00:00"
  }
]
```

`has_file` is `s3_key is not None`. `has_markdown` is `markdown_s3_key is not None`.

### `GET /sources/{id}/file`

- 404 if `s3_key` is null or source belongs to different workspace
- Streams bytes from MinIO with `Content-Type` derived from `kind`
- Uses FastAPI `StreamingResponse` to stream bytes from MinIO

### `GET /sources/{id}/markdown`

- 404 if `markdown_s3_key` is null or source belongs to different workspace
- Returns markdown text with `Content-Type: text/markdown`

---

## Testing

New test file: `tests/test_sources.py`

- `GET /sources` returns correct list, newest-first
- `GET /sources/{id}/file` returns correct bytes and `Content-Type`
- `GET /sources/{id}/markdown` returns correct markdown text
- Both file endpoints return 404 when `s3_key` / `markdown_s3_key` is null
- Both file endpoints return 404 for a source from a different workspace
- `GET /sources/{id}/file` returns 404 for `kind='url'` source

---

## Out of Scope

- Deleting sources
- Searching or filtering the file list
- Page-by-page navigation within multi-page sources (combined markdown shown)
- Storing the original source URL for `kind='url'` sources
