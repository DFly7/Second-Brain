# Extract Agent Prompts to Markdown Files — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all LLM-facing system prompt strings out of Python agent files into standalone `.md` files in `api/app/agents/prompts/`, making prompts easy to find and edit without touching Python code.

**Architecture:** Create `api/app/agents/prompts/` with 8 `.md` files. Each agent loads its prompt(s) via `Path(__file__).parent / "prompts" / "<name>.md").read_text()` at module level. The one dynamic vision caption prompt uses `jinja2.Template(...).render(context=...)` at call time.

**Tech Stack:** Python `pathlib.Path`, `jinja2.Template` (already installed; add to `requirements.txt`)

---

## File Map

| Action | Path |
|--------|------|
| Create | `api/app/agents/prompts/query.md` |
| Create | `api/app/agents/prompts/ingest_small.md` |
| Create | `api/app/agents/prompts/ingest_large.md` |
| Create | `api/app/agents/prompts/health.md` |
| Create | `api/app/agents/prompts/chat_monitor.md` |
| Create | `api/app/agents/prompts/sub_agent.md` |
| Create | `api/app/agents/prompts/vision_caption.md` |
| Create | `api/app/agents/prompts/vision_describe.md` |
| Create | `api/tests/test_prompts.py` |
| Modify | `api/requirements.txt` |
| Modify | `api/app/agents/query_agent.py` |
| Modify | `api/app/agents/ingest_agent.py` |
| Modify | `api/app/agents/health_agent.py` |
| Modify | `api/app/agents/chat_monitor.py` |
| Modify | `api/app/agents/sub_agent.py` |
| Modify | `api/app/agents/tools.py` |

---

## Task 1: Write failing tests

**Files:**
- Create: `api/tests/test_prompts.py`

- [ ] **Step 1: Create the test file**

```python
# api/tests/test_prompts.py
from pathlib import Path
from jinja2 import Template

PROMPTS_DIR = Path(__file__).parent.parent / "app" / "agents" / "prompts"

STATIC_PROMPTS = [
    "query.md",
    "ingest_small.md",
    "ingest_large.md",
    "health.md",
    "chat_monitor.md",
    "sub_agent.md",
    "vision_describe.md",
]


def test_all_prompt_files_exist():
    for name in STATIC_PROMPTS + ["vision_caption.md"]:
        assert (PROMPTS_DIR / name).exists(), f"Missing prompt file: {name}"


def test_static_prompts_are_non_empty():
    for name in STATIC_PROMPTS:
        text = (PROMPTS_DIR / name).read_text().strip()
        assert text, f"Prompt file is empty: {name}"


def test_vision_caption_renders():
    template_text = (PROMPTS_DIR / "vision_caption.md").read_text()
    rendered = Template(template_text).render(context="some document text")
    assert "some document text" in rendered
    assert rendered.strip()


def test_agent_modules_load_prompts():
    from app.agents import query_agent, health_agent, chat_monitor, sub_agent
    assert query_agent.SYSTEM_PROMPT.strip()
    assert health_agent.SYSTEM_PROMPT.strip()
    assert chat_monitor.SYSTEM_PROMPT.strip()
    assert sub_agent.SYSTEM_PROMPT.strip()


def test_ingest_agent_loads_both_prompts():
    from app.agents import ingest_agent
    assert ingest_agent.SYSTEM_PROMPT_SMALL.strip()
    assert ingest_agent.SYSTEM_PROMPT_LARGE.strip()
    assert ingest_agent.SYSTEM_PROMPT_SMALL != ingest_agent.SYSTEM_PROMPT_LARGE
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd api && python -m pytest tests/test_prompts.py -v
```

Expected: FAIL — `prompts/` directory does not exist yet, so `test_all_prompt_files_exist` and `test_static_prompts_are_non_empty` fail. The module import tests pass at this stage because the agent files still contain inline strings.

---

## Task 2: Add Jinja2 to requirements and create the prompts directory with all 8 files

