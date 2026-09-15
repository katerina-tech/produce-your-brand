"""HTTP boundary models.

Kept separate from :mod:`app.domain` on purpose: domain models may evolve for
business reasons, while these are a wire contract the frontend depends on.
``frontend/lib/types.ts`` mirrors this module.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import PriceBasis, ProductionMethod, Stage


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
    sign_in_configured: bool = False
    database: str = Field(
        default="sqlite",
        description=(
            "Which database this deployment is actually using. Reported because "
            "'it looks like it worked' is not the same as knowing, and after a "
            "migration the difference between postgres and a file on a volume is "
            "the difference between keeping data and losing it."
        ),
    )


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
    "restart_request",
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
    raw_request: str | None = Field(default=None, min_length=10, max_length=8000)
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
    product: str | None = Field(
        default=None, description="Product name, so the client can title the project."
    )
    design_upload_id: str | None = Field(
        default=None, description="Id of an attached design, if one was uploaded or generated."
    )
    payload: dict[str, Any] | None = None
    expected_action: str | None = None
    errors: list[str] = []
    is_complete: bool = False
    mine: bool = Field(
        default=False,
        description=(
            "Whether this project belongs to the caller. False means unowned, "
            "never somebody else's - a project with a different owner is a 404 "
            "here, so there is no third case for a client to handle."
        ),
    )


class ProjectSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    stage: Stage
    product: str | None
    quantity: int | None
    updated_at: str
    mine: bool = False


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


class GenerateDesignRequest(BaseModel):
    """A text description of the design the customer wants generated."""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(
        min_length=3,
        max_length=500,
        description="What to generate, e.g. 'a minimalist gold star logo on a plain background'.",
    )


class GeneratedDesignResponse(UploadResponse):
    """An :class:`UploadResponse` plus a one-time preview of what was generated.

    ``preview_data_url`` is the deliberate, narrow exception to "the file body is
    never returned": for an upload, the browser already holds the bytes the user
    picked and can preview them locally, but a generated image exists only on
    the server until this response - the one moment the user can see what they
    just paid to generate. It is not persisted here and no other endpoint
    (including a later fetch of the same project) returns it again.
    """

    model_config = ConfigDict(extra="forbid")

    preview_data_url: str


class NearbyStudioResponse(BaseModel):
    """One unverified OpenStreetMap lead. See app/services/osm_search.py."""

    model_config = ConfigDict(extra="forbid")

    osm_id: str
    name: str
    osm_category: str
    address: str | None
    website: str | None
    phone: str | None
    # Volunteered by the business to OpenStreetMap, alongside the phone number
    # already here. Passed through at the moment of the query and stored no
    # more than the phone number is.
    email: str | None
    lat: float
    lon: float


class NearbyStudiosResponse(BaseModel):
    """Deliberately separate from :class:`ProjectStateResponse` - these are not
    supplier matches and are never scored, so they do not belong in the same
    envelope as ``matches``."""

    model_config = ConfigDict(extra="forbid")

    studios: list[NearbyStudioResponse]
    source: Literal["openstreetmap"] = "openstreetmap"
    note: str = (
        "Unverified leads from OpenStreetMap, not scored or vetted. "
        "Contact them yourself to confirm they can do this job."
    )


# ------------------------------------------------------ product validation
# The instrumentation the first customer-discovery interview asked for - see
# the README's Product hypothesis section. Not gated to one workflow stage:
# the frontend decides when it makes sense to ask.

FoundUseful = Literal["yes", "partly", "no"]
AlternativeApproach = Literal["google", "chatgpt", "existing_platform", "known_supplier", "other"]


class FeedbackRequest(BaseModel):
    """A user's answer to "did this actually help?" - the evidence this
    product exists to gather, not a feature it happens to have."""

    model_config = ConfigDict(extra="forbid")

    found_useful: FoundUseful
    would_contact_supplier: bool
    alternative_approach: AlternativeApproach
    missing: str | None = Field(default=None, max_length=1000)


class OutreachResponse(BaseModel):
    """The approved quotation request, as an email the user can open and send.

    Carries links rather than a send button, because this system does not send.
    The buyer remains the sender - which is what keeps supplier contact data out
    of this product entirely and keeps a platform from being the one making
    unsolicited contact.
    """

    model_config = ConfigDict(extra="forbid")

    supplier_name: str
    to: str = Field(default="", description="Empty: no supplier addresses are stored.")
    subject: str
    body: str
    gmail_url: str = Field(description="Opens a pre-filled Gmail compose window.")
    mailto_url: str = Field(description="The same message in the local mail client.")
    fits_in_a_url: bool = Field(
        description="False when the body is too long for a link to carry intact; "
        "the client should offer copying instead of a truncated draft."
    )
    address_is_sample: bool = Field(
        default=False,
        description="True when the address belongs to a sample partner and "
        "cannot receive mail. The client must say so rather than let somebody "
        "believe they have written to a real company.",
    )


class CaptureQuoteRequest(BaseModel):
    """A supplier's reply, pasted by the buyer who received it."""

    model_config = ConfigDict(extra="forbid")

    reply_text: str = Field(
        min_length=1,
        max_length=20_000,
        description="The reply as received. Screened before anything reads it.",
    )


