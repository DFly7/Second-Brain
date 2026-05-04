"""Structlog context for agent runs: every log line includes ``agent`` and bound IDs."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from structlog.contextvars import bind_contextvars, clear_contextvars


@contextmanager
def agent_run_context(agent: str, **fields: object) -> Iterator[None]:
    cleaned = {k: v for k, v in fields.items() if v is not None}
    bind_contextvars(agent=agent, **cleaned)
    try:
        yield
    finally:
        clear_contextvars()
