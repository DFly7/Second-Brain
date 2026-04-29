# Vision Caption Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run vision once per image, bake the caption inline into `SourcePage.markdown`, and never call the vision model again for that page. Add a `describe_image` agent tool for manual retries.

**Architecture:** A `vision_processed` boolean flag on `SourcePage` is the single cache signal. A private `_ensure_vision_captions` helper in `tools.py` checks the flag, runs vision for each image, inserts caption blocks inline in `page.markdown` immediately after each matching image reference, then commits and flips `vision_processed = True`. `read_source_page` calls the helper before returning, so the agent always gets fully-described markdown with zero extra round-trips after the first read. A new `describe_image` tool lets the agent manually describe any image by s3_key without touching the DB.

**Tech Stack:** Python 3.11, SQLAlchemy async, Alembic, litellm, boto3/MinIO (via `download_file`), pytest + unittest.mock

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `api/app/models.py` | Add `vision_processed` column to `SourcePage` |
| Create | `api/alembic/versions/XXXX_add_vision_processed.py` | Migration: add boolean column with `server_default='false'` |
| Modify | `api/app/agents/tools.py` | Add `_ensure_vision_captions` helper, update `read_source_page`, add `describe_image` method + tool schema + dispatch |
| Modify | `tests/test_agents.py` | Update existing vision test, add new tests for helper and `describe_image` |

---

## Task 1: Add `vision_processed` to `SourcePage` model

**Files:**
- Modify: `api/app/models.py:78-88`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write a failing test**

Add to `tests/test_models.py`:

```python
def test_source_page_has_vision_processed_field():
    from app.models import SourcePage
    page = SourcePage(
        source_id="src-1",
        page_num=1,
        markdown="# Hello",
        preview="# Hello",
        image_s3_keys=[],
    )
    assert page.vision_processed is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /app && pytest tests/test_models.py::test_source_page_has_vision_processed_field -v
```

Expected: `AttributeError: vision_processed`

- [ ] **Step 3: Add `vision_processed` column to `SourcePage`**

In `api/app/models.py`, add the `Boolean` import and column:

```python
# Change this import line:
from sqlalchemy import DateTime, ForeignKey, String, Text
# To:
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
```

Then add the column to `SourcePage` (after `image_s3_keys`):

```python
class SourcePage(Base):
    __tablename__ = "source_pages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    page_num: Mapped[int] = mapped_column(nullable=False)
    markdown: Mapped[str] = mapped_column(Text, default="")
    preview: Mapped[str] = mapped_column(Text, default="")
    image_s3_keys: Mapped[list] = mapped_column(JSONB, default=list)
    vision_processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /app && pytest tests/test_models.py::test_source_page_has_vision_processed_field -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/models.py tests/test_models.py
git commit -m "feat: add vision_processed boolean column to SourcePage"
```

---

## Task 2: Write Alembic migration for `vision_processed`

**Files:**
- Create: `api/alembic/versions/XXXX_add_vision_processed.py`

The existing migration `2b5582550d39_add_source_pages.py` is the current head. This migration chains from it.

- [ ] **Step 1: Create the migration file**

Create `api/alembic/versions/c1d2e3f4a5b6_add_vision_processed.py`:

```python
"""add_vision_processed

Revision ID: c1d2e3f4a5b6
Revises: 2b5582550d39
Create Date: 2026-04-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = '2b5582550d39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'source_pages',
        sa.Column(
            'vision_processed',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )


def downgrade() -> None:
    op.drop_column('source_pages', 'vision_processed')
```

- [ ] **Step 2: Verify migration runs cleanly**

```bash
cd /app && alembic upgrade head
```

Expected: migration applies with no errors. Existing rows get `vision_processed = false` via `server_default`.

- [ ] **Step 3: Commit**

```bash
git add api/alembic/versions/c1d2e3f4a5b6_add_vision_processed.py
git commit -m "feat: alembic migration — add vision_processed to source_pages"
```

---

## Task 3: Implement `_ensure_vision_captions` helper

**Files:**
- Modify: `api/app/agents/tools.py`
- Modify: `tests/test_agents.py`