class ConfirmQuoteRequest(BaseModel):
    """Corrections a human typed at the confirm gate.

    Only the fields a person can reasonably re-read off the letter. Identity,
    provenance and ``confirmed_by_human`` are deliberately absent: a request
    that could set them could claim a figure was human-checked when it was not.
    """

    model_config = ConfigDict(extra="forbid")

    unit_price_eur: float | None = Field(default=None, ge=0)
    total_price_eur: float | None = Field(default=None, ge=0)
    setup_cost_eur: float | None = Field(default=None, ge=0)
    quoted_quantity: int | None = Field(default=None, ge=0)
    lead_time_days: int | None = Field(default=None, ge=0)
    price_basis: PriceBasis | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    feasible: bool | None = None


class FieldEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    quote: str


class QuoteResponse(BaseModel):
    """One captured reply, with the words each figure was read from."""

    model_config = ConfigDict(extra="forbid")

    id: str
    supplier_name: str
    feasible: bool | None
    proposed_method: ProductionMethod | None
    unit_price_eur: float | None
    total_price_eur: float | None
    setup_cost_eur: float | None
    quoted_quantity: int | None
    price_basis: PriceBasis
    price_is_estimate: bool | None
    currency: str | None
    lead_time_days: int | None
    sample_available: bool | None
    accepts_customer_owned_goods: bool | None
    open_questions: list[str] = []
    evidence: list[FieldEvidenceResponse] = []
    unverified_fields: list[str] = Field(
        default=[],
        description="Figures the verifier deleted because their span was not in the text.",
    )
    corrected_fields: list[str] = []
    source_text: str
    received_on: str
    confirmed_by_human: bool
    needs_manual_entry: bool = Field(
        default=False,
        description="Nothing could be read, so the buyer has to type the figures.",
    )


class ComparisonRowResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote_id: str
    supplier_name: str
    comparable_total_eur: float | None
    total_basis: PriceBasis
    lead_time_days: int | None
    answered_count: int
    unanswered: list[str] = []
    blockers: list[str] = []


class FollowUpResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_name: str
    subject: str
    questions: list[str] = []
    asks: list[str] = []


class QuoteDeskResponse(BaseModel):
    """Everything the quote screen renders, in one read."""

    model_config = ConfigDict(extra="forbid")

    quotes: list[QuoteResponse] = []
    rows: list[ComparisonRowResponse] = []
    requested_quantity: int | None = None
    cheapest_quote_id: str | None = None
    fastest_quote_id: str | None = None
    unanswered_by_everyone: list[str] = []
    note: str = ""
    followups: list[FollowUpResponse] = []


class PartnerResponse(BaseModel):
    """One real business from the directory.

    Deliberately carries no capability field. A Partner is a company that
    exists; a Supplier is one somebody established facts about, and keeping the
    wire shapes as different as the domain types stops a directory entry from
    drifting into the matcher.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    address: str | None
    city: str
    district: str | None = Field(
        default=None,
        description="The Ortsteil - what a person says when they mean 'near me'.",
    )
    borough: str | None = Field(
        default=None,
        description=(
            "One of Berlin's twelve Bezirke, or null for the few businesses just "
            "outside the city. The filter reads this; the screen shows the district."
        ),
    )
    category: str | None = Field(
        default=None, description="The source tag, e.g. 'craft=printer'. What the filter reads."
    )
    category_label: str | None = Field(
        default=None, description="What that tag is called - Druckerei, Copyshop, Stickerei."
    )
    summary: str | None = Field(
        default=None,
        description=(
            "The company's own one-line description of itself, from its site. Never a "
            "model's paraphrase - their line, or nothing."
        ),
    )
    email_source: str | None = Field(
        default=None,
        description=(
            "'openstreetmap' or 'website'. Shown because the two are not equally "
            "likely to still be watched."
        ),
    )
    website: str | None
    email: str | None
    phone: str | None
    implied_method: ProductionMethod | None = Field(
        default=None,
        description="What the source category suggests, not what the business confirmed.",
    )
    lat: float | None = None
    lon: float | None = None
    verified: bool = False


class BoroughCount(BaseModel):
    """One Bezirk and how many businesses are in it.

    Counted from the data rather than listed from a constant: offering a filter
    for a borough with nothing behind it answers "nothing here" to a question
    the directory never had.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    count: int