**Files:**
- Modify: `api/requirements.txt`
- Create: `api/app/agents/prompts/query.md`
- Create: `api/app/agents/prompts/ingest_small.md`
- Create: `api/app/agents/prompts/ingest_large.md`
- Create: `api/app/agents/prompts/health.md`
- Create: `api/app/agents/prompts/chat_monitor.md`
- Create: `api/app/agents/prompts/sub_agent.md`
- Create: `api/app/agents/prompts/vision_caption.md`
- Create: `api/app/agents/prompts/vision_describe.md`

- [ ] **Step 1: Add Jinja2 to requirements.txt**

Add this line to `api/requirements.txt`:
```
jinja2==3.1.3
```

- [ ] **Step 2: Create `api/app/agents/prompts/query.md`**

```
You are a knowledgeable assistant with access to the user's personal wiki.
When answering questions:
1. Call read_page("meta/index") first to see the full wiki structure and find relevant pages.
2. Use search_pages() to narrow down if needed.
3. Use read_page() to read up to 5 of the most relevant pages in full.
4. Answer based on what you find. Cite pages using their full slug: [[people/alice-jones]].
5. If the wiki doesn't contain the answer, say so clearly.
You may only read pages — do not write or create anything.
```

- [ ] **Step 3: Create `api/app/agents/prompts/ingest_small.md`**

```
You are an agent that maintains a personal knowledge wiki.
You have been given a source document split into pages. Integrate its knowledge into the wiki.

IMPORTANT — Slug conventions:
- Every page MUST have a folder prefix. Always use full-path slugs: people/alice-jones, concepts/knowledge-management.
- Top-level folders: people/ (individuals), concepts/ (ideas/frameworks), projects/ (ongoing work),
  sources/ (per-source summaries), meta/ (system pages — do not write here).
- Use sub-folders freely within these: people/investors/alice-jones is fine.
- Wikilinks must use the full path: [[people/alice-jones]], NOT [[alice-jones]].

Process:
1. Call read_page("meta/index") to see the current wiki structure.
2. Call list_source_pages() to see the document structure and previews.
3. Read pages with read_source_page(). Read all pages — they are manageable in size.
4. Call search_pages() to find related wiki pages before writing.
5. Write changes using write_page() or create_page(). Prefer updating existing pages.
6. When done, stop calling tools.

Write clear markdown. Use [[full/path/wikilinks]] to link related pages.
```

- [ ] **Step 4: Create `api/app/agents/prompts/ingest_large.md`**

```
You are an agent that maintains a personal knowledge wiki.
You have been given a large source document split into pages. Integrate its knowledge into the wiki.

IMPORTANT — Slug conventions:
- Every page MUST have a folder prefix. Always use full-path slugs: people/alice-jones, concepts/knowledge-management.
- Top-level folders: people/ (individuals), concepts/ (ideas/frameworks), projects/ (ongoing work),
  sources/ (per-source summaries), meta/ (system pages — do not write here).
- Use sub-folders freely within these: people/investors/alice-jones is fine.
- Wikilinks must use the full path: [[people/alice-jones]], NOT [[alice-jones]].

Process:
1. Call read_page("meta/index") to see the current wiki structure.
2. Call list_source_pages() to see the full document structure with previews.
3. Call spawn_page_reader() MULTIPLE TIMES IN THE SAME RESPONSE to read sections concurrently.
   Each call assigns a page range to a sub-agent that reads and summarises it.
   Group related pages together. Use focus_hint to guide each sub-agent.
4. After receiving all summaries, integrate knowledge into the wiki:
   - Call search_pages() to find related pages.
   - Write changes using write_page() or create_page(). Prefer updating existing pages.
5. When done, stop calling tools.

Write clear markdown. Use [[full/path/wikilinks]] to link related pages.
```

- [ ] **Step 5: Create `api/app/agents/prompts/health.md`**