This is the core of the feature. The helper:
1. Exits immediately if `page.vision_processed` is `True`.
2. Exits immediately if there are no images or no vision model configured.
3. For each s3_key, downloads the image, calls litellm, and inserts the caption block inline after the matching `![...](filename)` ref in `page.markdown`.
4. The s3_key format is `{workspace_id}/{source_id}/p{page_num}-{original_filename}` — strip the path prefix and `p{N}-` to recover the filename Marker put in the markdown.
5. If no matching image ref is found, appends the caption block at the end.
6. On vision failure, inserts an unavailable block with the s3_key embedded.
7. Sets `page.vision_processed = True`, adds and commits.

- [ ] **Step 1: Write failing tests for `_ensure_vision_captions`**

Add to `tests/test_agents.py`:

```python
@pytest.mark.asyncio
async def test_ensure_vision_captions_skips_if_already_processed():
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.agents.tools import _ensure_vision_captions
    from app.models import SourcePage

    page = MagicMock(spec=SourcePage)
    page.vision_processed = True
    page.image_s3_keys = ["ws/src/p1-img0.png"]

    mock_session = AsyncMock()

    with patch("app.agents.tools.litellm.acompletion", new_callable=AsyncMock) as mock_vision:
        await _ensure_vision_captions(page, mock_session)
        mock_vision.assert_not_called()

    mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_vision_captions_skips_if_no_images():
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.agents.tools import _ensure_vision_captions
    from app.models import SourcePage

    page = MagicMock(spec=SourcePage)
    page.vision_processed = False
    page.image_s3_keys = []

    mock_session = AsyncMock()

    with patch("app.agents.tools.litellm.acompletion", new_callable=AsyncMock) as mock_vision:
        await _ensure_vision_captions(page, mock_session)
        mock_vision.assert_not_called()

    mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_vision_captions_skips_if_no_vision_model():
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.agents.tools import _ensure_vision_captions
    from app.models import SourcePage

    page = MagicMock(spec=SourcePage)
    page.vision_processed = False
    page.image_s3_keys = ["ws/src/p1-img0.png"]

    mock_session = AsyncMock()

    with (
        patch("app.agents.tools.litellm.acompletion", new_callable=AsyncMock) as mock_vision,
        patch("app.agents.tools.settings") as mock_settings,
    ):
        mock_settings.vision_model = ""
        await _ensure_vision_captions(page, mock_session)
        mock_vision.assert_not_called()

    mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_vision_captions_inserts_caption_inline():
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.agents.tools import _ensure_vision_captions
    from app.models import SourcePage

    page = MagicMock(spec=SourcePage)
    page.vision_processed = False
    page.image_s3_keys = ["ws/src/p1-img0.png"]
    page.markdown = "## Results\n\n![Figure 1](img0.png)\n\nSome text."

    mock_session = AsyncMock()

    mock_vision_resp = MagicMock()
    mock_vision_resp.choices[0].message.content = "A bar chart showing quarterly revenue."

    with (
        patch("app.agents.tools.download_file", return_value=b"\x89PNG\r\n"),
        patch("app.agents.tools.settings") as mock_settings,
        patch("app.agents.tools.litellm.acompletion", new_callable=AsyncMock, return_value=mock_vision_resp),
    ):
        mock_settings.vision_model = "gpt-4o-mini"
        await _ensure_vision_captions(page, mock_session)

    assert page.vision_processed is True
    assert "> **[AI-generated caption — gpt-4o-mini]** A bar chart showing quarterly revenue." in page.markdown
    # Caption is inline — appears right after the image ref, not just appended at the end
    img_pos = page.markdown.index("![Figure 1](img0.png)")
    caption_pos = page.markdown.index("> **[AI-generated caption")
    assert caption_pos > img_pos
    assert caption_pos < page.markdown.index("Some text.")
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_vision_captions_inserts_fallback_on_failure():
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.agents.tools import _ensure_vision_captions
    from app.models import SourcePage

    page = MagicMock(spec=SourcePage)
    page.vision_processed = False
    page.image_s3_keys = ["ws/src/p1-img0.png"]
    page.markdown = "## Results\n\n![Figure 1](img0.png)\n\nSome text."

    mock_session = AsyncMock()

    with (
        patch("app.agents.tools.download_file", return_value=b"\x89PNG\r\n"),
        patch("app.agents.tools.settings") as mock_settings,
        patch("app.agents.tools.litellm.acompletion", new_callable=AsyncMock, side_effect=Exception("timeout")),
    ):
        mock_settings.vision_model = "gpt-4o-mini"
        await _ensure_vision_captions(page, mock_session)

    assert page.vision_processed is True
    assert "caption unavailable" in page.markdown
    assert "ws/src/p1-img0.png" in page.markdown
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_vision_captions_appends_orphaned_image():
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.agents.tools import _ensure_vision_captions
    from app.models import SourcePage

    page = MagicMock(spec=SourcePage)
    page.vision_processed = False
    page.image_s3_keys = ["ws/src/p1-img0.png"]
    # Markdown has no image ref for img0.png
    page.markdown = "## Results\n\nNo image tag here."

    mock_session = AsyncMock()

    mock_vision_resp = MagicMock()
    mock_vision_resp.choices[0].message.content = "A diagram."

    with (
        patch("app.agents.tools.download_file", return_value=b"\x89PNG\r\n"),
        patch("app.agents.tools.settings") as mock_settings,
        patch("app.agents.tools.litellm.acompletion", new_callable=AsyncMock, return_value=mock_vision_resp),
    ):
        mock_settings.vision_model = "gpt-4o-mini"
        await _ensure_vision_captions(page, mock_session)

    assert "> **[AI-generated caption — gpt-4o-mini]** A diagram." in page.markdown
    assert page.vision_processed is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /app && pytest tests/test_agents.py -k "ensure_vision" -v
```

