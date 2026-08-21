"""HTTP boundary models.

Kept separate from :mod:`app.domain` on purpose: domain models may evolve for
business reasons, while these are a wire contract the frontend depends on.
``frontend/lib/types.ts`` mirrors this module.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Stage


class ErrorDetail(BaseModel):
    """Machine-readable error body. Never contains a stack trace or model output."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Stable, machine-readable error code.")
    message: str = Field(description="Human-readable, safe to display.")
    stage: Stage | None = Field(default=None, description="Where in the workflow this failed.")
    recoverable: bool = Field(
        default=True, description="True when retrying or editing input can succeed."
    )


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail


class ReadinessChecks(BaseModel):
    """Deployment-readiness signals. Booleans only - never the API key itself."""

    model_config = ConfigDict(extra="forbid")

    api_key_configured: bool
    suppliers_file_present: bool
    knowledge_dir_present: bool
    knowledge_doc_count: int
    search_index_built: bool


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    version: str
    checks: ReadinessChecks
