import os

# Surya Settings() reads this when imported; must be set before Marker/surya load.
os.environ.setdefault("PARALLEL_DOWNLOAD_WORKERS", "1")

import base64
import io
import logging
import re
import shutil
import tempfile
import time
from pathlib import Path

_log = logging.getLogger(__name__)
if not _log.handlers:
    _stderr = logging.StreamHandler()
    _stderr.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    _log.addHandler(_stderr)
    _log.setLevel(logging.INFO)
    _log.propagate = False

import surya.common.s3 as surya_s3

_orig_download_directory = surya_s3.download_directory


def _download_directory(remote_path: str, local_dir: str) -> None:
    """Serialize datalab checkpoint downloads. flock(F_SETLK) is flaky on virtiofs-backed
    Docker Desktop volumes — use atomic posix O_CREAT|O_EXCL for mutual exclusion."""

    lock_root = Path(
        os.environ.get(
            "SURYA_MODEL_DOWNLOAD_EXCLUSIVE_ROOT",
            "/root/.cache/datalab/surya_download_exclusive",
        )
    )
    lock_root.mkdir(parents=True, exist_ok=True)
    safe_remote = "".join(c if c.isalnum() or c in "._-" else "_" for c in remote_path)
    lock_path = lock_root / f"{safe_remote}.lock"
    stale_after = float(
        os.environ.get("SURYA_DOWNLOAD_STALE_LOCK_SECONDS", str(7200))
    )
    poll_s = float(os.environ.get("SURYA_DOWNLOAD_LOCK_POLL_SECONDS", "0.35"))

    while True:
        if surya_s3.check_manifest(local_dir):
            return

        try:
            fd = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o644,
            )
        except FileExistsError:
            other_stale_removed = False
            if stale_after > 0 and lock_path.exists():
                try:
                    if time.time() - lock_path.stat().st_mtime > stale_after:
                        lock_path.unlink(missing_ok=True)
                        other_stale_removed = True
                except OSError:
                    pass
            if not other_stale_removed:
                if surya_s3.check_manifest(local_dir):
                    return
                time.sleep(poll_s)
            continue

        try:
            if surya_s3.check_manifest(local_dir):
                return
            local = Path(local_dir)
            if local.exists() and not surya_s3.check_manifest(local_dir):
                _log.warning("Clearing incomplete download at %s", local_dir)
                if local.is_file():
                    local.unlink()
                else:
                    shutil.rmtree(local, ignore_errors=True)
            return _orig_download_directory(remote_path, local_dir)
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(lock_path)
            except OSError:
                pass


surya_s3.download_directory = _download_directory

from fastapi import FastAPI, File, Form, UploadFile
from marker.config.parser import ConfigParser
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered
from PIL import Image

app = FastAPI(title="Marker Service")

_models = create_model_dict()

_PAGE_SEP = re.compile(r"\n\n\d+\n-{48}\n\n")
_IMG_REF = re.compile(r"!\[.*?\]\(([^)]+)\)")


def _pil_to_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/convert")
async def convert(
    file: UploadFile = File(...),
    use_llm: bool = Form(False),
    llm_service: str = Form("marker.services.gemini.GoogleGeminiService"),
    llm_model: str = Form(""),
    llm_api_key: str = Form(""),
    source_id: str = Form(""),
):
    data = await file.read()
    suffix = Path(file.filename or "file.pdf").suffix or ".pdf"
    sid = source_id.strip() or "-"
    _log.info(
        "convert start source_id=%s filename=%s suffix=%s bytes=%d use_llm=%s",
        sid,
        file.filename,
        suffix,
        len(data),
        use_llm,
    )

    try:
        config: dict = {"output_format": "markdown", "paginate_output": True}
        if use_llm:
            config["use_llm"] = True
            config["llm_service"] = llm_service
            if llm_model:
                config["llm_model"] = llm_model
            if llm_api_key:
                if "gemini" in llm_service.lower():
                    config["gemini_api_key"] = llm_api_key
                elif "claude" in llm_service.lower():
                    config["claude_api_key"] = llm_api_key
                elif "openai" in llm_service.lower():
                    config["openai_api_key"] = llm_api_key

        config_parser = ConfigParser(config)

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(data)
            tmp_path = f.name

        try:
            converter = PdfConverter(
                config=config_parser.generate_config_dict(),
                artifact_dict=_models,
                processor_list=config_parser.get_processors(),
                renderer=config_parser.get_renderer(),
                llm_service=config_parser.get_llm_service() if use_llm else None,
            )
            rendered = converter(tmp_path)
            _log.info(
                "convert pdf extraction done source_id=%s extracting markdown and images",
                sid,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        full_markdown, _, pil_images = text_from_rendered(rendered)
        _log.info(
            "convert text_from_rendered done source_id=%s markdown_chars=%d pil_image_count=%d",
            sid,
            len(full_markdown),
            len(pil_images or {}),
        )
        # pil_images: {filename: PIL.Image}
        b64_images = {name: _pil_to_b64(img) for name, img in (pil_images or {}).items()}
        _log.info(
            "convert images to base64 done source_id=%s encoded_images=%d",
            sid,
            len(b64_images),
        )

        # Split into per-page sections (paginate_output inserts separators)
        raw_pages = _PAGE_SEP.split(full_markdown)

        pages = []
        for i, page_md in enumerate(raw_pages):
            page_md = page_md.strip()
            if not page_md:
                continue
            refs = _IMG_REF.findall(page_md)
            page_images = [
                {"filename": ref, "b64": b64_images[ref]}
                for ref in refs
                if ref in b64_images
            ]
            pages.append({"page_num": i + 1, "markdown": page_md, "images": page_images})

        _log.info(
            "convert done source_id=%s filename=%s pages=%d",
            sid,
            file.filename,
            len(pages),
        )
        return pages
    except Exception:
        _log.exception(
            "convert failed source_id=%s filename=%s suffix=%s bytes=%d",
            sid,
            file.filename,
            suffix,
            len(data),
        )
        raise
