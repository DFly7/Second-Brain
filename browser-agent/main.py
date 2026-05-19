import base64
import json
import os
import tempfile
import uuid
from contextlib import asynccontextmanager

import boto3
from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from playwright.async_api import async_playwright
from playwright._impl._errors import TimeoutError as PlaywrightTimeoutError
from playwright_stealth import stealth_async
from pydantic import BaseModel

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

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


@app.exception_handler(PlaywrightTimeoutError)
async def playwright_timeout_handler(request: Request, exc: PlaywrightTimeoutError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


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


_CHROMIUM_PATH = os.getenv("CHROMIUM_EXECUTABLE_PATH")

_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--exclude-switches=enable-automation",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
    "--password-store=basic",
    "--disable-component-update",
    "--disable-dev-shm-usage",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--lang=en-GB",
]

# Injected on every page — renders a red dot that follows Playwright mouse events
# so the cursor is visible in the VNC/noVNC live view.
_CURSOR_SCRIPT = """(() => {
    const inject = () => {
        if (document.getElementById('__pw_cursor__')) return;
        const c = document.createElement('div');
        c.id = '__pw_cursor__';
        c.style.cssText = [
            'position:fixed',
            'width:14px',
            'height:14px',
            'border-radius:50%',
            'background:rgba(220,40,40,0.8)',
            'border:2px solid rgba(255,255,255,0.9)',
            'box-shadow:0 1px 4px rgba(0,0,0,0.45)',
            'pointer-events:none',
            'z-index:2147483647',
            'transform:translate(-50%,-50%)',
            'transition:none',
            'left:-100px',
            'top:-100px',
        ].join(';');
        document.documentElement.appendChild(c);
        document.addEventListener('mousemove', e => {
            c.style.left = e.clientX + 'px';
            c.style.top = e.clientY + 'px';
        }, {passive: true});
    };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', inject);
    } else {
        inject();
    }
})();"""


async def _new_page(browser, video_dir: str):
    """Create a stealth context + page with cursor injection."""
    context = await browser.new_context(
        record_video_dir=video_dir,
        viewport={"width": 1280, "height": 800},
        user_agent=_UA,
        locale="en-GB",
        timezone_id="Europe/London",
        color_scheme="light",
        extra_http_headers={"Accept-Language": "en-GB,en;q=0.9"},
    )
    page = await context.new_page()
    await stealth_async(page)
    await page.add_init_script(_CURSOR_SCRIPT)
    return context, page


@app.post("/session/new")
async def session_new():
    session_id = str(uuid.uuid4())
    video_dir = tempfile.mkdtemp()
    launch_kwargs = {
        "headless": False,
        "args": _LAUNCH_ARGS,
    }
    if _CHROMIUM_PATH:
        launch_kwargs["executable_path"] = _CHROMIUM_PATH
    browser = await _playwright.chromium.launch(**launch_kwargs)
    context, page = await _new_page(browser, video_dir)
    _sessions[session_id] = {
        "browser": browser,
        "context": context,
        "page": page,
        "video_dir": video_dir,
    }
    return {"session_id": session_id}


@app.post("/session/{session_id}/recover")
async def session_recover(session_id: str):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    s = _sessions[session_id]

    # Best-effort teardown of dead objects.
    for obj in (s.get("browser"), s.get("context")):
        if obj is not None:
            try:
                await obj.close()
            except Exception:
                pass

    video_dir = s.get("video_dir") or tempfile.mkdtemp()
    launch_kwargs = {"headless": False, "args": _LAUNCH_ARGS}
    if _CHROMIUM_PATH:
        launch_kwargs["executable_path"] = _CHROMIUM_PATH
    browser = await _playwright.chromium.launch(**launch_kwargs)
    context, page = await _new_page(browser, video_dir)

    _sessions[session_id] = {
        "browser": browser,
        "context": context,
        "page": page,
        "video_dir": video_dir,
    }
    return {"ok": True}


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
    text: str | None = None
    x: float | None = None
    y: float | None = None


@app.post("/session/{session_id}/click")
async def session_click(session_id: str, body: ClickRequest):
    s = _get_session(session_id)
    if body.selector:
        await s["page"].click(body.selector, timeout=10000)
    elif body.text:
        await s["page"].get_by_text(body.text, exact=False).first.click(timeout=10000)
    elif body.x is not None and body.y is not None:
        await s["page"].mouse.click(body.x, body.y, delay=150)
    else:
        raise HTTPException(status_code=400, detail="Provide selector, text, or x,y coordinates")
    return {"ok": True}


class MouseMoveRequest(BaseModel):
    x: float
    y: float


@app.post("/session/{session_id}/mouse_move")
async def session_mouse_move(session_id: str, body: MouseMoveRequest):
    s = _get_session(session_id)
    await s["page"].mouse.move(body.x, body.y)
    return {"ok": True}