class CategoryCount(BaseModel):
    """One kind of business, and how many there are.

    The tag travels beside the label so a filter's claim stays checkable
    against the public map the label came from.
    """

    model_config = ConfigDict(extra="forbid")

    tag: str
    label: str
    count: int


class PartnerDirectoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    partners: list[PartnerResponse] = []
    boroughs: list[BoroughCount] = Field(
        default=[], description="Every Bezirk with businesses, most first."
    )
    categories: list[CategoryCount] = Field(
        default=[], description="Every kind of business present, most first."
    )
    total: int = Field(description="Businesses in the whole directory, before filtering.")
    contactable: int = Field(description="How many of the total publish an email address.")
    shown: int = Field(description="How many matched the current filters.")
    attribution: str = ""
    area: str = ""
    incomplete_categories: list[str] = Field(
        default=[],
        description=(
            "Source categories missing from this build entirely. Reported so an "
            "absence is not read as a finding."
        ),
    )


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["recorded"] = "recorded"


class FeedbackEntryResponse(BaseModel):
    """One stored response. Mirrors app.domain.project.FeedbackEntry."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    found_useful: str
    would_contact_supplier: bool
    alternative_approach: str
    missing: str | None
    created_at: str


class FeedbackListResponse(BaseModel):
    """The internal read this data is for - a flat list, not a dashboard.
    There is no aggregate claim to make with only a handful of responses."""

    model_config = ConfigDict(extra="forbid")

    entries: list[FeedbackEntryResponse]


class CredentialsRequest(BaseModel):
    """Sign-in and registration take the same two fields."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


class AccountResponse(BaseModel):
    """What the client is told about the signed-in account.

    The password hash is not here, and there is nothing else on a user record
    that could leak - the model holds an id, an address and a date.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    email: str


class CapabilityClaimResponse(BaseModel):
    """One thing a company said it can do, with the words it said it in.

    The quote is not decoration. It is the difference between "this product
    believes they do screen printing" and "their own page says so, here" - and
    it is what a person reads before confirming the reading is right.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    quote: str
    kind: str
    method: ProductionMethod | None = None


class PartnerDetailResponse(BaseModel):
    """One company, plus whatever was read from its website."""

    model_config = ConfigDict(extra="forbid")

    partner: PartnerResponse
    claims: list[CapabilityClaimResponse] = []
    source_urls: list[str] = []
    extracted_on: str | None = Field(
        default=None, description="None when nobody has read this company's site yet."
    )
    dropped_count: int = Field(
        default=0,
        description=(
            "Claims the verifier deleted because their words were not on the page. "
            "Shown rather than hidden: a reading that dropped half of what the model "
            "proposed is a reading worth a closer look."
        ),
    )
    reading_note: str = Field(
        default="",
        description="Why this company has no claims, when it has none. Empty otherwise.",
    )


class VerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verified: bool = True


class CapabilityMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement: str = Field(min_length=3, max_length=2000)
    limit: int = Field(default=8, ge=1, le=25)


class CapabilityMatchResponse(BaseModel):
    """One company retrieval found and a model then checked.

    ``can_do_it`` is deliberately three-valued. Null is the honest answer more
    often than either of the others, and collapsing it into false would throw
    away the list of companies worth a phone call.
    """

    model_config = ConfigDict(extra="forbid")

    partner_id: str
    partner_name: str
    similarity: float
    can_do_it: bool | None = None
    reason: str = ""
    quote: str = ""
    quote_verified: bool = False
    supported: bool = False


class CapabilityMatchesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matches: list[CapabilityMatchResponse] = []
    companies_indexed: int = Field(
        description="Companies whose claims were searched. Zero means nothing has been read yet."
    )
    note: str = Field(
        default="",
        description="Why the result is empty or thin, in words. Empty when it is neither.",
    )
