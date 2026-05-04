import logging
import os

import structlog
import structlog.testing
import pytest

from app.logging_config import configure_logging


def test_configure_logging_json_sets_up_structlog(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "json")
    configure_logging()
    config = structlog.get_config()
    assert config["logger_factory"].__class__.__name__ == "LoggerFactory"


def test_configure_logging_console_does_not_raise(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "console")
    configure_logging()


def test_litellm_loggers_suppressed():
    configure_logging()
    assert logging.getLogger("LiteLLM").level == logging.WARNING
    assert logging.getLogger("litellm").level == logging.WARNING