Expected: `ImportError: cannot import name '_ensure_vision_captions'`

- [ ] **Step 3: Add `import re` and implement `_ensure_vision_captions` in `tools.py`**

Add `import re` at the top of `api/app/agents/tools.py` (after the existing imports).

Then add this function before the `AgentTools` class definition:

```python
async def _ensure_vision_captions(page: "SourcePage", session: AsyncSession) -> None:
    if page.vision_processed:
        return
    if not page.image_s3_keys or not settings.vision_model:
        return

    markdown = page.markdown

    for s3_key in page.image_s3_keys:
        # Recover the original filename Marker put in the markdown.
        # s3_key format: {workspace_id}/{source_id}/p{page_num}-{original_filename}
        basename = s3_key.rsplit("/", 1)[-1]
        original_filename = re.sub(r"^p\d+-", "", basename)

        try:
            img_bytes = download_file(s3_key)
            b64 = base64.b64encode(img_bytes).decode()
            ext = s3_key.rsplit(".", 1)[-1].lower()
            mime = {
                "png": "image/png",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "webp": "image/webp",
            }.get(ext, "image/png")
            resp = await litellm.acompletion(
                model=settings.vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"Describe this image in the context of the surrounding document text:\n\n{markdown[:500]}",
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{b64}"},
                            },
                        ],
                    }
                ],
            )
            caption = resp.choices[0].message.content or ""
            caption_block = f"\n> **[AI-generated caption — {settings.vision_model}]** {caption}"
        except Exception:
            caption_block = (
                f"\n> **[AI-generated caption — {settings.vision_model}]**"
                f" *(caption unavailable — image: `{s3_key}`)*"
            )

        pattern = re.compile(
            r"(!\[.*?\]\([^)]*" + re.escape(original_filename) + r"[^)]*\))"
        )
        if pattern.search(markdown):
            markdown = pattern.sub(r"\1" + caption_block, markdown, count=1)
        else:
            markdown += caption_block

    page.markdown = markdown
    page.vision_processed = True
    session.add(page)
    await session.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /app && pytest tests/test_agents.py -k "ensure_vision" -v
```

Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/agents/tools.py tests/test_agents.py
git commit -m "feat: add _ensure_vision_captions helper — lazy vision write-back"
```

---

## Task 4: Update `read_source_page` to use `_ensure_vision_captions`

**Files:**
- Modify: `api/app/agents/tools.py:121-168`
- Modify: `tests/test_agents.py`

The existing `test_read_source_page_with_images_calls_vision_model` test must be updated — the old inline vision logic is removed. The new test verifies `_ensure_vision_captions` is called and `page.markdown` is returned directly.

- [ ] **Step 1: Update the existing vision test to match new behaviour**

Replace the existing `test_read_source_page_with_images_calls_vision_model` test in `tests/test_agents.py` with:

```python
@pytest.mark.asyncio
async def test_read_source_page_calls_ensure_vision_captions():
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.agents.tools import AgentTools
    from app.models import SourcePage

    page = MagicMock(spec=SourcePage)
    page.markdown = "## Results\n\n![Figure 1](img0.png)\n\n> **[AI-generated caption — gpt-4o-mini]** A chart."
    page.image_s3_keys = ["ws/src/p1-img0.png"]
    page.vision_processed = True  # already processed — helper is a no-op

    mock_session = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = page
    mock_session.execute = AsyncMock(return_value=scalar_result)

    with patch("app.agents.tools._ensure_vision_captions", new_callable=AsyncMock) as mock_helper:
        tools = AgentTools(
            session=mock_session, workspace_id="ws-1", broadcaster=None, source_id="src-1"
        )
        result = await tools.read_source_page(1)
        mock_helper.assert_awaited_once_with(page, mock_session)

    assert "> **[AI-generated caption" in result
