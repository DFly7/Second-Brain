import base64
import io
import re
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from marker.config.parser import ConfigParser
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered
from PIL import Image

app = FastAPI(title="Marker Service")

# Models load once at startup — intentionally module-level
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
):
    data = await file.read()
    suffix = Path(file.filename or "file.pdf").suffix or ".pdf"

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
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    full_markdown, _, pil_images = text_from_rendered(rendered)
    # pil_images: {filename: PIL.Image}
    b64_images = {name: _pil_to_b64(img) for name, img in (pil_images or {}).items()}

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

    return pages
