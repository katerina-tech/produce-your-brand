"""HTTP endpoints.

This layer is deliberately thin: parse, delegate to a service, serialise. No
business logic lives here, which is what allows the frontend to be replaced (or a
CLI added) without touching the workflow.

Ten endpoints, and only one of them advances the workflow. ``/resume`` answers
whichever gate the graph is paused at, because the graph is the authority on
where it is - a client cannot talk it into skipping a human approval by calling a
different path. ``/feedback`` and ``/analytics/feedback`` never touch the graph
at all - they are the product-validation instrumentation, not a workflow step.
"""

from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile

from app.api.dto import (
    AccountResponse,
    CreateProjectRequest,
    CredentialsRequest,
    FeedbackEntryResponse,
    FeedbackListResponse,
    FeedbackRequest,
    FeedbackResponse,
    GeneratedDesignResponse,
    GenerateDesignRequest,
    HealthResponse,
    NearbyStudioResponse,
    NearbyStudiosResponse,
    OutreachResponse,
    ProjectListResponse,
    ProjectStateResponse,
    ProjectSummaryResponse,
    ReadinessChecks,
    ResumeRequest,
    UploadResponse,
)
from app.config import Settings, get_settings
from app.llm.factory import ImageProvider
from app.repositories.user_repo import EmailAlreadyRegisteredError, UserRepository
from app.security.uploads import UploadRejectedError, store_upload
from app.services.auth import (
    SESSION_COOKIE,
    AuthError,
    hash_password,
    issue_session,
    normalise_email,
    read_session,
    sign_in_available,
    validate_credentials,
    verify_password,
)
from app.services.design_service import DesignGenerationError, generate_design
from app.services.osm_search import OSMSearchError, OverpassStudioSearch
from app.services.outreach import RFQNotApprovedError, render_email
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