```
You are a wiki health agent. Your job is to fix and report issues in the wiki.

Run these steps in order:

1. Call list_pages() to get all pages.
2. Call read_page("meta/index") to load the current index.
3. Regenerate meta/index from scratch using write_page("meta/index", ...) with all pages grouped
   by folder (slug prefix). Format:
     ## people/ (N pages)
     - [[people/alice]] — one-line summary
4. For each page (sample up to 20 if large wiki):
   a. Call read_page(slug) to read its content.
   b. Find [[wikilinks]] that reference slugs not in the page list — these are broken links.
   c. If you can identify the correct target page, fix the link with write_page().
   d. Find plain-text mentions of other page titles/slugs not wrapped in [[]] — add wikilinks.
5. Identify orphan pages: pages that appear in list_pages() but are not linked from any other page.
   Do NOT delete them — just note them.
6. Write meta/health-report with two sections:
   ## Fixed
   - list every patch made (what was broken, what you changed)
   ## Needs attention
   - orphan pages with suggested actions
   - broken links you could not resolve
   - any contradictions or gaps you noticed

Be thorough but do not invent facts. Only fix what you are confident about.
```

- [ ] **Step 6: Create `api/app/agents/prompts/chat_monitor.md`**

```
You are a background agent that reads chat transcripts and decides what to save to the user's wiki.

Review the conversation and identify anything worth retaining permanently:
- Decisions made ("I decided to...", "We agreed that...")
- Facts learned or confirmed
- Ideas worth developing
- Commitments or plans
- Insights or realisations

Do NOT ingest casual back-and-forth, clarifying questions, or content already well-covered in the wiki.

If you find something worth saving:
1. Use search_pages() to check if it already exists.
2. Use write_page() to add it to an existing page, or create a new one.

If nothing in the conversation is worth saving, do nothing.
```

- [ ] **Step 7: Create `api/app/agents/prompts/sub_agent.md`**

```
You are a document reading assistant. You have been given a range of pages from a source document.

Process:
1. Read each page in your assigned range using read_source_page().
2. You may read 1-2 pages beyond your range if something appears cut off.
3. Return a comprehensive knowledge summary — key concepts, facts, data, arguments.

Do not write to the wiki. Only read and summarise.
```

- [ ] **Step 8: Create `api/app/agents/prompts/vision_caption.md`**

```
Describe this image in the context of the surrounding document text:

{{ context }}
```

- [ ] **Step 9: Create `api/app/agents/prompts/vision_describe.md`**

```
Describe this image in detail.
```

- [ ] **Step 10: Run the file-existence tests to verify they now pass**

```bash
cd api && python -m pytest tests/test_prompts.py::test_all_prompt_files_exist tests/test_prompts.py::test_static_prompts_are_non_empty tests/test_prompts.py::test_vision_caption_renders -v
```

Expected: PASS for the three file-level tests. Module import tests still fail because the agents still read from inline strings, not from files.

---

## Task 3: Update `query_agent.py`

**Files:**
- Modify: `api/app/agents/query_agent.py`

- [ ] **Step 1: Replace the inline prompt string**

Replace the top of the file from:

```python
SYSTEM_PROMPT = """You are a knowledgeable assistant with access to the user's personal wiki.
When answering questions:
1. Call read_page("meta/index") first to see the full wiki structure and find relevant pages.
2. Use search_pages() to narrow down if needed.
3. Use read_page() to read up to 5 of the most relevant pages in full.
4. Answer based on what you find. Cite pages using their full slug: [[people/alice-jones]].
5. If the wiki doesn't contain the answer, say so clearly.
You may only read pages — do not write or create anything."""
```

To:

```python
from pathlib import Path

_PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS / "query.md").read_text()
```

- [ ] **Step 2: Run tests**

```bash
cd api && python -m pytest tests/test_prompts.py::test_agent_modules_load_prompts -v -k "query"
```

Expected: The query_agent portion of `test_agent_modules_load_prompts` now passes.

---

## Task 4: Update `ingest_agent.py`

**Files:**
- Modify: `api/app/agents/ingest_agent.py`

- [ ] **Step 1: Replace both inline prompt strings**

Replace:

```python
SYSTEM_PROMPT_SMALL = """You are an agent that maintains a personal knowledge wiki.
...
Write clear markdown. Use [[full/path/wikilinks]] to link related pages."""

SYSTEM_PROMPT_LARGE = """You are an agent that maintains a personal knowledge wiki.
...
Write clear markdown. Use [[full/path/wikilinks]] to link related pages."""
```

With:

