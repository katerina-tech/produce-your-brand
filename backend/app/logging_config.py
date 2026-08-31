"""The single logging configuration for the backend.

Every module obtains its logger with ``logging.getLogger(__name__)``. Structured
events are emitted through :func:`log_event` so that event names are a closed
enum rather than free-form strings scattered across the codebase.

Redaction policy: user request text is logged truncated and hashed, never in
full. Secrets are never logged - :class:`~app.config.Settings` stores the API key
as ``SecretStr`` so it cannot be stringified by accident.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from enum import StrEnum
from typing import Any

RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}

_TRUNCATE_AT = 200


class Event(StrEnum):
    """Closed set of structured log events (see README, Observability)."""

    API_STARTED = "api_started"
    PROJECT_CREATED = "project_created"
    PROJECT_RESUMED = "project_resumed"
    PROJECT_PERSISTED = "project_persisted"
    REQUIREMENT_EXTRACTION_STARTED = "requirement_extraction_started"
    REQUIREMENT_EXTRACTION_COMPLETED = "requirement_extraction_completed"
    CLARIFICATION_REQUESTED = "clarification_requested"
    CLARIFICATION_ANSWERED = "clarification_answered"
    BRIEF_CONFIRMED = "brief_confirmed"
    RETRIEVAL_DECISION = "retrieval_decision"
    RAG_CALLED = "rag_called"
    RAG_COMPLETED = "rag_completed"
    METHOD_RECOMMENDED = "method_recommended"
    METHOD_CONFIRMED = "method_confirmed"
    SUPPLIER_SEARCH_STARTED = "supplier_search_started"
    SUPPLIER_CANDIDATES_FOUND = "supplier_candidates_found"
    SUPPLIER_MATCHING_COMPLETED = "supplier_matching_completed"
    SUPPLIER_SELECTED = "supplier_selected"
    RFQ_GENERATED = "rfq_generated"
    RFQ_APPROVED = "rfq_approved"
    INJECTION_SUSPECTED = "injection_suspected"
    UPLOAD_REJECTED = "upload_rejected"
    UPLOAD_ACCEPTED = "upload_accepted"
    DESIGN_GENERATION_STARTED = "design_generation_started"
    DESIGN_GENERATION_COMPLETED = "design_generation_completed"
    OSM_SEARCH_COMPLETED = "osm_search_completed"
    REQUEST_RESTARTED = "request_restarted"
    OFFERS_LOADED = "offers_loaded"
    FEEDBACK_SUBMITTED = "feedback_submitted"
    LLM_ERROR = "llm_error"
    TOOL_ERROR = "tool_error"
    VALIDATION_ERROR = "validation_error"


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per line, including any ``extra`` fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in RESERVED:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Human-readable format for local development."""

    def format(self, record: logging.LogRecord) -> str:
        extras = " ".join(
            f"{k}={v}" for k, v in record.__dict__.items() if k not in RESERVED and k != "event"
        )
        event = getattr(record, "event", "-")
        stamp = self.formatTime(record, "%H:%M:%S")
        base = f"{stamp} {record.levelname:<7} [{event}] {record.getMessage()}"
        return f"{base}  {extras}".rstrip()


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Install the single root handler. Idempotent - safe to call twice."""
    formatter: logging.Formatter = JsonFormatter() if fmt == "json" else ConsoleFormatter()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Third-party noise: keep our own logs readable.
    for noisy in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(
    logger: logging.Logger,
    event: Event,
    message: str = "",
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit a structured event.

    Callers pass domain fields as keyword arguments; they land as top-level keys
    in the JSON output. Never pass secrets or full user documents here - use
    :func:`redact_text` for anything user-supplied.
    """
    logger.log(level, message or event.value, extra={"event": event.value, **fields})


def redact_text(text: str | None) -> dict[str, Any]:
    """Summarise user-supplied text for logs: length, hash, short preview.

    The full text is deliberately never returned, so request bodies and document
    contents cannot end up in log storage.
    """
    if not text:
        return {"text_len": 0, "text_sha256": None, "text_preview": None}
    encoded = text.encode("utf-8", errors="replace")
    preview = text[:_TRUNCATE_AT].replace("\n", " ")
    return {
        "text_len": len(text),
        "text_sha256": hashlib.sha256(encoded).hexdigest()[:16],
        "text_preview": preview + ("..." if len(text) > _TRUNCATE_AT else ""),
    }
