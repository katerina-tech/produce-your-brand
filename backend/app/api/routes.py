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
from pydantic import ValidationError

from app.api.dto import (
    AccountResponse,
    BoroughCount,
    CapabilityClaimResponse,
    CapabilityMatchesResponse,
    CapabilityMatchRequest,
    CapabilityMatchResponse,
    CaptureQuoteRequest,
    CategoryCount,
    ComparisonRowResponse,
    ConfirmQuoteRequest,
    CreateProjectRequest,
    CredentialsRequest,
    FeedbackEntryResponse,
    FeedbackListResponse,
    FeedbackRequest,
    FeedbackResponse,
    FieldEvidenceResponse,
    FollowUpResponse,
    GeneratedDesignResponse,
    GenerateDesignRequest,
    HealthResponse,
    NearbyStudioResponse,
    NearbyStudiosResponse,
    OutreachResponse,
    PartnerDetailResponse,
    PartnerDirectoryResponse,
    PartnerResponse,
    ProjectListResponse,
    ProjectStateResponse,
    ProjectSummaryResponse,
    QuoteDeskResponse,
    QuoteResponse,
    ReadinessChecks,
    ResumeRequest,
    TenderBoardResponse,
    TenderFamilyCount,
    TenderResponse,
    UploadResponse,
    VerificationRequest,
)
from app.config import Settings, get_settings
from app.domain.enums import ProductionMethod
from app.domain.outreach import SAMPLE_ADDRESS_SUFFIX
from app.domain.partner import Partner
from app.domain.project import Project
from app.domain.quote import SupplierQuote
from app.domain.tender import Tender
from app.llm.factory import (
    ImageProvider,
    LLMProvider,
    get_embedding_provider,
    get_provider,
)
from app.logging_config import Event
from app.repositories.capability_repo import CapabilityRepository
from app.repositories.partner_repo import PartnerRepository
from app.repositories.supplier_repo import SupplierRepository
from app.repositories.tender_repo import TenderRepository
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
from app.services.capability_match import DEFAULT_CANDIDATES, CapabilityIndex, find_matches
from app.services.design_service import DesignGenerationError, generate_design
from app.services.osm_search import OSMSearchError, OverpassStudioSearch
from app.services.outreach import RFQNotApprovedError, render_email
from app.services.project_service import (
    DesignNotFoundError,
    ProjectService,
    ProjectView,
    StageMismatchError,
)
from app.services.quote_desk import NoRequestToAnswerError, QuoteDesk

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


def get_suppliers(request: Request) -> SupplierRepository | None:
    """The partner dataset, if it loaded. ``None`` rather than 503: everything
    that needs it here degrades to an empty address box, which is a worse
    experience and not a broken one."""
    repository: SupplierRepository | None = getattr(request.app.state, "supplier_repository", None)
    return repository


