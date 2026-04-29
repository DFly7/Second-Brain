# Vision Caption Cache — Design

**Goal:** Run vision once per image, bake the caption inline into `SourcePage.markdown`, and never call the vision model again for that page. Add a `describe_image` tool so the agent can manually retry failed captions.

---

## Data Model

Add one column to `SourcePage`:

```python
vision_processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
```

- `image_s3_keys` remains the authoritative list of images for a page.
- `markdown` becomes the destination — captions are baked in once.
- `vision_processed = True` is the permanent signal to skip vision on all future reads.

One Alembic migration required.

---

## Caption Format

Captions are inserted **inline**, immediately after the matching image reference in markdown:

```markdown
![Figure 1](images/page3_img0.png)
> **[AI-generated caption — gpt-4o-mini]** This bar chart shows quarterly revenue
> broken down by region for FY2024, with EMEA leading at 42%.
```

The vision model name is interpolated from `settings.vision_model` at generation time.

**Failure format** (vision call throws for a specific image):

```markdown
![Figure 1](images/page3_img0.png)
> **[AI-generated caption — gpt-4o-mini]** *(caption unavailable — image: `images/page3_img0.png`)*
```

The s3_key is embedded so the agent can pass it directly to `describe_image`.

If an image s3_key has no matching `![...](s3_key)` ref in markdown (orphaned), the caption is appended at the end of the page as a fallback.

---

## Code Flow

### `_ensure_vision_captions(page: SourcePage, session: AsyncSession) -> None`

New private async helper in `api/app/agents/tools.py`.

1. If `page.vision_processed` → return immediately.
2. If `not page.image_s3_keys` or `not settings.vision_model` → return immediately.
3. For each `s3_key` in `page.image_s3_keys`:
   - Download image bytes from S3 via `download_file(s3_key)`.
   - Call `litellm.acompletion` with vision model + base64 image.
   - On success: insert caption block after matching `![...](s3_key)` in `page.markdown`.
   - On failure: insert failure block with embedded s3_key; continue to next image.
4. Set `page.vision_processed = True`.
5. `session.add(page)` → `await session.commit()`.

All images are attempted regardless of individual failures. `vision_processed` is set after all attempts.

### `read_source_page(page_num: int) -> str`

Updated in `api/app/agents/tools.py`:

1. Load `SourcePage` from DB (unchanged).
2. Call `await _ensure_vision_captions(page, self.session)`.
3. Return `page.markdown` — always fully described after step 2.

The agent's interface is unchanged. One tool, always returns complete markdown.

### `describe_image(s3_key: str) -> str`

New agent tool in `api/app/agents/tools.py`:

- Downloads image from S3, calls `litellm.acompletion` with `settings.vision_model`.
- Returns the raw caption string on success, or a clear error message on failure.
- **No DB writes.** Does not touch `page.markdown` or `vision_processed`.
- Added to `as_litellm_tools` and `dispatch`.

**Agent use pattern:** agent reads a page, sees `*(caption unavailable — image: \`images/page3_img0.png\`)*`, calls `describe_image("images/page3_img0.png")`, incorporates the result into its wiki notes or reasoning.

---

## Error Handling

| Failure | Behaviour |
|---|---|
| Vision call fails for one image | Insert failure block with s3_key; continue; set `vision_processed = True` after all attempts |
| Commit fails after vision runs | `vision_processed` stays `False`; vision re-runs on next read (idempotent, acceptable) |
| S3 download fails | Exception propagates to agent as today |
| `describe_image` vision fails | Return error string to agent; no DB side-effects |

---

## Files Changed

| Action | File | Change |
|---|---|---|
| Modify | `api/app/models.py` | Add `vision_processed: Mapped[bool]` to `SourcePage` |
| Create | `api/alembic/versions/XXXX_add_vision_processed.py` | Migration: add column, `server_default='false'` |
| Modify | `api/app/agents/tools.py` | Add `_ensure_vision_captions`, update `read_source_page`, add `describe_image` tool |

---

## Out of Scope

- Eager (pre-agent) vision generation — lazy on first read is sufficient.
- Auto-patching markdown from `describe_image` — agent decides what to do with output.
- Re-running vision on already-processed pages — `vision_processed` is permanent.
