"""HTTP boundary models.

Kept separate from :mod:`app.domain` on purpose: domain models may evolve for
business reasons, while these are a wire contract the frontend depends on.
``frontend/lib/types.ts`` mirrors this module.
"""

from __future__ import annotations

from typing import Any, Literal

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
    expected_action: str | None = Field(
        default=None,
        description="On a stage mismatch, the action the workflow is actually waiting for.",
    )


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail


class ReadinessChecks(BaseModel):
    """Deployment-readiness signals. Booleans only - never the API key itself."""

    model_config = ConfigDict(extra="forbid")

    api_key_configured: bool
    suppliers_file_present: bool
    supplier_count: int
    knowledge_dir_present: bool
    knowledge_doc_count: int
    search_index_built: bool
    injection_guard_enabled: bool


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    version: str
    checks: ReadinessChecks


# ------------------------------------------------------------------- projects


class CreateProjectRequest(BaseModel):
    """A new project starts as one paragraph of natural language."""

    model_config = ConfigDict(extra="forbid")

    request_text: str = Field(
        min_length=10,
        max_length=8000,
        description="What the customer wants produced, in their own words.",
    )
    design_upload_id: str | None = Field(
        default=None, description="Optional id returned by POST /api/uploads."
    )


ResumeAction = Literal[
    "answer_clarification",
    "confirm_brief",
    "edit_brief",
    "confirm_method",
    "select_supplier",
    "approve_rfq",
    "edit_rfq",
]


class ResumeRequest(BaseModel):
    """Answer the gate the workflow is currently paused at.

    One endpoint rather than seven: the graph already knows which interrupt it is
    parked at, so the server validates the action against that rather than
    trusting the client to call the right path.
    """

    model_config = ConfigDict(extra="forbid")

    action: ResumeAction
    answer: str | None = Field(default=None, max_length=4000)
    requirement: dict[str, Any] | None = None
    method: str | None = None
    supplier_id: str | None = None
    rfq: dict[str, Any] | None = None
    approved: bool | None = None

    def payload(self) -> dict[str, Any]:
        """Only the fields relevant to this action."""
        return self.model_dump(exclude={"action"}, exclude_none=True)


class ProjectStateResponse(BaseModel):
    """The current step, plus whatever the paused node published.

    The frontend switches on ``stage`` and renders ``payload``. That is the whole
    client contract, and why no workflow logic lives in the browser.
    """

    model_config = ConfigDict(extra="forbid")

    project_id: str
    stage: Stage
    payload: dict[str, Any] | None = None
    expected_action: str | None = None
    errors: list[str] = []
    is_complete: bool = False


class ProjectSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    stage: Stage
    product: str | None
    quantity: int | None
    updated_at: str


class ProjectListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projects: list[ProjectSummaryResponse]


# -------------------------------------------------------------------- uploads


class UploadResponse(BaseModel):
    """Metadata only. The file body is never returned or sent to a model."""

    model_config = ConfigDict(extra="forbid")

    upload_id: str
    filename: str
    mime_type: str
    size_bytes: int
