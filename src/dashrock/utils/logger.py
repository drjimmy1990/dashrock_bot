"""Structured logging — JSON file + console, correlation IDs."""

from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dashrock.config import LoggingCfg

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter with correlation ID support."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id.get(""),
        }
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def setup_logging(cfg: LoggingCfg) -> None:
    """Configure root logger with console + JSON file handlers."""
    root = logging.getLogger()
    root.setLevel(cfg.level)

    # Clear existing handlers to avoid duplicates on re-init
    root.handlers.clear()

    # Console: human-readable
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(console)

    # File: JSON structured
    log_path = Path(cfg.file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        str(log_path),
        maxBytes=cfg.max_size_mb * 1024 * 1024,
        backupCount=3,
    )
    file_handler.setFormatter(JSONFormatter())
    root.addHandler(file_handler)

    # Silence noisy third-party loggers — they spam every HTTP req / WS frame
    for noisy in ("httpx", "httpcore", "websockets", "hpack", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def new_correlation_id() -> str:
    """Generate a new correlation ID and set it in context."""
    cid = uuid.uuid4().hex[:12]
    correlation_id.set(cid)
    return cid
