"""One JSON object per line, to a file, from stdlib logging only.

Every claim this project makes about a public authority is only as good as the
audit trail behind it: which URL was called, when, what came back. A plain text
log is unreadable once there are thousands of calls, so each record is a JSON
object on its own line — greppable by eye, and loadable with json.loads per
line without a parser or a dependency.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

LOGGER_NAME = "tender_scan"
DEFAULT_LOG_PATH = "tender_scan.log"

# LogRecord attributes that carry a structured payload live under this key, so
# they can never collide with the record's own attribute names.
_FIELDS = "fields"


class JsonFileHandler(logging.FileHandler):
    """Marker subclass so configure() can find its own handler and no other.

    Other handlers on this logger belong to whoever attached them — a host
    application, or pytest's log capture — and are left alone.
    """


class JsonLineFormatter(logging.Formatter):
    """Renders a record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(getattr(record, _FIELDS, None) or {})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure(log_path: str | Path | None = None, level: int = logging.INFO) -> logging.Logger:
    """Attach the JSON file handler to the package logger and return it.

    Idempotent: any handler this function attached earlier is closed and
    replaced, so calling it twice (CLI startup plus a library entry point)
    neither doubles the lines nor pins the log to a stale path.
    """
    path = Path(log_path or os.environ.get("TENDER_SCAN_LOG") or DEFAULT_LOG_PATH)
    logger = logging.getLogger(LOGGER_NAME)
    for previous in [h for h in logger.handlers if isinstance(h, JsonFileHandler)]:
        logger.removeHandler(previous)
        previous.close()

    handler = JsonFileHandler(path, encoding="utf-8")
    handler.setFormatter(JsonLineFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False  # the JSON lines are for the file, not for the root handlers
    return logger


def log_external_call(url: str, status: int | None, elapsed_ms: float, note: str = "") -> None:
    """Record one outbound HTTP call: url, status (None when it never answered), duration."""
    logger = logging.getLogger(LOGGER_NAME)
    if not any(isinstance(h, JsonFileHandler) for h in logger.handlers):
        configure()  # a call must never go unlogged just because nobody called configure()
    logger.info(
        "external_call",
        extra={
            _FIELDS: {
                "event": "external_call",
                "url": url,
                "status": status,
                "elapsed_ms": round(elapsed_ms, 1),
                "note": note,
            }
        },
    )
