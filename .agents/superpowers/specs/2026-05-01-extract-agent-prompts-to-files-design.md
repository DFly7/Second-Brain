# Design: Extract Agent System Prompts to Markdown Files

**Date:** 2026-05-01  
**Status:** Approved

---

## Goal

Move all LLM-facing system prompt strings out of Python source files and into standalone `.md` files in a `prompts/` directory co-located with the agents. This makes prompts easy to find, read, and edit without touching Python code.

---

## File Structure

```
api/app/agents/prompts/
    query.md              ← query_agent.py SYSTEM_PROMPT
    ingest_small.md       ← ingest_agent.py SYSTEM_PROMPT_SMALL
    ingest_large.md       ← ingest_agent.py SYSTEM_PROMPT_LARGE
    health.md             ← health_agent.py SYSTEM_PROMPT
    chat_monitor.md       ← chat_monitor.py SYSTEM_PROMPT
    sub_agent.md          ← sub_agent.py SYSTEM_PROMPT
    vision_caption.md     ← tools.py inline caption string (has {{ context }} variable)
    vision_describe.md    ← tools.py inline describe string (static)
```

---

## Loading Pattern

### Static prompts (all agents)

Module-level constant, loaded once at import time using `pathlib.Path`:

```python
from pathlib import Path

_PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS / "query.md").read_text()
```

`ingest_agent.py` loads two files:

```python
SYSTEM_PROMPT_SMALL = (_PROMPTS / "ingest_small.md").read_text()
SYSTEM_PROMPT_LARGE = (_PROMPTS / "ingest_large.md").read_text()
```

### Dynamic prompt (vision caption in tools.py)

`vision_caption.md` contains `{{ context }}` where the surrounding document excerpt is injected. Rendered at call time using `jinja2.Template`:

```python
from jinja2 import Template
from pathlib import Path

_PROMPTS = Path(__file__).parent / "prompts"

# at call site inside _ensure_vision_captions:
caption_prompt = Template((_PROMPTS / "vision_caption.md").read_text()).render(context=markdown[:500])
```

`vision_describe.md` is static — loaded with plain `read_text()` alongside the other prompts, cached as a module-level constant.

---

## What Changes

| File | Change |
|------|--------|
| `query_agent.py` | Replace inline `SYSTEM_PROMPT` string with `Path` load |
| `ingest_agent.py` | Replace `SYSTEM_PROMPT_SMALL` and `SYSTEM_PROMPT_LARGE` strings with `Path` loads |
| `health_agent.py` | Replace inline `SYSTEM_PROMPT` string with `Path` load |
| `chat_monitor.py` | Replace inline `SYSTEM_PROMPT` string with `Path` load |
| `sub_agent.py` | Replace inline `SYSTEM_PROMPT` string with `Path` load |
| `tools.py` | Replace two inline vision strings with `Path` loads; use `jinja2.Template` for caption |
| `api/app/agents/prompts/` | New directory with 8 `.md` files |

---

## Constraints

- No new loader abstraction — `Path` and `jinja2.Template` directly at the call site.
- Jinja2 is used only for `vision_caption.md`; all other files are plain `read_text()`.
- Prompt content is unchanged — this is a pure structural refactor.
- Fails fast at startup if any prompt file is missing (import-time read).
