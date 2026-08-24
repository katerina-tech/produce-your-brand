"""HTTP endpoints.

This layer is deliberately thin: parse, delegate to a service, serialise. No
business logic lives here, which is what allows the frontend to be replaced (or a
CLI added) without touching the workflow.

Seven endpoints, and only one of them advances the workflow. ``/resume`` answers
whichever gate the graph is paused at, because the graph is the authority on
where it is - a client cannot talk it into skipping a human approval by calling a
different path.
"""

from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.api.dto import (
    CreateProjectRequest,
    GeneratedDesignResponse,
    GenerateDesignRequest,
    HealthResponse,
    NearbyStudioResponse,
    NearbyStudiosResponse,
    ProjectListResponse,
    ProjectStateResponse,
    ProjectSummaryResponse,
    ReadinessChecks,
    ResumeRequest,
    UploadResponse,
)
from app.config import Settings, get_settings
from app.llm.factory import ImageProvider
from app.security.uploads import UploadRejectedError, store_upload
from app.services.design_service import DesignGenerationError, generate_design
from app.services.osm_search import OSMSearchError, OverpassStudioSearch
from app.services.project_service import (
    DesignNotFoundError,
    ProjectService,
    ProjectView,
    StageMismatchError,
)

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


def get_app_settings(request: Request) -> Settings:
    """Resolve the settings the app was actually built with.

    ``create_app(settings=...)`` lets a caller (a test, in practice) inject
    custom settings, and the lifespan honours that for the workflow and the
    image provider. Routes must resolve the same object rather than the
    process-wide ``get_settings()`` singleton - calling the singleton directly
    would silently ignore an injected override, which is what happened here
    before this dependency existed: uploads and generation used to always read
    the real production upload directory regardless of what the app was
    constructed with.
    """
    settings: Settings | None = getattr(request.app.state, "settings", None)
    return settings or get_settings()


def get_image_generation_provider(request: Request) -> ImageProvider:
    """Resolve the image provider built once at startup.

    Injected the same way as :func:`get_service`, rather than constructed
    inline in the route, so a test can swap in a scripted provider without a
    real API key or network access - and so there is exactly one place the
    production wiring happens (``main.py``'s lifespan), not one per route.
    """
    provider: ImageProvider | None = getattr(request.app.state, "image_provider", None)
    if provider is None:
        raise HTTPException(status_code=503, detail="The service is not ready.")
    return provider


def get_osm_search_client(request: Request) -> OverpassStudioSearch:
    """Resolve the OSM search client built once at startup - same reasoning as
    :func:`get_image_generation_provider`: one production wiring site, and a
    test can inject a fake instead of reaching the real Overpass API."""
    client: OverpassStudioSearch | None = getattr(request.app.state, "osm_search", None)
    if client is None:
        raise HTTPException(status_code=503, detail="The service is not ready.")
    return client


def _to_response(view: ProjectView) -> ProjectStateResponse:
    return ProjectStateResponse(
        project_id=view.project_id,
        stage=view.stage,
        product=view.product,
        design_upload_id=view.design_upload_id,
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
def health(request: Request, settings: Settings = Depends(get_app_settings)) -> HealthResponse:
    """Liveness plus readiness. Safe to expose: contains no secrets."""
    checks = _readiness(settings, request)
    degraded = not (checks.api_key_configured and checks.suppliers_file_present)
    return HealthResponse(status="degraded" if degraded else "ok", version=VERSION, checks=checks)


# ------------------------------------------------------------------- projects


@router.post("/projects", response_model=ProjectStateResponse, status_code=201, tags=["projects"])
def create_project(
    body: CreateProjectRequest, service: ProjectService = Depends(get_service)
) -> ProjectStateResponse:
    """Start a project and run to the first human gate."""
    try:
        return _to_response(service.create(body.request_text, body.design_upload_id))
    except DesignNotFoundError as missing:
        raise HTTPException(status_code=422, detail=str(missing)) from missing


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


@router.get(
    "/projects/{project_id}/nearby-studios",
    response_model=NearbyStudiosResponse,
    tags=["projects"],
)
def nearby_studios(
    project_id: str,
    service: ProjectService = Depends(get_service),
    client: OverpassStudioSearch = Depends(get_osm_search_client),
) -> NearbyStudiosResponse:
    """Real, unscored Berlin businesses from OpenStreetMap for this project's
    confirmed method - see app/services/osm_search.py for why these are kept
    separate from supplier matches rather than merged into them.

    Available once a method is confirmed; before that there is nothing to
    search for, and the response says so rather than guessing a technique.
    """
    project = service.get_record(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="No such project.")

    if project.confirmed_method is None:
        return NearbyStudiosResponse(
            studios=[],
            note="No production method confirmed yet - nothing to search for.",
        )

    try:
        studios = client.search(project.confirmed_method)
    except OSMSearchError as failure:
        # 502: our request was fine, OpenStreetMap's public endpoint was not
        # reachable or timed out. This is a convenience layer, not a gate, so
        # nothing about the project itself is affected by this failing.
        raise HTTPException(status_code=502, detail=str(failure)) from failure

    return NearbyStudiosResponse(
        studios=[NearbyStudioResponse(**studio.model_dump()) for studio in studios]
    )


# -------------------------------------------------------------------- uploads


@router.post("/uploads", response_model=UploadResponse, status_code=201, tags=["uploads"])
async def upload_design(
    file: UploadFile = File(...), settings: Settings = Depends(get_app_settings)
) -> UploadResponse:
    """Validate and store a design file. Metadata only comes back.

    The body is never returned, never rendered and never sent to a model in this
    phase - it is validated, stored inert under a generated name, and referenced
    by id.
    """
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


@router.post(
    "/designs/generate",
    response_model=GeneratedDesignResponse,
    status_code=201,
    tags=["uploads"],
)
def generate_design_route(
    body: GenerateDesignRequest,
    provider: ImageProvider = Depends(get_image_generation_provider),
    settings: Settings = Depends(get_app_settings),
) -> GeneratedDesignResponse:
    """Generate a design from a text prompt. The one call in this system with a
    real per-image cost - see the README's Design attachment section.

    The generated bytes are stored exactly like an upload (same magic-byte
    validation) and are echoed back once, as a preview, which no other endpoint
    repeats: see :class:`GeneratedDesignResponse`.
    """
    try:
        record = generate_design(body.prompt, provider, settings)
    except DesignGenerationError as failure:
        # 502: our own request was fine, but the upstream image provider could
        # not fulfil it - a refusal, an outage, or unusable bytes.
        raise HTTPException(status_code=502, detail=str(failure)) from failure

    content = (settings.upload_dir / record.stored_name).read_bytes()
    preview = f"data:{record.mime_type};base64,{base64.b64encode(content).decode()}"

    return GeneratedDesignResponse(
        upload_id=record.upload_id,
        filename=record.original_name,
        mime_type=record.mime_type,
        size_bytes=record.size_bytes,
        preview_data_url=preview,
    )
