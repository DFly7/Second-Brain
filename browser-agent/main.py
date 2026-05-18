import base64
import os
import tempfile
import uuid
from contextlib import asynccontextmanager

import boto3
from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException
from playwright.async_api import async_playwright
from pydantic import BaseModel

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
S3_BUCKET = os.getenv("S3_BUCKET", "wiki")

_playwright = None
_sessions: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _playwright
    _playwright = await async_playwright().start()
    yield
    for s in list(_sessions.values()):
        try:
            await s["browser"].close()
        except Exception:
            pass
    await _playwright.stop()


app = FastAPI(title="Browser Agent", lifespan=lifespan)


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name="us-east-1",
    )


def _ensure_bucket():
    s3 = _s3_client()
    try:
        s3.head_bucket(Bucket=S3_BUCKET)
    except ClientError:
        s3.create_bucket(Bucket=S3_BUCKET)


def _get_session(session_id: str) -> dict:
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return _sessions[session_id]


@app.get("/health")
async def health():
    return {"status": "ok"}


_CHROMIUM_PATH = os.getenv("CHROMIUM_EXECUTABLE_PATH")  # set on ARM64/Pi via env


@app.post("/session/new")
async def session_new():
    session_id = str(uuid.uuid4())
    video_dir = tempfile.mkdtemp()
    launch_kwargs = {"headless": False}
    if _CHROMIUM_PATH:
        launch_kwargs["executable_path"] = _CHROMIUM_PATH
    browser = await _playwright.chromium.launch(**launch_kwargs)
    context = await browser.new_context(
        record_video_dir=video_dir,
        viewport={"width": 1280, "height": 800},
    )
    page = await context.new_page()
    _sessions[session_id] = {
        "browser": browser,
        "context": context,
        "page": page,
        "video_dir": video_dir,
    }
    return {"session_id": session_id}


class NavigateRequest(BaseModel):
    url: str


@app.post("/session/{session_id}/navigate")
async def session_navigate(session_id: str, body: NavigateRequest):
    s = _get_session(session_id)
    await s["page"].goto(body.url, wait_until="domcontentloaded")
    title = await s["page"].title()
    return {"title": title, "url": s["page"].url}


class ClickRequest(BaseModel):
    selector: str | None = None
    x: float | None = None
    y: float | None = None


@app.post("/session/{session_id}/click")
async def session_click(session_id: str, body: ClickRequest):
    s = _get_session(session_id)
    if body.selector:
        await s["page"].click(body.selector)
    elif body.x is not None and body.y is not None:
        await s["page"].mouse.click(body.x, body.y)
    else:
        raise HTTPException(status_code=400, detail="Provide selector or x,y coordinates")
    return {"ok": True}


class TypeRequest(BaseModel):
    text: str


@app.post("/session/{session_id}/type")
async def session_type(session_id: str, body: TypeRequest):
    s = _get_session(session_id)
    await s["page"].keyboard.type(body.text)
    return {"ok": True}


class ScrollRequest(BaseModel):
    direction: str = "down"
    amount: int = 300


@app.post("/session/{session_id}/scroll")
async def session_scroll(session_id: str, body: ScrollRequest):
    s = _get_session(session_id)
    delta = body.amount if body.direction == "down" else -body.amount
    await s["page"].mouse.wheel(0, delta)
    return {"ok": True}


@app.post("/session/{session_id}/extract")
async def session_extract(session_id: str):
    s = _get_session(session_id)
    text = await s["page"].inner_text("body")
    return {"text": text[:20000]}


@app.post("/session/{session_id}/screenshot")
async def session_screenshot(session_id: str):
    s = _get_session(session_id)
    png = await s["page"].screenshot(full_page=False)
    return {"image_b64": base64.b64encode(png).decode()}


@app.post("/session/{session_id}/close")
async def session_close(session_id: str):
    s = _get_session(session_id)
    page = s["page"]
    context = s["context"]
    browser = s["browser"]

    await context.close()
    video_path = await page.video.path()
    await browser.close()

    recording_url = None
    try:
        _ensure_bucket()
        key = f"automation-recordings/{session_id}.webm"
        with open(video_path, "rb") as f:
            _s3_client().put_object(
                Bucket=S3_BUCKET,
                Key=key,
                Body=f.read(),
                ContentType="video/webm",
            )
        recording_url = key
    except Exception:
        pass

    del _sessions[session_id]
    return {"recording_url": recording_url}