```

- [ ] **Step 2: Run updated test to verify it fails (helper not yet wired in)**

```bash
cd /app && pytest tests/test_agents.py::test_read_source_page_calls_ensure_vision_captions -v
```

Expected: FAIL — helper is not called by the current implementation.

- [ ] **Step 3: Replace the vision block in `read_source_page` with a call to `_ensure_vision_captions`**

Replace the body of `read_source_page` in `api/app/agents/tools.py`:

```python
async def read_source_page(self, page_num: int) -> str:
    result = await self.session.execute(
        select(SourcePage).where(
            SourcePage.source_id == self.source_id,
            SourcePage.page_num == page_num,
        )
    )
    page = result.scalar_one_or_none()
    if not page:
        return f"[Page {page_num} not found]"

    await _ensure_vision_captions(page, self.session)
    return page.markdown
```

- [ ] **Step 4: Run the full agent test suite**

```bash
cd /app && pytest tests/test_agents.py -v
```

Expected: all tests PASS. Pay attention to `test_read_source_page_no_images_returns_markdown` — it uses a page with `image_s3_keys = []`, so `_ensure_vision_captions` will early-exit and the test remains valid. Update that mock to add `vision_processed = False` if the spec mock raises `AttributeError`.

- [ ] **Step 5: Commit**

```bash
git add api/app/agents/tools.py tests/test_agents.py
git commit -m "feat: read_source_page delegates vision to _ensure_vision_captions"
```

---

## Task 5: Add `describe_image` tool

**Files:**
- Modify: `api/app/agents/tools.py`
- Modify: `tests/test_agents.py`

`describe_image(s3_key)` is a pure describe operation — downloads image, calls litellm, returns caption string. No DB writes. Registered in `as_litellm_tools` and `dispatch`.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_agents.py`:

```python
@pytest.mark.asyncio
async def test_describe_image_returns_caption():
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.agents.tools import AgentTools

    mock_vision_resp = MagicMock()
    mock_vision_resp.choices[0].message.content = "A scatter plot of user retention."

    with (
        patch("app.agents.tools.download_file", return_value=b"\x89PNG\r\n"),
        patch("app.agents.tools.settings") as mock_settings,
        patch("app.agents.tools.litellm.acompletion", new_callable=AsyncMock, return_value=mock_vision_resp),
    ):
        mock_settings.vision_model = "gpt-4o-mini"
        tools = AgentTools(session=AsyncMock(), workspace_id="ws-1", broadcaster=None)
        result = await tools.describe_image("ws/src/p2-chart.png")

    assert result == "A scatter plot of user retention."


@pytest.mark.asyncio
async def test_describe_image_returns_error_on_failure():
    from unittest.mock import AsyncMock, patch
    from app.agents.tools import AgentTools

    with (
        patch("app.agents.tools.download_file", side_effect=Exception("S3 error")),
        patch("app.agents.tools.settings") as mock_settings,
    ):
        mock_settings.vision_model = "gpt-4o-mini"
        tools = AgentTools(session=AsyncMock(), workspace_id="ws-1", broadcaster=None)
        result = await tools.describe_image("ws/src/p2-chart.png")

    assert "error" in result.lower()


@pytest.mark.asyncio
async def test_describe_image_does_not_write_to_db():
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.agents.tools import AgentTools

    mock_session = AsyncMock()
    mock_vision_resp = MagicMock()
    mock_vision_resp.choices[0].message.content = "A pie chart."

    with (
        patch("app.agents.tools.download_file", return_value=b"\x89PNG\r\n"),
        patch("app.agents.tools.settings") as mock_settings,
        patch("app.agents.tools.litellm.acompletion", new_callable=AsyncMock, return_value=mock_vision_resp),
    ):
        mock_settings.vision_model = "gpt-4o-mini"
        tools = AgentTools(session=mock_session, workspace_id="ws-1", broadcaster=None)
        await tools.describe_image("ws/src/p1-img0.png")

    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_describe_image():
    from unittest.mock import AsyncMock
    from app.agents.tools import AgentTools

    tools = AgentTools(session=AsyncMock(), workspace_id="ws-1", broadcaster=None)
    tools.describe_image = AsyncMock(return_value="A chart.")

    result = await tools.dispatch("describe_image", {"s3_key": "ws/src/p1-img0.png"})

    tools.describe_image.assert_awaited_once_with("ws/src/p1-img0.png")
    assert result == "A chart."


def test_describe_image_in_tool_schema():
    from app.agents.tools import AgentTools
    tools = AgentTools(session=None, workspace_id="ws-1", broadcaster=None)
    names = [t["function"]["name"] for t in tools.as_litellm_tools()]
    assert "describe_image" in names
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /app && pytest tests/test_agents.py -k "describe_image" -v
```

