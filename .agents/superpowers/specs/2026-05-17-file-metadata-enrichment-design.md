# File Metadata Enrichment Design

**Date:** 2026-05-17
**Status:** Approved

## Problem

Ingested files display as meaningless hash-based labels (`PNG · B5412F1C`, `JPEG · 92B32CA6`) in the Files sidebar. There is no way to know what a file contains without clicking into it. The two-row display (original + converted.md sub-row) is also noisy and wastes vertical space.

## Goals

- Every file in the sidebar has a human-readable title and a 1-sentence description
- The sidebar is scannable — one row per file
- Original and markdown views remain accessible via a toggle in the viewer
- Users can correct or refine AI-generated metadata via a metadata modal

## Design

### 1. Data Model

Add two nullable columns to the `Source` table:

```
title:       VARCHAR | NULL   -- short human-readable name, max ~80 chars
description: VARCHAR | NULL   -- 1-sentence summary of content, max ~200 chars
```

Both nullable. Existing rows and in-progress ingestions are unaffected. Migration: `ALTER TABLE ADD COLUMN` (no backfill required). The frontend falls back to `{kind} · {id[:8].upper()}` when `title` is null.

### 2. Title/Description Generation (Pipeline)

At the end of `_run_pipeline()` in `api/app/routes/ingest.py`, just before setting `status = "done"`:

1. Take the first ~2000 chars of the converted markdown
2. Make one LLM call with the content and the original `filename` (if present)
3. **Input selection** — choose what to send to the LLM based on available content:
   - `len(converted_markdown.strip()) >= 100`: send the first ~2000 chars of markdown (normal path)
   - `len(converted_markdown.strip()) < 100` AND `kind in {png, jpg, jpeg, webp}`: send the image bytes directly — Claude is multimodal and can generate a meaningful title from the visual content (e.g. "Whiteboard — OAuth2 login flow")
   - `len(converted_markdown.strip()) < 100` AND non-image kind: send just `filename` + `kind` with a prompt that acknowledges limited context; model produces a best-effort title (e.g. "PDF document — no text extracted")
   - Voice notes are transcribed before the pipeline runs, so their markdown is always populated — no special case needed

4. The prompt instructs the model to:
   - Judge whether the filename is already descriptive of the actual content
   - If descriptive: derive a clean title from it (strip extension, fix casing); generate description from content
   - If not descriptive (or filename is null/a hash): generate both title and description from the provided content
5. Parse the JSON response `{ "title": "...", "description": "..." }` and write to the `Source` row

**Error handling:** if the LLM call fails for any reason, swallow the error and leave both fields null. Ingestion completes successfully either way.

### 3. API

**`SourceOut` response model** gains two new fields:
```python
title: str | None
description: str | None
```

Both passed through from the DB row. No other changes to `GET /sources` or `GET /sources/{id}`.

**`SourceItem` TypeScript type** in `frontend/src/api/client.ts` gains `title: string | null` and `description: string | null`.

**New endpoint:**
```
PATCH /api/sources/{id}
Body: { title?: string, description?: string }
Returns: SourceOut
```

Updates only the fields provided. Used by the metadata modal to save user edits.

### 4. Frontend — Sidebar (`FilesList.tsx`)

Replace the two-row-per-file display (original row + converted.md sub-row) with a single row per file:

| Element | Value |
|---|---|
| Icon | Existing file type icon (unchanged) |
| Primary text | `source.title ?? "{kind} · {id.slice(0,8).toUpperCase()}"` |
| Secondary text | `source.description` (only rendered if present) |
| Kind badge | `pdf`, `png`, `jpeg`, `voice`, etc. |
| Status dot | Unchanged (green/red/blue) |
| ⓘ icon | Appears on row hover; opens metadata modal |

The original/markdown sub-rows are removed entirely — view switching moves to the viewer.

### 5. Frontend — Viewer (`FileViewer.tsx`)

Pill toggle added to the viewer header:

- Left: file title
- Right: **Original | Markdown** segmented pill control
- Default: `markdown` if `has_markdown` is true, else `original`
- Toggle only renders when `has_file && has_markdown` — files with only one view show no toggle
- Viewer body logic unchanged; wired to toggle state instead of the removed sub-row clicks

### 6. Frontend — Metadata Modal (`SourceMetaModal.tsx`)

New component triggered by the ⓘ icon on sidebar row hover.

**Editable:**
- Title (text input)
- Description (textarea)
- Save → `PATCH /api/sources/{id}` → invalidate `['sources']` React Query cache

**Read-only:**
- Original filename (if present)
- Kind / file type
- Date ingested
- Status

Scope: metadata editing only. No delete or re-ingest actions.

## Out of Scope

- Backfilling titles/descriptions for existing ingested files
- Bulk rename / batch edit
- Re-generating AI metadata after initial ingestion
