import pytest
from app.extractors.url import extract_main_content


@pytest.mark.asyncio
async def test_extract_url_returns_text():
    # Use a stable, simple URL
    text = await extract_main_content("https://example.com")
    assert isinstance(text, str)
    assert len(text) > 10
