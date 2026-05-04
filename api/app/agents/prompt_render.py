"""Render agent system prompts with shared run context (Jinja wrapper)."""

from datetime import datetime
from pathlib import Path

from jinja2 import Template

_PROMPTS = Path(__file__).parent / "prompts"
_SYSTEM_PROMPT_WRAPPER = Template((_PROMPTS / "run_context_wrapper.md").read_text())


def render_system_prompt(body: str, *, model: str | None = None) -> str:
    """Wrap *body* with server-local time; pass *model* to expose the configured LiteLLM id."""
    now = datetime.now().astimezone()
    tz_label = (now.tzname() or "").strip()
    server_local_datetime = now.strftime("%Y-%m-%d %H:%M:%S")
    return _SYSTEM_PROMPT_WRAPPER.render(
        server_local_datetime=server_local_datetime,
        tz_label=tz_label,
        model=model,
        body=body,
    )
