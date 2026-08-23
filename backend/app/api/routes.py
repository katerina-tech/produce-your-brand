"""HTTP endpoints.

This layer is deliberately thin: parse, delegate to a service, serialise. No
business logic lives here, which is what allows the frontend to be replaced (or a
CLI added) without touching the workflow.

Six endpoints, and only one of them advances the workflow. ``/resume`` answers
whichever gate the graph is paused at, because the graph is the authority on
where it is - a client cannot talk it into skipping a human approval by calling a
different path.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.api.dto import (
    CreateProjectRequest,
    HealthResponse,
    ProjectListResponse,
    ProjectStateResponse,
    ProjectSummaryResponse,
    ReadinessChecks,
    ResumeRequest,
    UploadResponse,
)
from app.config import Settings, get_settings
from app.security.uploads import UploadRejectedError, store_upload
from app.services.project_service import ProjectService, ProjectView, StageMismatchError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

VERSION = "0.1.0"

MAX_UPLOAD_READ = 8 * 1024 * 1024


def get_service(request: Request) -> ProjectService:
    """Resolve the service built once at startup."""
    service: ProjectService | None = getattr(request.app.state, "project_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="The service is not ready.")
    return service


def _to_response(view: ProjectView) -> ProjectStateResponse:
    return ProjectStateResponse(
        project_id=view.project_id,
        stage=view.stage,
        product=view.product,
        payload=view.payload,
        expected_action=view.expected_action,
        errors=view.errors,
        is_complete=view.is_complete,
    )


# --------------------------------------------------------------------- system


def _readiness(settings: Settings, request: Request) -> ReadinessChecks:
    knowledge_docs = (
        sorted(settings.knowledge_dir.glob("*.md")) if settings.knowledge_dir.is_dir() else []
    )
    return ReadinessChecks(
        api_key_configured=settings.has_api_key,
        suppliers_file_present=settings.suppliers_file.is_file(),
        supplier_count=getattr(request.app.state, "supplier_count", 0),
        knowledge_dir_present=settings.knowledge_dir.is_dir(),
        knowledge_doc_count=len(knowledge_docs),
        search_index_built=(settings.index_dir / "index.faiss").is_file(),
        injection_guard_enabled=settings.injection_classifier_enabled,
    )


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health(request: Request) -> HealthResponse:
    """Liveness plus readiness. Safe to expose: contains no secrets."""
    settings = get_settings()
    checks = _readiness(settings, request)
    degraded = not (checks.api_key_configured and checks.suppliers_file_present)
    return HealthResponse(status="degraded" if degraded else "ok", version=VERSION, checks=checks)


# ------------------------------------------------------------------- projects


@router.post("/projects", response_model=ProjectStateResponse, status_code=201, tags=["projects"])
def create_project(
    body: CreateProjectRequest, service: ProjectService = Depends(get_service)
) -> ProjectStateResponse:
    """Start a project and run to the first human gate."""
    return _to_response(service.create(body.request_text))


@router.get("/projects", response_model=ProjectListResponse, tags=["projects"])
def list_projects(service: ProjectService = Depends(get_service)) -> ProjectListResponse:
    """Dashboard rows, newest first."""
    return ProjectListResponse(
        projects=[
            ProjectSummaryResponse(
                id=summary.id,
                stage=summary.stage,
                product=summary.product,
                quantity=summary.quantity,
                updated_at=summary.updated_at.isoformat(),
            )
            for summary in service.list_summaries()
        ]
    )


@router.get("/projects/{project_id}", response_model=ProjectStateResponse, tags=["projects"])
def get_project(
    project_id: str, service: ProjectService = Depends(get_service)
) -> ProjectStateResponse:
    """Full current state. This is the "leave and come back" endpoint."""
    view = service.get(project_id)
    if view is None:
        raise HTTPException(status_code=404, detail="No such project.")
    return _to_response(view)


@router.post(
    "/projects/{project_id}/resume", response_model=ProjectStateResponse, tags=["projects"]
)
def resume_project(
    project_id: str, body: ResumeRequest, service: ProjectService = Depends(get_service)
) -> ProjectStateResponse:
    """Answer the current gate and run to the next one.

    A mismatched action returns 409 naming the action the workflow actually
    expects, so a stale browser tab gets a correctable answer rather than
    silently resuming the wrong branch.
    """
    try:
        return _to_response(service.resume(project_id, body.action, body.payload()))
    except KeyError as missing:
        raise HTTPException(status_code=404, detail="No such project.") from missing
    except StageMismatchError as mismatch:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This project is not waiting for '{mismatch.received}'. "
                f"It expects '{mismatch.expected}'."
            ),
        ) from mismatch


# -------------------------------------------------------------------- uploads


@router.post("/uploads", response_model=UploadResponse, status_code=201, tags=["uploads"])
async def upload_design(file: UploadFile = File(...)) -> UploadResponse:
    """Validate and store a design file. Metadata only comes back.

    The body is never returned, never rendered and never sent to a model in this
    phase - it is validated, stored inert under a generated name, and referenced
    by id.
    """
    settings = get_settings()

    # Read with a hard ceiling above the configured limit, so an oversized upload
    # is refused without buffering an unbounded body first.
    content = await file.read(MAX_UPLOAD_READ + 1)
    if len(content) > MAX_UPLOAD_READ:
        raise HTTPException(status_code=413, detail="The file is too large.")

    try:
        record = store_upload(file.filename or "upload", content, settings)
    except UploadRejectedError as rejection:
        raise HTTPException(status_code=415, detail=str(rejection)) from rejection

    return UploadResponse(
        upload_id=record.upload_id,
        filename=record.original_name,
        mime_type=record.mime_type,
        size_bytes=record.size_bytes,
    )
