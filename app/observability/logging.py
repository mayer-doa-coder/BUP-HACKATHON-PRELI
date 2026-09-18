"""Structured JSON logging with correlation IDs.

Replaces the ``logging.basicConfig`` placeholder left in P1. Three things matter here:

* **Every line is JSON**, so a hosting platform's log search can filter on ``correlation_id``,
  ``http_status`` or ``failure_code`` instead of grepping prose.
* **The correlation ID travels in a context variable**, not through every function signature.
  Context variables are task-local under asyncio, so a line logged deep in the optimizer carries
  the right request's ID even with many requests in flight.
* **Operator notes and model output are never logged by default.** They are the two places
  where untrusted or sensitive content could leak into a log aggregator, so they are redacted to
  a hash plus a length unless a flag explicitly enables them for local debugging.

Third-party loggers are quietened deliberately: at INFO, ``httpx`` logs a line per provider call
and ``uvicorn.access`` one per request, which would bury the service's own structured output.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

from app.config import Settings, get_settings

#: Task-local correlation ID. Empty string when logging outside a request.
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")

#: Attributes the standard library puts on every record; anything else is caller-supplied.
_STANDARD_RECORD_FIELDS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
        "levelname", "levelno", "lineno", "module", "msecs", "msg", "message", "name",
        "pathname", "process", "processName", "relativeCreated", "stack_info", "taskName",
        "thread", "threadName",
    }
)

#: Logger *prefixes* that are noisy at INFO and say nothing this service does not already
#: record. Prefix matching rather than exact names because the installed client may register
#: under a variant name (``httpx2``), and an exact list would silently miss it.
_QUIET_LOGGER_PREFIXES = ("httpx", "httpcore", "uvicorn.access", "python_multipart", "asyncio")

REDACTION_PREVIEW_CHARS = 200


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line, with caller-supplied ``extra`` fields merged in."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        correlation_id = getattr(record, "correlation_id", None) or correlation_id_var.get()
        if correlation_id:
            payload["correlation_id"] = correlation_id

        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_FIELDS and key != "correlation_id":
                payload[key] = _jsonable(value)

        if record.exc_info:
            # The type and message only. A full traceback can carry request content, and it is
            # never needed to identify the failure when the correlation ID is right there.
            exception_type, exception, _ = record.exc_info
            payload["error_type"] = getattr(exception_type, "__name__", str(exception_type))
            payload["error_message"] = str(exception)

        return json.dumps(payload, default=str, ensure_ascii=False)


class QuietThirdPartyFilter(logging.Filter):
    """Drop sub-warning chatter from third-party libraries.

    Applied as a handler filter rather than by setting levels on named loggers, so it also
    covers loggers that are created *after* configuration — which is the usual case, since
    libraries register their loggers on first use.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        return not record.name.startswith(_QUIET_LOGGER_PREFIXES)


def configure_logging(settings: Settings | None = None) -> None:
    """Install the JSON handler on the root logger. Safe to call more than once."""
    settings = settings or get_settings()

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    handler.addFilter(QuietThirdPartyFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)


def bind_correlation_id(correlation_id: str) -> None:
    correlation_id_var.set(correlation_id)


def current_correlation_id() -> str:
    return correlation_id_var.get()


# --------------------------------------------------------------------------- redaction


def redact_note(note: str, settings: Settings | None = None) -> str:
    """Render an operator note for logs.

    Notes are untrusted third-party text and may describe real operations, so by default only a
    stable hash and a length are recorded — enough to correlate repeated inputs or reproduce a
    cache key, without putting the content itself into a log aggregator.
    """
    settings = settings or get_settings()
    if settings.log_raw_operator_notes:
        return note[:REDACTION_PREVIEW_CHARS]
    return f"sha256:{_short_hash(note)} len={len(note)}"


def redact_model_output(output: str, settings: Settings | None = None) -> str:
    """Render raw model output for logs, redacted unless explicitly enabled."""
    settings = settings or get_settings()
    if settings.log_llm_raw_output:
        return output[:REDACTION_PREVIEW_CHARS]
    return f"sha256:{_short_hash(output)} len={len(output)}"


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _jsonable(value: Any) -> Any:
    if isinstance(value, str | int | float | bool | type(None)):
        return value
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return str(value)


__all__ = [
    "REDACTION_PREVIEW_CHARS",
    "JsonLogFormatter",
    "QuietThirdPartyFilter",
    "bind_correlation_id",
    "configure_logging",
    "correlation_id_var",
    "current_correlation_id",
    "redact_model_output",
    "redact_note",
]