```python
from pathlib import Path

_PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT_SMALL = (_PROMPTS / "ingest_small.md").read_text()
SYSTEM_PROMPT_LARGE = (_PROMPTS / "ingest_large.md").read_text()
```

- [ ] **Step 2: Run tests**

```bash
cd api && python -m pytest tests/test_prompts.py::test_ingest_agent_loads_both_prompts -v
```

Expected: PASS.

---

## Task 5: Update `health_agent.py`

**Files:**
- Modify: `api/app/agents/health_agent.py`

- [ ] **Step 1: Replace the inline prompt string**

Replace:

```python
SYSTEM_PROMPT = """You are a wiki health agent. Your job is to fix and report issues in the wiki.
...
Be thorough but do not invent facts. Only fix what you are confident about."""
```

With:

```python
from pathlib import Path

_PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS / "health.md").read_text()
```

- [ ] **Step 2: Run tests**

```bash
cd api && python -m pytest tests/test_prompts.py::test_agent_modules_load_prompts -v
```

Expected: PASS (health_agent portion passes).

---

## Task 6: Update `chat_monitor.py`

**Files:**
- Modify: `api/app/agents/chat_monitor.py`

- [ ] **Step 1: Replace the inline prompt string**

Replace:

```python
SYSTEM_PROMPT = """You are a background agent that reads chat transcripts and decides what to save to the user's wiki.
...
If nothing in the conversation is worth saving, do nothing."""
```

With:

```python
from pathlib import Path

_PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS / "chat_monitor.md").read_text()
```

- [ ] **Step 2: Run tests**

```bash
cd api && python -m pytest tests/test_prompts.py::test_agent_modules_load_prompts -v
```

Expected: PASS.

---

## Task 7: Update `sub_agent.py`

**Files:**
- Modify: `api/app/agents/sub_agent.py`

- [ ] **Step 1: Replace the inline prompt string**

Replace:

```python
SYSTEM_PROMPT = """You are a document reading assistant. You have been given a range of pages from a source document.
...
Do not write to the wiki. Only read and summarise."""
```

With:

```python
from pathlib import Path

_PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS / "sub_agent.md").read_text()
```

- [ ] **Step 2: Run all module-load tests**

```bash
cd api && python -m pytest tests/test_prompts.py::test_agent_modules_load_prompts tests/test_prompts.py::test_ingest_agent_loads_both_prompts -v
```

Expected: PASS.

---

## Task 8: Update `tools.py` vision prompts

**Files:**
- Modify: `api/app/agents/tools.py`

- [ ] **Step 1: Add imports and load vision_describe at module level**

At the top of `tools.py`, after existing imports, add:

```python
from pathlib import Path
from jinja2 import Template

_PROMPTS = Path(__file__).parent / "prompts"
_VISION_CAPTION_TEMPLATE = Template((_PROMPTS / "vision_caption.md").read_text())
_VISION_DESCRIBE_PROMPT = (_PROMPTS / "vision_describe.md").read_text()
```

- [ ] **Step 2: Replace the inline caption string in `_ensure_vision_captions`**

Find this line (around line 47):

```python
"text": f"Describe this image in the context of the surrounding document text:\n\n{markdown[:500]}",
```

Replace with:

```python
"text": _VISION_CAPTION_TEMPLATE.render(context=markdown[:500]),
```

- [ ] **Step 3: Replace the inline describe string in `describe_image`**

Find this line (around line 276):

```python
"text": "Describe this image in detail.",
```

Replace with:

```python
"text": _VISION_DESCRIBE_PROMPT,
```

- [ ] **Step 4: Run full test suite**

```bash
cd api && python -m pytest tests/test_prompts.py -v
```

Expected: All 5 tests PASS.

---

## Task 9: Commit

- [ ] **Step 1: Stage and commit all changes**

```bash
cd api && git add \
  requirements.txt \
  app/agents/prompts/ \
  app/agents/query_agent.py \
  app/agents/ingest_agent.py \
  app/agents/health_agent.py \
  app/agents/chat_monitor.py \
  app/agents/sub_agent.py \
  app/agents/tools.py \
  tests/test_prompts.py
git commit -m "refactor: extract agent system prompts to markdown files in prompts/"
```
