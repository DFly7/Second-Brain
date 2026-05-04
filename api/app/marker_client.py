import asyncio
import re
import time
from dataclasses import dataclass, field

import httpx
import structlog

from app.config import settings

_log = structlog.get_logger()

DATALAB_CONVERT_URL = "https://www.datalab.to/api/v1/convert"
_PAGE_SEP = re.compile(r"\n\n\d+\n-{48}\n\n")
_IMG_REF = re.compile(r"!\[.*?\]\(([^)]+)\)")

_DATALAB_SUBMIT_TIMEOUT = httpx.Timeout(connect=30.0, read=60.0, write=120.0, pool=30.0)
_DATALAB_POLL_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
_LOCAL_HTTP_TIMEOUT = httpx.Timeout(connect=60.0, read=7200.0, write=600.0, pool=60.0)

_CONNECT_RETRIES = 5
_CONNECT_BACKOFF_BASE = 15.0
_CONNECT_BACKOFF_MAX = 120.0
POLL_INTERVAL = 5.0
MAX_WAIT = 7200.0


@dataclass
class ImageData:
    filename: str
    b64: str


@dataclass
class PageData:
    page_num: int
    markdown: str
    images: list[ImageData] = field(default_factory=list)


def _parse_paginated_markdown(full_markdown: str, b64_images: dict) -> list[PageData]:
    raw_pages = _PAGE_SEP.split(full_markdown)
    pages = []
    for i, page_md in enumerate(raw_pages):
        page_md = page_md.strip()
        if not page_md:
            continue
        refs = _IMG_REF.findall(page_md)
        page_images = [
            ImageData(filename=ref, b64=b64_images[ref])
            for ref in refs
            if ref in b64_images
        ]
        pages.append(PageData(page_num=i + 1, markdown=page_md, images=page_images))
    return pages


class DatalabMarkerClient:
    def __init__(self, api_key: str = "", mode: str = ""):
        self.api_key = api_key or settings.datalab_api_key
        self.mode = mode or settings.datalab_mode

    async def convert(self, data: bytes, filename: str, *, source_id: str = "") -> list[PageData]:
        headers = {"X-API-Key": self.api_key}
        MIME_TYPES = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "doc": "application/msword",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "html": "text/html",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "tiff": "image/tiff",
            "webp": "image/webp",
        }
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        mime = MIME_TYPES.get(ext, "application/octet-stream")
        files = {"file": (filename, data, mime)}
        form = {"output_format": "markdown", "paginate": "true", "mode": self.mode}

        async with httpx.AsyncClient(timeout=_DATALAB_SUBMIT_TIMEOUT) as client:
            resp = await client.post(
                DATALAB_CONVERT_URL, headers=headers, files=files, data=form
            )
            if resp.status_code >= 400:
                _log.error("datalab_api_error", status=resp.status_code, body=resp.text)
            resp.raise_for_status()
            submission = resp.json()

        if not submission.get("success"):
            raise RuntimeError(f"Datalab submission failed: {submission}")

        check_url = submission["request_check_url"]
        _log.info(
            "datalab_submission",
            source_id=source_id or "-",
            request_id=submission["request_id"],
        )

        deadline = time.monotonic() + MAX_WAIT
        async with httpx.AsyncClient(timeout=_DATALAB_POLL_TIMEOUT) as client:
            while time.monotonic() < deadline:
                await asyncio.sleep(POLL_INTERVAL)
                resp = await client.get(check_url, headers=headers)
                resp.raise_for_status()
                result = resp.json()
                if result["status"] == "complete":
                    break
                if result["status"] == "failed":
                    raise RuntimeError(
                        f"Datalab conversion failed: {result.get('error')}"
                    )
            else:
                raise TimeoutError(
                    f"Datalab conversion timed out after {MAX_WAIT}s source_id={source_id or '-'}"
                )

        _log.info(
            "datalab_conversion_complete",
            source_id=source_id or "-",
            request_id=submission["request_id"],
        )
        return _parse_paginated_markdown(
            result.get("markdown", ""), result.get("images") or {}
        )


class LocalMarkerClient:
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

    async def convert(self, data: bytes, filename: str, *, source_id: str = "") -> list[PageData]:
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
            "local_marker_post",
            url=url,
            source_id=source_id or "-",
            filename=filename,
            bytes=len(data),
        )

        resp = None
        for attempt in range(_CONNECT_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=_LOCAL_HTTP_TIMEOUT) as client:
                    resp = await client.post(url, data=form, files=files)
                    resp.raise_for_status()
                break
            except (httpx.ConnectError, httpx.RemoteProtocolError) as e:
                if attempt >= _CONNECT_RETRIES:
                    raise
                wait = min(_CONNECT_BACKOFF_BASE * (2**attempt), _CONNECT_BACKOFF_MAX)
                _log.warning(
                    "marker_connect_retry",
                    source_id=source_id or "-",
                    attempt=attempt + 1,
                    max=_CONNECT_RETRIES,
                    error=str(e),
                )
                await asyncio.sleep(wait)

        raw_pages = resp.json()
        _log.info(
            "local_marker_response",
            source_id=source_id or "-",
            pages=len(raw_pages),
        )
        return [
            PageData(
                page_num=p["page_num"],
                markdown=p["markdown"],
                images=[ImageData(**img) for img in p.get("images", [])],
            )
            for p in raw_pages
        ]


def make_client() -> DatalabMarkerClient | LocalMarkerClient:
    if settings.marker_backend == "local":
        return LocalMarkerClient()
    return DatalabMarkerClient()
