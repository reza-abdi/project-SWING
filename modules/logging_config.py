"""Structured service logging with bounded messages and credential redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Iterator, TextIO
from uuid import uuid4


MAX_LOG_MESSAGE_LENGTH = 2000
_request_id: ContextVar[str | None] = ContextVar("swing_request_id", default=None)
_SECRET_PATTERNS = (
    re.compile(r"(?i)(\bauthorization\s*[:=]\s*)(?:(?:bearer|basic)\s+)?[^\s,;]+"),
    re.compile(r"(?i)(\b(?:api[_-]?key|google_api_key|token|password|client_secret)\s*[:=]\s*)[^\s,;]+"),
)


def redact_and_bound(message: str, *, limit: int = MAX_LOG_MESSAGE_LENGTH) -> str:
    result = message
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(r"\1[REDACTED]", result)
    if len(result) > limit:
        result = result[: max(0, limit - 15)] + "…[truncated]"
    return result


@contextmanager
def request_context(request_id: str | None = None) -> Iterator[str]:
    """Attach one bounded correlation ID to log records in the current context."""
    value = redact_and_bound(request_id or uuid4().hex, limit=128)
    token = _request_id.set(value)
    try:
        yield value
    finally:
        _request_id.reset(token)


class SafeRecordFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = "<log message formatting failed>"
        if record.exc_info:
            message += "\n" + "".join(traceback.format_exception(*record.exc_info))
        record.msg = redact_and_bound(message)
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = redact_and_bound(record.stack_info) if record.stack_info else None
        record.request_id = getattr(record, "request_id", None) or _request_id.get() or uuid4().hex
        record.service = record.name.split(".", 1)[0]
        return True


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "level": record.levelname,
                "service": record.service,
                "logger": record.name,
                "request_id": record.request_id,
                "message": record.msg,
            },
            ensure_ascii=False,
        )


def configure_logging(level: str = "INFO", *, stream: TextIO | None = None) -> None:
    normalized = level.upper()
    if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ValueError("SWING_LOG_LEVEL must be DEBUG, INFO, WARNING, or ERROR")
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.addFilter(SafeRecordFilter())
    handler.setFormatter(JsonLogFormatter())
    for service in ("digital_twin", "ai_agent"):
        logger = logging.getLogger(service)
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(normalized)
        logger.propagate = False