def get_partners(request: Request) -> PartnerRepository:
    """The real-company directory built at startup."""
    repository: PartnerRepository | None = getattr(request.app.state, "partner_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="The service is not ready.")
    return repository


def get_tenders(request: Request) -> TenderRepository:
    """The public-contract board built at startup."""
    repository: TenderRepository | None = getattr(request.app.state, "tender_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="The service is not ready.")
    return repository


def get_capabilities(request: Request) -> CapabilityRepository:
    """What has been read from the companies' own websites."""
    repository: CapabilityRepository | None = getattr(
        request.app.state, "capability_repository", None
    )
    if repository is None:
        raise HTTPException(status_code=503, detail="The service is not ready.")
    return repository


def get_quote_desk(request: Request) -> QuoteDesk:
    """The Quote Desk built at startup."""
    desk: QuoteDesk | None = getattr(request.app.state, "quote_desk", None)
    if desk is None:
        raise HTTPException(status_code=503, detail="The service is not ready.")
    return desk


def _visible_project(service: ProjectService, project_id: str, user_id: str | None) -> Project:
    """The project, or the 404 that a project you cannot see always gets."""
    guard_project(service, project_id, user_id)
    project = service.get_record(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="No such project.")
    return project


def _quote_response(quote: SupplierQuote) -> QuoteResponse:
    return QuoteResponse(
        id=quote.id,
        supplier_name=quote.supplier_name,
        feasible=quote.feasible,
        proposed_method=quote.proposed_method,
        unit_price_eur=quote.unit_price_eur,
        total_price_eur=quote.total_price_eur,
        setup_cost_eur=quote.setup_cost_eur,
        quoted_quantity=quote.quoted_quantity,
        price_basis=quote.price_basis,
        price_is_estimate=quote.price_is_estimate,
        currency=quote.currency,
        lead_time_days=quote.lead_time_days,
        sample_available=quote.sample_available,
        accepts_customer_owned_goods=quote.accepts_customer_owned_goods,
        open_questions=list(quote.open_questions),
        evidence=[
            FieldEvidenceResponse(field=item.field, quote=item.quote) for item in quote.evidence
        ],
        unverified_fields=list(quote.unverified_fields),
        corrected_fields=list(quote.corrected_fields),
        source_text=quote.source_text,
        received_on=quote.received_on.isoformat(),
        confirmed_by_human=quote.confirmed_by_human,
        needs_manual_entry=quote.nothing_was_read,
    )


def _desk_response(desk: QuoteDesk, project: Project) -> QuoteDeskResponse:
    comparison = desk.comparison(project)
    return QuoteDeskResponse(
        quotes=[_quote_response(quote) for quote in desk.quotes_for(project)],
        rows=[
            ComparisonRowResponse(
                quote_id=row.quote_id,
                supplier_name=row.supplier_name,
                comparable_total_eur=row.comparable_total_eur,
                total_basis=row.total_basis,
                lead_time_days=row.lead_time_days,
                answered_count=row.answered_count,
                unanswered=list(row.unanswered),
                blockers=list(row.blockers),
            )
            for row in comparison.rows
        ],
        requested_quantity=comparison.requested_quantity,
        cheapest_quote_id=comparison.cheapest_quote_id,
        fastest_quote_id=comparison.fastest_quote_id,
        unanswered_by_everyone=list(comparison.unanswered_by_everyone),
        note=comparison.note,
        followups=[
            FollowUpResponse(
                supplier_name=draft.supplier_name,
                subject=draft.subject,
                questions=list(draft.questions),
                asks=list(draft.asks),
            )
            for draft in desk.followups(project)
        ],
    )


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


def _database_dialect(request: Request) -> str:
    """Which database the running application actually opened.

    Read off the live connection rather than off the setting: a URL that is
    configured but unreachable would have the setting say postgres while every
    write went somewhere else entirely.
    """
    service: ProjectService | None = getattr(request.app.state, "project_service", None)
    dialect = getattr(getattr(service, "_projects", None), "_connection", None)
    return str(getattr(dialect, "dialect", "unknown"))


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
        database=_database_dialect(request),
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
    suppliers: SupplierRepository | None = Depends(get_suppliers),
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

    partner = suppliers.get(project.rfq.supplier_id) if suppliers else None
    try:
        email = render_email(project.rfq, to=partner.contact_email or "" if partner else "")
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
        address_is_sample=email.to.endswith(SAMPLE_ADDRESS_SUFFIX),
    )


def _partner_response(partner: Partner) -> PartnerResponse:
    """One directory entry on the wire. Written once, because the list and the
    detail view must never drift into disagreeing about the same company."""
    return PartnerResponse(
        id=partner.id,
        name=partner.name,
        address=partner.address,
        city=partner.city,
        district=partner.district,
        borough=partner.borough,
        category=partner.category,
        category_label=partner.category_label,
        summary=partner.summary,
        email_source=partner.email_source,
        website=partner.website,
        email=partner.email,
        phone=partner.phone,
        implied_method=partner.implied_method,
        lat=partner.lat,
        lon=partner.lon,
        verified=partner.verified,
    )


@router.get("/partners", response_model=PartnerDirectoryResponse, tags=["partners"])
def list_partners(
    q: str | None = None,
    method: ProductionMethod | None = None,
    borough: str | None = None,
    category: str | None = None,
    with_email: bool = False,
    limit: int = 200,
    partners: PartnerRepository = Depends(get_partners),
) -> PartnerDirectoryResponse:
    """Real Berlin businesses, as they published themselves.

    Not the matcher's dataset and never scored: these carry identity and contact
    details and nothing about materials, minimum orders or lead times, because
    the source does not know those and this product does not invent them.
    """
    directory = partners.directory()
    found = partners.search(
        query=q,
        method=method,
        borough=borough,
        category=category,
        with_email=with_email,
        limit=limit,
    )

    return PartnerDirectoryResponse(
        partners=[_partner_response(partner) for partner in found],
        # The whole list every time, not only the boroughs surviving the current
        # filter: a filter that removes its own options is one you cannot get
        # back out of without knowing to clear it.
        boroughs=[BoroughCount(name=name, count=count) for name, count in partners.boroughs()],
        categories=[
            CategoryCount(tag=tag, label=label, count=count)
            for tag, label, count in partners.categories()
        ],
        total=partners.count(),
        contactable=partners.contactable_count(),
        shown=len(found),
        attribution=directory.attribution,
        area=directory.area,
        incomplete_categories=list(directory.incomplete_categories),
    )


def _capability_index(request: Request) -> CapabilityIndex:
    """The claim index, built on first use and kept.

    Not built at startup on purpose. Embedding every company costs a model call
    per boot, and a deployment restarts for reasons that have nothing to do with
    anybody searching. Built when somebody actually asks, kept afterwards, and
    rebuilt by a restart - which is also how a fresh extraction becomes visible.
    """
    existing: CapabilityIndex | None = getattr(request.app.state, "capability_index", None)
    if existing is not None:
        return existing

    index = CapabilityIndex(get_embedding_provider(get_settings()))
    index.build(get_capabilities(request).all())
    request.app.state.capability_index = index
    return index


@router.post("/partners/match", response_model=CapabilityMatchesResponse, tags=["partners"])
def match_partners(
    payload: CapabilityMatchRequest,
    request: Request,
    capabilities: CapabilityRepository = Depends(get_capabilities),
) -> CapabilityMatchesResponse:
    """Which companies can do this, by their own words.

    Retrieval over what the companies wrote about themselves, then a model
    check on each candidate that must quote the company's claim, then a literal
    verifier that deletes any quote the company did not make. Nothing here
    scores or ranks a company on a model's judgement: the order is retrieval
    similarity, and the reason a buyer reads is the company's own sentence.
    """
    return _matches_for(request, capabilities, payload.requirement, limit=payload.limit)


def _matches_for(
    request: Request,
    capabilities: CapabilityRepository,
    requirement: str,
    *,
    limit: int = DEFAULT_CANDIDATES,
) -> CapabilityMatchesResponse:
    """Retrieve, verify, answer. Shared by the directory search and the tender
    board, because "who can do this" is the same question whether the words
    came from a buyer's box or from a government's notice."""
    indexed = capabilities.with_claims_count()
    if indexed == 0:
        return CapabilityMatchesResponse(
            matches=[],
            companies_indexed=0,
            note=(
                "No company websites have been read yet, so there is nothing to search. "
                "Run scripts/extract_capabilities.py to build this."
            ),
        )

    index = _capability_index(request)
    if index.size == 0:
        return CapabilityMatchesResponse(
            matches=[],
            companies_indexed=indexed,
            note=(
                "The claims could not be embedded, so retrieval is unavailable. "
                "The directory and the deterministic matcher are unaffected."
            ),
        )

    # Verification degrades to "unclear" without a model rather than failing the
    # request - but a provider that cannot even be built is a configuration
    # fault, and swallowing it silently would show every company as unclear with
    # nothing anywhere saying why.
    provider: LLMProvider | None
    try:
        provider = get_provider(get_settings())
    except Exception:
        logger.exception(
            "capability verification has no model provider",
            extra={"event": Event.LLM_ERROR.value},
        )
        provider = None

    found = find_matches(requirement, index, provider, limit=limit)
    supported = sum(1 for match in found if match.is_supported)

    return CapabilityMatchesResponse(
        matches=[
            CapabilityMatchResponse(
                partner_id=match.candidate.partner_id,
                partner_name=match.candidate.partner_name,
                similarity=match.candidate.similarity,
                can_do_it=match.can_do_it,
                reason=match.reason,
                quote=match.quote,
                quote_verified=match.quote_verified,
                supported=match.is_supported,
            )
            for match in found
        ],
        companies_indexed=index.size,
        note=(
            ""
            if supported
            else "Nothing here plainly covers the request. These are the companies worth asking."
        ),
    )


# The id is an OpenStreetMap reference - "node/6532305050" - and the slash in
# it is why these two read as they do. A plain path parameter stops at a slash,
# so the id needs the greedy converter, and a greedy converter has to be the
# last thing in the path or it swallows whatever follows. Rewriting 135 ids in
# a live database to make a URL prettier would be the wrong trade.
@router.get(
    "/partners/detail/{partner_id:path}", response_model=PartnerDetailResponse, tags=["partners"]
)
def get_partner(
    partner_id: str,
    partners: PartnerRepository = Depends(get_partners),
    capabilities: CapabilityRepository = Depends(get_capabilities),
) -> PartnerDetailResponse:
    """One company, and what its own website says it does."""
    partner = partners.get(partner_id)
    if partner is None:
        raise HTTPException(status_code=404, detail="No such company.")

    reading = capabilities.get(partner_id)
    response = PartnerDetailResponse(partner=_partner_response(partner))
    if reading is None:
        response.reading_note = "This company's website has not been read yet."
        return response

    record = reading.capabilities
    response.claims = [
        CapabilityClaimResponse(
            text=claim.text, quote=claim.quote, kind=claim.kind, method=claim.method
        )
        for claim in record.claims
    ]
    response.source_urls = list(record.source_urls)
    response.extracted_on = record.extracted_on.isoformat()
    response.dropped_count = record.dropped_count
    response.reading_note = reading.explanation
    return response


@router.post(
    "/partners/verification/{partner_id:path}", response_model=PartnerResponse, tags=["partners"]
)
def set_partner_verification(
    partner_id: str,
    payload: VerificationRequest,
    request: Request,
    partners: PartnerRepository = Depends(get_partners),
) -> PartnerResponse:
    """Record that a person checked this reading and stands behind it.

    The one fact in the directory that no amount of scraping can produce. A
    model read the page and a verifier checked the quotes; neither of those is
    somebody saying "yes, this is what they do".
    """
    if not partners.mark_verified(partner_id, payload.verified):
        raise HTTPException(status_code=404, detail="No such company.")

    partner = partners.get(partner_id)
    if partner is None:  # pragma: no cover - it existed one statement ago
        raise HTTPException(status_code=404, detail="No such company.")

    # A confirmation changes what the index should hold, and the index is a
    # cache. Dropping it is cheaper and more honest than patching it in place.
    request.app.state.capability_index = None
    return _partner_response(partner)


ATTRIBUTION = (
    "Bekanntmachungsservice / Datenservice Öffentlicher Einkauf (Beschaffungsamt des BMI), "
    "released as open data under CC0 1.0. Reproduced, not endorsed."
)


def _tender_response(tender: Tender) -> TenderResponse:
    """One notice on the wire. Written once, so the board and the detail view
    cannot drift into disagreeing about the same contract."""
    return TenderResponse(
        id=tender.id,
        title=tender.title,
        description=tender.description,
        cpv=tender.cpv,
        family_prefix=tender.family_prefix,
        family_label=tender.family_label,
        implied_method=tender.implied_method,
        buyer=tender.buyer,
        buyer_city=tender.buyer_city,
        place_city=tender.place_city,
        place_region=tender.place_region,
        in_berlin=tender.is_berlin,
        estimated_value=tender.estimated_value,
        currency=tender.currency,
        published_on=tender.published_on.isoformat(),
        deadline=tender.deadline.isoformat() if tender.deadline else None,
        suitable_for_smes=tender.suitable_for_smes,
        procedure_type=tender.procedure_type,
        notice_type=tender.notice_type,
        source_url=tender.source_url,
    )


@router.get("/tenders", response_model=TenderBoardResponse, tags=["tenders"])
def list_tenders(
    q: str | None = None,
    family: str | None = None,
    berlin: bool = False,
    smes: bool = False,
    include_closed: bool = False,
    limit: int = 100,
    tenders: TenderRepository = Depends(get_tenders),
) -> TenderBoardResponse:
    """German public contracts for printing, textiles and engraving.

    Open ones first and soonest deadline first, because a board of closed
    tenders is a board nobody can use. The data is CC0 open data from the
    federal Bekanntmachungsservice - reproduced here with its attribution
    travelling in the response rather than remembered by a reader.
    """
    found = tenders.search(
        query=q,
        family=family,
        berlin_only=berlin,
        smes_only=smes,
        open_only=not include_closed,
        limit=limit,
    )
    return TenderBoardResponse(
        tenders=[_tender_response(tender) for tender in found],
        # The whole list every time, not only the families surviving the
        # current filter: a filter that removes its own options is one you
        # cannot get back out of.
        families=[
            TenderFamilyCount(prefix=prefix, label=label, count=count)
            for prefix, label, count in tenders.families()
        ],
        total=tenders.count(),
        berlin=tenders.berlin_count(),
        shown=len(found),
        attribution=ATTRIBUTION,
        imported_at=tenders.latest_import(),
    )


@router.get("/tenders/detail/{tender_id}", response_model=TenderResponse, tags=["tenders"])
def get_tender(tender_id: str, tenders: TenderRepository = Depends(get_tenders)) -> TenderResponse:
    """One notice. The id is a UUID, so this one needs no path converter."""
    tender = tenders.get(tender_id)
    if tender is None:
        raise HTTPException(status_code=404, detail="No such tender.")
    return _tender_response(tender)


@router.post(
    "/tenders/detail/{tender_id}/matches",
    response_model=CapabilityMatchesResponse,
    tags=["tenders"],
)
def match_tender(
    tender_id: str,
    request: Request,
    tenders: TenderRepository = Depends(get_tenders),
    capabilities: CapabilityRepository = Depends(get_capabilities),
) -> CapabilityMatchesResponse:
    """Which companies in the directory say they can do this contract.

    The thing a tender aggregator cannot do and this one can: the other side of
    the market is already here. Retrieval over what the companies wrote about
    themselves, then a model that must quote the company's own claim, then the
    same literal verifier that deletes any quote they did not make.

    The buyer's own title and description are the query. Nothing here rewrites
    the tender into what this product would rather it said.
    """
    tender = tenders.get(tender_id)
    if tender is None:
        raise HTTPException(status_code=404, detail="No such tender.")
    return _matches_for(request, capabilities, tender.searchable_text)


@router.get("/projects/{project_id}/quotes", response_model=QuoteDeskResponse, tags=["quotes"])
def list_quotes(
    project_id: str,
    service: ProjectService = Depends(get_service),
    desk: QuoteDesk = Depends(get_quote_desk),
    user_id: str | None = Depends(current_user_id),
) -> QuoteDeskResponse:
    """Everything the quote screen renders, in one read."""
    project = _visible_project(service, project_id, user_id)
    return _desk_response(desk, project)


@router.post(
    "/projects/{project_id}/quotes",
    response_model=QuoteDeskResponse,
    status_code=201,
    tags=["quotes"],
)
def capture_reply(
    project_id: str,
    body: CaptureQuoteRequest,
    service: ProjectService = Depends(get_service),
    desk: QuoteDesk = Depends(get_quote_desk),
    user_id: str | None = Depends(current_user_id),
) -> QuoteDeskResponse:
    """Read one pasted supplier reply into a stored quote.

    201 even when nothing could be read. A blocked or unreadable reply is still
    captured, with every figure absent and the text kept, because the buyer
    needs to see that it arrived and type the numbers themselves - losing it
    would be the worse answer.
    """
    project = _visible_project(service, project_id, user_id)
    try:
        desk.capture(project, body.reply_text)
    except NoRequestToAnswerError as missing:
        raise HTTPException(
            status_code=409,
            detail="Approve a quotation request before capturing a reply to it.",
        ) from missing
    return _desk_response(desk, project)


@router.post(
    "/projects/{project_id}/quotes/{quote_id}/confirm",
    response_model=QuoteDeskResponse,
    tags=["quotes"],
)
def confirm_quote(
    project_id: str,
    quote_id: str,
    body: ConfirmQuoteRequest,
    service: ProjectService = Depends(get_service),
    desk: QuoteDesk = Depends(get_quote_desk),
    user_id: str | None = Depends(current_user_id),
) -> QuoteDeskResponse:
    """Apply a human's corrections and mark the reply checked.

    ``confirmed_by_human`` is set server-side and is not a field of the request:
    a client that could set it could claim a figure was checked when nobody
    looked at it.
    """
    project = _visible_project(service, project_id, user_id)
    corrections = body.model_dump(exclude_none=True)
    try:
        updated = desk.confirm(quote_id, corrections)
    except ValidationError as invalid:
        # A correction can contradict a rule - a sample cost with no sample.
        raise HTTPException(status_code=422, detail=str(invalid.errors()[0]["msg"])) from invalid
    if updated is None or updated.project_id != project.id:
        raise HTTPException(status_code=404, detail="No such quote.")
    return _desk_response(desk, project)


@router.delete(
    "/projects/{project_id}/quotes/{quote_id}",
    response_model=QuoteDeskResponse,
    tags=["quotes"],
)
def delete_quote(
    project_id: str,
    quote_id: str,
    service: ProjectService = Depends(get_service),
    desk: QuoteDesk = Depends(get_quote_desk),
    user_id: str | None = Depends(current_user_id),
) -> QuoteDeskResponse:
    """Remove a captured reply - pasted into the wrong project, most likely,
    and then it is somebody else's correspondence sitting where it should not."""
    project = _visible_project(service, project_id, user_id)
    existing = desk.quotes_for(project)
    if not any(quote.id == quote_id for quote in existing):
        raise HTTPException(status_code=404, detail="No such quote.")
    desk.remove(quote_id)
    return _desk_response(desk, project)


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
