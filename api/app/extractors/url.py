import httpx
import trafilatura


async def extract_main_content(url: str) -> str:
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    text = trafilatura.extract(resp.text, include_comments=False, include_tables=True)
    return text or resp.text[:8000]
