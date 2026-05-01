import logging
from dataclasses import dataclass, field

import httpx

from app.config import settings

_log = logging.getLogger(__name__)


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

    async def convert(
        self,
        data: bytes,
        filename: str,
        *,
        source_id: str = "",
    ) -> list[PageData]:
        form = {
            "use_llm": str(self.use_llm).lower(),
            "llm_service": self.llm_service,
            "llm_model": self.llm_model,
            "llm_api_key": self.llm_api_key,
            "source_id": source_id,
        }
        files = {"file": (filename, data, "application/octet-stream")}
        url = f"{self.base_url}/convert"
        _log.info(
            "marker HTTP POST %s source_id=%s filename=%s bytes=%d use_llm=%s",
            url,
            source_id or "-",
            filename,
            len(data),
            self.use_llm,
        )
        async with httpx.AsyncClient(timeout=600.0) as client:
            try:
                resp = await client.post(url, data=form, files=files)
            except httpx.RemoteProtocolError as e:
                _log.error(
                    "marker closed connection without a response (often OOM kill or crash in "
                    "marker container; check `docker compose logs marker` and Docker memory). "
                    "source_id=%s err=%s",
                    source_id or "-",
                    e,
                )
                raise
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                _log.error(
                    "marker HTTP %s body=%s",
                    resp.status_code,
                    (resp.text[:500] + "…") if len(resp.text) > 500 else resp.text,
                )
                raise

        raw_pages = resp.json()
        _log.info(
            "marker response OK source_id=%s pages=%d",
            source_id or "-",
            len(raw_pages),
        )
        return [
            PageData(
                page_num=p["page_num"],
                markdown=p["markdown"],
                images=[ImageData(**img) for img in p.get("images", [])],
            )
            for p in raw_pages
        ]