Expected: `AttributeError: 'AgentTools' object has no attribute 'describe_image'`

- [ ] **Step 3: Add `describe_image` method to `AgentTools`**

Add this method to the `AgentTools` class in `api/app/agents/tools.py`, after `read_source_page`:

```python
async def describe_image(self, s3_key: str) -> str:
    try:
        img_bytes = download_file(s3_key)
        b64 = base64.b64encode(img_bytes).decode()
        ext = s3_key.rsplit(".", 1)[-1].lower()
        mime = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
        }.get(ext, "image/png")
        resp = await litellm.acompletion(
            model=settings.vision_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                        {
                            "type": "text",
                            "text": "Describe this image in detail.",
                        },
                    ],
                }
            ],
        )
        return resp.choices[0].message.content or ""
    except Exception as exc:
        return f"[describe_image error: {exc}]"
```

- [ ] **Step 4: Register `describe_image` in `as_litellm_tools`**

In the `as_litellm_tools` method, append this entry to `all_tools` before the `if allowed:` line:

```python
{
    "type": "function",
    "function": {
        "name": "describe_image",
        "description": (
            "Describe a specific image from the source document by its S3 key. "
            "Use this when a page shows '(caption unavailable — image: `<key>`)' "
            "to get a fresh vision description of that image."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "s3_key": {
                    "type": "string",
                    "description": "The S3 key of the image, as shown in the caption unavailable notice.",
                }
            },
            "required": ["s3_key"],
        },
    },
},
```

- [ ] **Step 5: Register `describe_image` in `dispatch`**

In the `dispatch` method, add before the final `return f"Unknown tool: {name}"` line:

```python
if name == "describe_image":
    return await self.describe_image(args["s3_key"])
```

- [ ] **Step 6: Run the full test suite**

```bash
cd /app && pytest tests/test_agents.py -v
```

Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add api/app/agents/tools.py tests/test_agents.py
git commit -m "feat: add describe_image agent tool — on-demand vision, no DB writes"
```

---

## Self-Review

**Spec coverage:**
- `vision_processed` column + migration → Task 1 + Task 2 ✓
- `_ensure_vision_captions` helper (early exits, inline insertion, failure fallback, orphaned key, commit) → Task 3 ✓
- `read_source_page` delegates to helper → Task 4 ✓
- Caption format with model name → Task 3 Step 3 ✓
- Failure format with embedded s3_key → Task 3 Step 3 ✓
- `describe_image` tool (no DB writes, error string, dispatch, schema) → Task 5 ✓

**Type consistency:**
- `_ensure_vision_captions(page, session)` defined in Task 3, called with `(page, self.session)` in Task 4 ✓
- `describe_image(s3_key: str) -> str` defined and dispatched with `args["s3_key"]` ✓
- `page.vision_processed` set as `bool` in Task 1, read as bool in Task 3 ✓

**No placeholders:** all steps contain complete code.
