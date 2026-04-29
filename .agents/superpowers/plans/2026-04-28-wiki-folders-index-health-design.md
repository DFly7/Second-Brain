# Wiki Folders, Index & Health Agent — Design Spec

**Date:** 2026-04-28  
**Status:** Approved  
**Author:** Darragh Flynn

---

## 1. What we're building

Three tightly related features that turn the flat wiki into an organised, self-maintaining knowledge base:

1. **Folder organisation** — pages are filed under agent-decided folder prefixes encoded directly in the slug
2. **`meta/index` page** — a structured, incrementally-maintained table of contents the agent reads first on every query
3. **Wiki-health agent** — a fix-and-report agent triggered manually or after every N ingests

---

## 2. Folder Organisation

### Approach

Slug-as-path. The `slug` column in Postgres becomes the full folder path. No new columns or migrations needed.

Examples:
- `people/alice-jones`
- `concepts/knowledge-management`
- `projects/second-brain`
- `sources/gemini-api-docs`
- `meta/index`
- `meta/health-report`

### Top-level taxonomy (seeded in agent prompt / CLAUDE.md)

| Folder | Contents |
|--------|----------|
| `people/` | Individuals — founders, investors, contacts |
| `concepts/` | Ideas, frameworks, mental models |
| `projects/` | Ongoing or past projects |
| `sources/` | Per-source summary pages written by ingest agent |
| `meta/` | System pages — index, health-report, log. Reserved, not user knowledge. |

The agent classifies on write. It may create sub-folders freely within the top-level taxonomy (e.g. `people/investors/`). The top-level folders above are fixed.

### Slug validation

- Allow `/` in slugs
- Enforce at least one `/` prefix (every page must be in a folder)
- Uniqueness constraint stays on `(workspace_id, slug)` — no change

### Wikilinks

Full-path slugs are canonical: `[[people/alice-jones]]`. The existing `wikilinks.py` exact-match resolution requires no change. No short-name resolution — explicit only.

---

## 3. `meta/index` Page

### Purpose

A structured table of contents the agent reads first before deciding which pages to drill into. Optimised for agent navigation — compact, folder-grouped, slug + one-liner per entry.

### Format

```markdown
# Wiki Index

_Last updated: 2026-04-28 by ingest_agent_

## people/ (12 pages)
- [[people/alice-jones]] — Co-founder of Acme Corp, met 2024-03
- [[people/bob-smith]] — VC at Sequoia, infra focus

## concepts/ (8 pages)
- [[concepts/knowledge-management]] — PKM patterns and tools

## meta/ (3 pages)
- [[meta/index]] — This file
- [[meta/health-report]] — Last health check results
```

### Storage

A regular `Page` row in Postgres with `slug = "meta/index"`. No special treatment — the agent reads and writes it via the existing `read_page` / `write_page` tools.

### Update strategy

**Incremental (default):** After every `write_page` call, the ingest agent reads `meta/index`, patches only the folder section that changed (adds/updates the entry for the written page), and writes it back. One extra tool round per ingest.

**Full regeneration (health agent):** The health agent scans all pages and rewrites `meta/index` from scratch. This is the correction pass — fixes drift caused by page moves, deletes, or incremental patch failures.

### Agent workflow change

`query_agent` reads `meta/index` first on every query in place of (or before) calling `list_pages`. This gives it a richer, structured view of what's in the wiki before deciding what to read.

---

## 4. Wiki-Health Agent

### Triggers

| Trigger | Mechanism |
|---------|-----------|
| Manual | `POST /health/run` — UI button in sidebar |
| Automatic | After every N ingests (N configurable, default `10`) — counter checked in ingest route post-completion |

### What the agent does (in order)

1. **Regenerate `meta/index`** — full scan of all pages, rewrite from scratch
2. **Fix broken wikilinks** — find `[[slug]]` references in `body_md` that resolve to no page; attempt to find the correct target and patch, or flag
3. **Add missing cross-references** — find pages that mention another page's title/slug in plain text but don't use `[[]]` syntax; add wikilinks where confident
4. **Flag orphan pages** — pages with no inbound `page_links`; report for human review (don't auto-delete)
5. **Write `meta/health-report`** — two sections:
   - **Fixed** — list of every patch made with before/after
   - **Needs attention** — orphans, unresolved broken links, suggested topics to investigate

### `meta/health-report` format

```markdown
# Health Report

_Run: 2026-04-28 14:32 | Trigger: manual | Pages scanned: 47_

## Fixed
- Regenerated `meta/index` (47 entries)
- Fixed broken wikilink in `concepts/rag` → `[[concepts/retrieval-augmented-generation]]`
- Added cross-reference in `people/alice-jones` → `[[projects/second-brain]]`

## Needs attention
- **Orphan pages (no inbound links):** `sources/old-article-2024`, `concepts/memex`
  - Suggestion: link from relevant pages or merge into a broader concept page
- **Unresolved broken links:**
  - `projects/second-brain` references `[[people/bob-jones]]` — no page found, consider creating
```

### Implementation pattern

Same pattern as `ingest_agent` — `BackgroundTask`, `AgentTools`, SSE events (`agent:reading`, `agent:writing`, `health:done`) so the UI shows it running live.

New route: `POST /health/run` → fires `HealthAgent` as a `BackgroundTask`.

Auto-trigger: `ingest_route` increments a counter (stored in `Workspace` or a simple config row); when `counter % N == 0`, fires health agent as an additional `BackgroundTask`.

---

## 5. UI — Sidebar Folder Tree

### From

Flat alphabetical list of page titles.

### To

Collapsible folder tree grouped by slug prefix:

```
▼ people/        (12)
    alice-jones
    bob-smith
▶ concepts/      (8)
▶ projects/      (3)
▶ meta/          (3)    ← shown last, visually de-emphasised
```

### Behaviour

- Folders collapse/expand on click
- Expand/collapse state persisted in `localStorage` per workspace (so collapsed folders stay collapsed across page refreshes)
- `meta/` always rendered last and styled differently (muted colour — system pages)
- Active page highlighted in tree
- Clicking a page navigates as today

### Health run button

Sits at the bottom of the sidebar. One click → `POST /health/run`. SSE shows the agent running live (same visual treatment as ingest). Button is disabled while a health run is in progress.

---

## 6. Out of scope

| Item | Reason |
|------|--------|
| Short-name wikilink resolution | Adds ambiguity; full-path is explicit and simpler |
| Auto-delete of orphan pages | Too destructive to automate; human reviews the report |
| Graph view | Post-v0 |
| Multi-level folder UI (deeply nested trees) | Top-level taxonomy is shallow; not needed yet |