@app.post("/session/{session_id}/click_cloudflare")
async def session_click_cloudflare(session_id: str):
    """Click the Cloudflare Turnstile checkbox via iframe frame access — no coordinate guessing."""
    s = _get_session(session_id)
    page = s["page"]
    for frame in page.frames:
        url = frame.url or ""
        if "challenges.cloudflare.com" in url or "turnstile" in url:
            try:
                await frame.click("input[type=checkbox]", timeout=5000)
                return {"ok": True, "method": "checkbox"}
            except Exception:
                pass
            try:
                await frame.click("label", timeout=5000)
                return {"ok": True, "method": "label"}
            except Exception:
                pass
    # Fallback: try clicking the iframe element itself from the main frame
    try:
        iframe_el = await page.query_selector("iframe[src*='cloudflare'], iframe[src*='turnstile']")
        if iframe_el:
            box = await iframe_el.bounding_box()
            if box:
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                await page.mouse.move(cx, cy)
                await page.mouse.click(cx, cy, delay=150)
                return {"ok": True, "method": "iframe_center", "x": cx, "y": cy}
    except Exception:
        pass
    return {"ok": False, "error": "Cloudflare iframe not found — try browser_click_at with coordinates from screenshot"}


class TypeRequest(BaseModel):
    text: str


@app.post("/session/{session_id}/type")
async def session_type(session_id: str, body: TypeRequest):
    s = _get_session(session_id)
    await s["page"].keyboard.type(body.text)
    return {"ok": True}


class PressKeyRequest(BaseModel):
    key: str


@app.post("/session/{session_id}/press_key")
async def session_press_key(session_id: str, body: PressKeyRequest):
    s = _get_session(session_id)
    await s["page"].keyboard.press(body.key)
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


class HoverRequest(BaseModel):
    selector: str


@app.post("/session/{session_id}/hover")
async def session_hover(session_id: str, body: HoverRequest):
    s = _get_session(session_id)
    await s["page"].hover(body.selector, timeout=10000)
    return {"ok": True}


class SelectOptionRequest(BaseModel):
    selector: str
    value: str


@app.post("/session/{session_id}/select_option")
async def session_select_option(session_id: str, body: SelectOptionRequest):
    s = _get_session(session_id)
    selected = await s["page"].select_option(body.selector, body.value)
    return {"selected": selected}


class FocusRequest(BaseModel):
    selector: str


@app.post("/session/{session_id}/focus")
async def session_focus(session_id: str, body: FocusRequest):
    s = _get_session(session_id)
    await s["page"].focus(body.selector, timeout=10000)
    return {"ok": True}


class WaitForRequest(BaseModel):
    selector: str | None = None
    text: str | None = None
    timeout: int = 10000


@app.post("/session/{session_id}/wait_for")
async def session_wait_for(session_id: str, body: WaitForRequest):
    s = _get_session(session_id)
    if not body.selector and not body.text:
        raise HTTPException(status_code=400, detail="Provide selector or text")
    try:
        if body.selector:
            await s["page"].wait_for_selector(body.selector, timeout=body.timeout)
        else:
            await s["page"].wait_for_function(
                f"() => document.body.innerText.includes({json.dumps(body.text)})",
                timeout=body.timeout,
            )
        return {"found": True}
    except PlaywrightTimeoutError:
        return {"found": False, "error": f"Timeout after {body.timeout}ms — not found"}


class ExecuteJsRequest(BaseModel):
    script: str


@app.post("/session/{session_id}/execute_js")
async def session_execute_js(session_id: str, body: ExecuteJsRequest):
    s = _get_session(session_id)
    result = await s["page"].evaluate(body.script)
    return {"result": result}


_GET_ELEMENTS_JS = """() => {
    function getSelector(el) {
        if (el.id) return '#' + CSS.escape(el.id);
        const name = el.getAttribute('name');
        if (name) return el.tagName.toLowerCase() + '[name="' + name + '"]';
        let path = [], node = el;
        while (node && node.nodeType === 1 && path.length < 4) {
            let sel = node.tagName.toLowerCase();
            let sib = node, nth = 1;
            while ((sib = sib.previousElementSibling)) {
                if (sib.tagName === node.tagName) nth++;
            }
            if (nth > 1) sel += ':nth-of-type(' + nth + ')';
            path.unshift(sel);
            node = node.parentElement;
        }
        return path.join(' > ');
    }
    const seen = new Set();
    const els = [];
    const query = 'a[href], button, input, select, textarea, [role="button"], [role="link"], [role="checkbox"], [role="radio"], [role="menuitem"]';
    document.querySelectorAll(query).forEach(el => {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        const text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim().slice(0, 80);
        const sel = getSelector(el);
        if (seen.has(sel)) return;
        seen.add(sel);
        els.push({
            tag: el.tagName.toLowerCase(),
            type: el.getAttribute('type') || null,
            text,
            selector: sel,
            href: el.tagName === 'A' ? el.getAttribute('href') : null,
            x: Math.round(rect.left + rect.width / 2),
            y: Math.round(rect.top + rect.height / 2),
        });
    });
    return els.slice(0, 60);
}"""


@app.post("/session/{session_id}/get_page_state")
async def session_get_page_state(session_id: str):
    s = _get_session(session_id)
    page = s["page"]
    url = page.url
    title = await page.title()
    elements = await page.evaluate(_GET_ELEMENTS_JS)
    return {"url": url, "title": title, "interactive_elements": elements}


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
