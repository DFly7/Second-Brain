from dataclasses import dataclass, field

import httpx

from app.config import settings


@dataclass
class ImageData:
    filename: str
    b64: str


@dataclass
class PageData:
    page_num: int
    markdown: str
    images: list[ImageData] = field(default_factory=list)


class MarkerClient:
    def __init__(
        self,
        base_url: str = "",
        use_llm: bool = False,
        llm_service: str = "",
        llm_model: str = "",
        llm_api_key: str = "",
    ):
        self.base_url = base_url or settings.marker_url
        self.use_llm = use_llm
        self.llm_service = llm_service or settings.marker_llm_service
        self.llm_model = llm_model or settings.marker_llm_model
        self.llm_api_key = llm_api_key or settings.marker_llm_api_key

    async def convert(self, data: bytes, filename: str) -> list[PageData]:
        form = {
            "use_llm": str(self.use_llm).lower(),
            "llm_service": self.llm_service,
            "llm_model": self.llm_model,
            "llm_api_key": self.llm_api_key,
        }
        files = {"file": (filename, data, "application/octet-stream")}
        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(f"{self.base_url}/convert", data=form, files=files)
            resp.raise_for_status()

        raw_pages = resp.json()
        return [
            PageData(
                page_num=p["page_num"],
                markdown=p["markdown"],
                images=[ImageData(**img) for img in p.get("images", [])],
            )
            for p in raw_pages
        ]
