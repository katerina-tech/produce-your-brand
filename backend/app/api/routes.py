"""HTTP endpoints.

This layer is deliberately thin: parse, delegate to a service, serialise. No
business logic lives here, which is what allows the frontend to be replaced (or
a CLI added) without touching the workflow.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.api.dto import HealthResponse, ReadinessChecks
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

VERSION = "0.1.0"


def _readiness(settings: Settings) -> ReadinessChecks:
    knowledge_docs = (
        sorted(settings.knowledge_dir.glob("*.md")) if settings.knowledge_dir.is_dir() else []
    )
    return ReadinessChecks(
        api_key_configured=settings.has_api_key,
        suppliers_file_present=settings.suppliers_file.is_file(),
        knowledge_dir_present=settings.knowledge_dir.is_dir(),
        knowledge_doc_count=len(knowledge_docs),
        search_index_built=(settings.index_dir / "index.faiss").is_file(),
    )


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    """Liveness plus readiness. Safe to expose: contains no secrets."""
    checks = _readiness(get_settings())
    degraded = not (checks.api_key_configured and checks.suppliers_file_present)
    return HealthResponse(status="degraded" if degraded else "ok", version=VERSION, checks=checks)