def get_users(request: Request) -> UserRepository:
    """Resolve the account repository built at startup."""
    repository: UserRepository | None = getattr(request.app.state, "user_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="The service is not ready.")
    return repository


def current_user_id(request: Request) -> str | None:
    """Who is signed in, if anyone.

    Returns ``None`` rather than refusing, because signing in is optional here:
    an anonymous visitor following a link must reach exactly the product a
    signed-in one does. Ownership, not access, is what an account buys.
    """
    settings: Settings = request.app.state.settings
    return read_session(request.cookies.get(SESSION_COOKIE), settings)


def guard_project(service: ProjectService, project_id: str, viewer_id: str | None) -> None:
    """Refuse a project that belongs to somebody else.

    404 rather than 403, deliberately. 403 would confirm that the id exists,
    which turns this endpoint into a way of discovering other people's
    projects one guess at a time; 404 tells an attacker nothing they did not
    already know and tells a legitimate user exactly as much as they need.
    """
    if not service.visible_to(project_id, viewer_id):
        raise HTTPException(status_code=404, detail="No such project.")


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


def _to_response(view: ProjectView, *, mine: bool = False) -> ProjectStateResponse:
    return ProjectStateResponse(
        project_id=view.project_id,
        stage=view.stage,
        product=view.product,
        design_upload_id=view.design_upload_id,
        payload=view.payload,
        expected_action=view.expected_action,
        errors=view.errors,
        is_complete=view.is_complete,
        mine=mine,
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
        sign_in_configured=sign_in_available(settings),
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
    body: CreateProjectRequest,
    service: ProjectService = Depends(get_service),
    user_id: str | None = Depends(current_user_id),
) -> ProjectStateResponse:
    """Start a project and run to the first human gate.

    Signed in, the project is yours from the moment it exists. Signed out, it
    belongs to nobody and stays openable by anyone holding the link - which is
    what the demo link in the application depends on.
    """
    try:
        return _to_response(
            service.create(body.request_text, body.design_upload_id, owner_id=user_id)
        )
    except DesignNotFoundError as missing:
        raise HTTPException(status_code=422, detail=str(missing)) from missing


@router.get("/projects", response_model=ProjectListResponse, tags=["projects"])
def list_projects(
    service: ProjectService = Depends(get_service),
    user_id: str | None = Depends(current_user_id),
) -> ProjectListResponse:
    """Dashboard rows, newest first: your own, plus the unowned ones."""
    return ProjectListResponse(
        projects=[
            ProjectSummaryResponse(
                id=summary.id,
                stage=summary.stage,
                product=summary.product,
                quantity=summary.quantity,
                updated_at=summary.updated_at.isoformat(),
                mine=summary.mine,
            )
            for summary in service.list_summaries(viewer_id=user_id)
        ]
    )


@router.get("/projects/{project_id}", response_model=ProjectStateResponse, tags=["projects"])
def get_project(
    project_id: str,
    service: ProjectService = Depends(get_service),
    user_id: str | None = Depends(current_user_id),
) -> ProjectStateResponse:
    """Full current state. This is the "leave and come back" endpoint."""
    guard_project(service, project_id, user_id)
    view = service.get(project_id)
    if view is None:
        raise HTTPException(status_code=404, detail="No such project.")
    return _to_response(view, mine=service.owned_by(project_id, user_id))


@router.post(
    "/projects/{project_id}/resume", response_model=ProjectStateResponse, tags=["projects"]
)
def resume_project(
    project_id: str,
    body: ResumeRequest,
    service: ProjectService = Depends(get_service),
    user_id: str | None = Depends(current_user_id),
) -> ProjectStateResponse:
    """Answer the current gate and run to the next one.

    A mismatched action returns 409 naming the action the workflow actually
    expects, so a stale browser tab gets a correctable answer rather than
    silently resuming the wrong branch.
    """
    guard_project(service, project_id, user_id)
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


@router.post("/projects/{project_id}/claim", response_model=ProjectStateResponse, tags=["projects"])
def claim_project(
    project_id: str,
    service: ProjectService = Depends(get_service),
    user_id: str | None = Depends(current_user_id),
) -> ProjectStateResponse:
    """Take ownership of a project that has none.

    This is what makes accounts arrive without stranding anything: work started
    before signing in, or on another device, can be moved onto the shelf it
    belongs on. A project that already has an owner answers 404 like any other
    project you cannot see - including, deliberately, one that is already yours
    to claim a second time.
    """
    if user_id is None:
        raise HTTPException(status_code=401, detail="Sign in to keep a project.")

    view = service.get(project_id)
    if view is None:
        raise HTTPException(status_code=404, detail="No such project.")
    if not service.claim(project_id, user_id):
        raise HTTPException(status_code=404, detail="No such project.")
    return _to_response(view)


@router.get(
    "/projects/{project_id}/nearby-studios",
    response_model=NearbyStudiosResponse,
    tags=["projects"],
)
def nearby_studios(
    project_id: str,
    service: ProjectService = Depends(get_service),
    client: OverpassStudioSearch = Depends(get_osm_search_client),
    user_id: str | None = Depends(current_user_id),
) -> NearbyStudiosResponse:
    """Real, unscored Berlin businesses from OpenStreetMap for this project's
    confirmed method - see app/services/osm_search.py for why these are kept
    separate from supplier matches rather than merged into them.

    Available once a method is confirmed; before that there is nothing to
    search for, and the response says so rather than guessing a technique.
    """
    guard_project(service, project_id, user_id)
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


@router.get("/projects/{project_id}/outreach", response_model=OutreachResponse, tags=["projects"])
def project_outreach(
    project_id: str,
    service: ProjectService = Depends(get_service),
    user_id: str | None = Depends(current_user_id),
) -> OutreachResponse:
    """The approved quotation request, ready to open in a mail client.

    A GET, because it creates nothing and sends nothing: it renders text the
    user already approved. 409 rather than 404 when the RFQ is not approved
    yet - the project exists and the answer is "not at that step", which is
    something the caller can act on.
    """
    guard_project(service, project_id, user_id)
    project = service.get_record(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="No such project.")
    if project.rfq is None:
        raise HTTPException(status_code=409, detail="This project has no quotation request yet.")

    try:
        email = render_email(project.rfq)
    except RFQNotApprovedError as unapproved:
        raise HTTPException(
            status_code=409,
            detail="Approve the quotation request before contacting the partner.",
        ) from unapproved

    return OutreachResponse(
        supplier_name=project.rfq.supplier_name,
        to=email.to,
        subject=email.subject,
        body=email.body,
        gmail_url=email.gmail_url,
        mailto_url=email.mailto_url,
        fits_in_a_url=email.fits_in_a_url,
    )


@router.post(
    "/projects/{project_id}/feedback",
    response_model=FeedbackResponse,
    status_code=201,
    tags=["projects"],
)
def submit_feedback(
    project_id: str,
    body: FeedbackRequest,
    service: ProjectService = Depends(get_service),
    user_id: str | None = Depends(current_user_id),
) -> FeedbackResponse:
    """Record one product-validation response. Not a workflow action - it
    never touches the graph, and it does not require the project to be at
    any particular stage.
    """
    guard_project(service, project_id, user_id)
    try:
        service.record_feedback(project_id, body.model_dump())
    except KeyError as missing:
        raise HTTPException(status_code=404, detail="No such project.") from missing
    return FeedbackResponse()


@router.get(
    "/analytics/feedback",
    response_model=FeedbackListResponse,
    tags=["analytics"],
)
def list_feedback(service: ProjectService = Depends(get_service)) -> FeedbackListResponse:
    """The internal read this data is for. See README's Product hypothesis
    section - there is no dashboard here on purpose, only the raw, honest
    responses, while the sample size is still too small for an aggregate to
    mean anything."""
    entries = service.list_feedback()
    return FeedbackListResponse(
        entries=[
            FeedbackEntryResponse(
                project_id=entry.project_id,
                found_useful=entry.found_useful,
                would_contact_supplier=entry.would_contact_supplier,
                alternative_approach=entry.alternative_approach,
                missing=entry.missing,
                created_at=entry.created_at.isoformat(),
            )
            for entry in entries
        ]
    )


# ------------------------------------------------------------------ accounts


@router.post("/auth/register", response_model=AccountResponse, status_code=201, tags=["auth"])
def register(
    body: CredentialsRequest,
    response: Response,
    users: UserRepository = Depends(get_users),
    settings: Settings = Depends(get_app_settings),
) -> AccountResponse:
    """Create an account and sign in straight away.

    Registering then being asked to sign in again is a pointless second step,
    and the credentials were just proven correct by definition.
    """
    email = normalise_email(body.email)
    try:
        validate_credentials(email, body.password)
        user = users.create(email, hash_password(body.password))
    except AuthError as invalid:
        raise HTTPException(status_code=422, detail=str(invalid)) from invalid
    except EmailAlreadyRegisteredError as taken:
        raise HTTPException(
            status_code=409, detail="That address already has an account. Sign in instead."
        ) from taken

    _set_session_cookie(response, user.id, settings)
    return AccountResponse(id=user.id, email=user.email)


@router.post("/auth/login", response_model=AccountResponse, tags=["auth"])
def login(
    body: CredentialsRequest,
    response: Response,
    users: UserRepository = Depends(get_users),
    settings: Settings = Depends(get_app_settings),
) -> AccountResponse:
    """Sign in. A wrong password and an unknown address answer identically.

    Distinguishing them would tell an attacker which addresses are registered,
    which is a free list of targets for credential stuffing elsewhere.
    """
    email = normalise_email(body.email)
    found = users.password_hash_for(email)
    if found is None or not verify_password(body.password, found[1]):
        raise HTTPException(status_code=401, detail="Wrong email or password.")

    user_id, _ = found
    _set_session_cookie(response, user_id, settings)
    user = users.get(user_id)
    assert user is not None  # the row was just read
    return AccountResponse(id=user.id, email=user.email)


@router.post("/auth/logout", status_code=204, tags=["auth"])
def logout(response: Response) -> None:
    """Clear the cookie. Sessions are stateless, so this is the whole of it."""
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/auth/me", response_model=AccountResponse | None, tags=["auth"])
def me(
    user_id: str | None = Depends(current_user_id),
    users: UserRepository = Depends(get_users),
) -> AccountResponse | None:
    """Who is signed in. ``null`` for nobody, which is a normal answer here."""
    if user_id is None:
        return None
    user = users.get(user_id)
    if user is None:
        # A valid signature for a deleted account. Treat as signed out.
        return None
    return AccountResponse(id=user.id, email=user.email)


def _set_session_cookie(response: Response, user_id: str, settings: Settings) -> None:
    """HttpOnly so script cannot read it; Lax so a link from elsewhere still
    arrives signed in; Secure whenever the deployment is not plain local.

    A deployment with no configured secret answers 503 here rather than 500:
    the request is fine, the feature is not available, and saying which is the
    difference between a fixable deployment and a mysterious one.
    """
    try:
        token = issue_session(user_id, settings)
    except AuthError as unconfigured:
        raise HTTPException(status_code=503, detail=str(unconfigured)) from unconfigured

    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )
