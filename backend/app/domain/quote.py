"""Supplier quotes - what came back, read strictly, compared honestly.

The product could tell a buyer who *could* make a thing. It stopped there: the
reply the supplier sent was a dead end, and turning "Machbar, aber bei 100 Stück
kommen wir auf 14 Tage, ca. 8,50/Stück netto" into something comparable was work
the buyer still did in a spreadsheet. This module is the other half of the loop
the customer-discovery interview asked for - not a better search, an answer you
can act on.

**The platform never sends anything.** Quotes arrive because a buyer pastes a
reply they already received, in correspondence they already own. That is not a
limitation waiting to be lifted; it is the design. A platform that mails German
businesses is a platform arguing about UWG §7 and GDPR Art. 14, and the value
here was never in the transport - it is in reading the answer correctly. An
audit rule holds outbound transport libraries at zero so this stays true by
construction rather than by intention.

**No contact data, deliberately.** There is no field on any model here that an
email address, a phone number or a name out of a signature could be written
into. ``suppliers.json`` holds name, city, ISO country and website and nothing
else. Holding a publicly-collected contact person is precisely what would make
this a controller with an Art. 14 notification duty, so the MVP holds none. If
one is ever added, it must carry four fields from its first day:
``collected_from``, ``collected_on``, ``lawful_basis``, ``art14_notice_sent_on``.

**Every figure must quote its source.** The model reads language and nothing
else; it may not produce a number without the verbatim words it read that number
from, and :mod:`app.services.quote_verification` - pure Python, no AI import -
deletes any figure whose span is not literally present in the text. An invented
price is not discouraged here, it is unstorable. That is the same division the
scorer rests on, applied to extraction.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import PriceBasis, ProductionMethod

# Answer fields the model is allowed to read out of a reply. Named here because
# three separate rules need the same list: the evidence validator, the verifier,
# and the test that proves a corrected field is exempt.
NUMERIC_ANSWER_FIELDS: tuple[str, ...] = (
    "unit_price_eur",
    "total_price_eur",
    "setup_cost_eur",
    "sample_cost_eur",
    "quoted_quantity",
    "lead_time_days",
)


class FieldEvidence(BaseModel):
    """The words a single extracted value was read from.

    One small model rather than a parallel tree of typed figures: the guarantee
    wanted is not "this number has a rich type", it is "this number can be
    pointed at in the supplier's own sentence".
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str = Field(description="Name of the SupplierQuote answer field this span supports.")
    quote: str = Field(
        min_length=1,
        description="Verbatim substring of the screened reply. Checked literally, not fuzzily.",
    )


class SupplierQuote(BaseModel):
    """One supplier's answer to one request for quotation.

    Not frozen: a human corrects fields at the confirm gate, the way MatchResult
    is not frozen. Every answer field is ``T | None`` because a reply that is
    silent about price is ordinary, and silence must never arrive as a zero.
    """

    model_config = ConfigDict(extra="forbid")

    # ---- identity, always set by code ----
    id: str
    project_id: str
    supplier_id: str
    supplier_name: str

    # ---- what the supplier answered ----
    feasible: bool | None = Field(
        default=None,
        description=(
            "True only from an explicit statement that it can be done. A warm reply that "
            "never says so is None - unclear is not declined."
        ),
    )
    proposed_method: ProductionMethod | None = Field(
        default=None, description="A method the supplier proposed instead of the one asked about."
    )
    method_deviation_note: str | None = Field(
        default=None, description="Their own words about why, kept verbatim."
    )

    unit_price_eur: float | None = Field(default=None, ge=0)
    total_price_eur: float | None = Field(default=None, ge=0)
    setup_cost_eur: float | None = Field(default=None, ge=0)
    sample_cost_eur: float | None = Field(default=None, ge=0)
    quoted_quantity: int | None = Field(
        default=None, ge=0, description="The quantity their price refers to, if stated."
    )
    price_basis: PriceBasis = Field(
        default=PriceBasis.UNSTATED,
        description="Net, gross, or - most often - not stated at all.",
    )
    price_is_estimate: bool | None = Field(
        default=None, description="True when hedged: 'ca.', 'circa', 'etwa', 'around'."
    )
    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        description=(
            "ISO 4217, only if stated or unambiguous. None is a comparison blocker - a "
            "figure whose currency was assumed is never totalled."
        ),
    )
    lead_time_days: int | None = Field(default=None, ge=0)
    lead_time_basis: str | None = Field(
        default=None, description="What the clock starts from, in their words."
    )
    sample_available: bool | None = None
    accepts_customer_owned_goods: bool | None = None
    open_questions: tuple[str, ...] = Field(
        default=(), description="Questions they asked back. Prose; enters no calculation."
    )
    unanswered_indices: tuple[int, ...] = Field(
        default=(),
        description=(
            "Indices into the RFQ's confirmations_requested that this reply did not answer. "
            "A question leaves this tuple only on verified evidence, never on model silence."
        ),
    )

    # ---- provenance, mirroring Offer ----
    evidence: tuple[FieldEvidence, ...] = ()
    unverified_fields: tuple[str, ...] = Field(
        default=(),
        description=(
            "Fields the verifier dropped because their span was not in the text, so the "
            "interface can say a figure was discarded rather than show a silent blank."
        ),
    )
    corrected_fields: tuple[str, ...] = Field(
        default=(),
        description=(
            "Fields a human typed or edited. Provenance is per field, not per record: "
            "correcting a lead time must not quietly relabel the price as human-checked, "
            "and a corrected field is exempt from needing a source span."
        ),
    )
    source_text: str = Field(description="The reply as screened, which is what the model saw.")
    source_language: str | None = None
    received_on: date = Field(description="Passed in by the caller; never date.today() in here.")
    is_demo: bool = Field(
        default=True,
        description="Seeded sample rather than a real reply. Defaults True, like TrackRecord.",
    )
    confirmed_by_human: bool = Field(
        default=False,
        description="Set only server-side, at the confirm gate. Never accepted from a request.",
    )

    # ------------------------------------------------------------- validators

    @model_validator(mode="after")
    def _a_total_price_must_say_what_quantity_it_is_for(self) -> SupplierQuote:
        """A total with no quantity cannot be compared with anything.

        It also cannot be corrected later without asking the supplier again, so
        it is better refused now than stored as a number that looks usable.
        """
        if self.total_price_eur is not None and self.quoted_quantity is None:
            raise ValueError("a total price must state what quantity it is for")
        return self

    @model_validator(mode="after")
    def _demo_quotes_cannot_be_human_confirmed(self) -> SupplierQuote:
        """Verbatim mirror of Offer's rule: a seeded record is not a fact about
        a real supplier, so it cannot also carry a human's confirmation."""
        if self.is_demo and self.confirmed_by_human:
            raise ValueError("a demo quote cannot also be human-confirmed")
        return self

    @model_validator(mode="after")
    def _a_sample_cost_implies_a_sample(self) -> SupplierQuote:
        """The mirror of TrackRecord's completion-date rule: a price for a thing
        that is not on offer is a contradiction the interface would have to
        explain away."""
        if self.sample_cost_eur is not None and self.sample_available is False:
            raise ValueError("a sample cost implies a sample is available")
        return self

    @model_validator(mode="after")
    def _a_figure_needs_the_words_it_came_from(self) -> SupplierQuote:
        """The invariant the whole module rests on.

        Any numeric answer the model produced must carry a span. Fields a human
        typed are exempt - a person may know a figure the letter does not state
        - which is exactly why provenance is tracked per field rather than once
        per record.
        """
        supported = {evidence.field for evidence in self.evidence}
        missing = [
            name
            for name in NUMERIC_ANSWER_FIELDS
            if getattr(self, name) is not None
            and name not in supported
            and name not in self.corrected_fields
        ]
        if missing:
            raise ValueError(f"an extracted figure needs the words it came from: {sorted(missing)}")
        return self

    @model_validator(mode="after")
    def _evidence_may_only_name_real_answer_fields(self) -> SupplierQuote:
        """A span attached to a field that does not exist would silently satisfy
        nothing and confuse everything downstream."""
        unknown = sorted(
            {evidence.field for evidence in self.evidence} - set(type(self).model_fields)
        )
        if unknown:
            raise ValueError(f"evidence names unknown fields: {unknown}")
        return self

    # --------------------------------------------------------------- display

    @property
    def has_price(self) -> bool:
        """A price exists *and* its basis is known.

        A figure whose net/gross status is unknown is not a price anyone can
        quote back to a client, so it does not count as one here.
        """
        return (
            self.unit_price_eur is not None or self.total_price_eur is not None
        ) and self.price_basis is not PriceBasis.UNSTATED

    @property
    def is_empty(self) -> bool:
        """Nothing usable was readable from the reply."""
        return (
            self.feasible is None
            and self.unit_price_eur is None
            and self.total_price_eur is None
            and self.lead_time_days is None
        )

    def summary(self) -> str:
        """One line, arithmetic-free. Never a zero, never a total it computed."""
        if self.is_empty:
            return "Nothing readable in this reply"

        parts: list[str] = []
        if self.unit_price_eur is not None:
            piece = f"{self.currency or 'EUR'} {self.unit_price_eur:.2f}/unit"
            if self.price_basis is not PriceBasis.UNSTATED:
                piece += f" {self.price_basis.value}"
            if self.price_is_estimate:
                piece += " (estimate)"
            if self.quoted_quantity is not None:
                piece += f" at {self.quoted_quantity} units"
            parts.append(piece)
        elif self.total_price_eur is not None:
            parts.append(f"{self.currency or 'EUR'} {self.total_price_eur:.2f} total")
        else:
            parts.append("Price not stated")

        if self.lead_time_days is not None:
            parts.append(f"{self.lead_time_days} days")

        return " · ".join(parts)


class ComparisonRow(BaseModel):
    """One supplier's line in the comparison - comparable, or explained."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    quote_id: str
    supplier_name: str
    comparable_total_eur: float | None = Field(default=None, ge=0)
    total_basis: PriceBasis = PriceBasis.UNSTATED
    lead_time_days: int | None = Field(default=None, ge=0)
    answered_count: int = Field(default=0, ge=0)
    unanswered: tuple[str, ...] = ()
    blockers: tuple[str, ...] = Field(
        default=(),
        description=(
            "Why this row carries no comparable total: 'price basis not stated', "
            "'quoted for 50 units, you asked for 100', 'currency is CHF'."
        ),
    )

    @model_validator(mode="after")
    def _a_total_is_either_computed_or_explained(self) -> ComparisonRow:
        """No silent blanks in a money column.

        Either the row has a total, or it says why it does not. A blank cell
        with no reason is the one outcome that would let a buyer assume the
        supplier was expensive when in fact nobody knew.
        """
        if self.comparable_total_eur is None and not self.blockers:
            raise ValueError("a row without a comparable total must say why")
        if self.comparable_total_eur is not None and self.blockers:
            raise ValueError("a row with a comparable total must not also be blocked")
        return self


class QuoteComparison(BaseModel):
    """Several quotes, side by side, ranked only where ranking is defensible."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rows: tuple[ComparisonRow, ...]
    requested_quantity: int | None = None
    cheapest_quote_id: str | None = Field(
        default=None,
        description="Named only when the compared totals share a basis and a currency.",
    )
    fastest_quote_id: str | None = None
    unanswered_by_everyone: tuple[str, ...] = Field(
        default=(), description="Questions no supplier answered - the follow-up writes itself."
    )
    note: str = ""

    # Deliberately absent: best_quote_id, and any score. Cheapest and fastest are
    # facts a column sort can defend. "Best" is a judgement, and at two or three
    # quotes a weighted model would be theatre - the same honesty the six-factor
    # match score is held to, at a sample size where scoring could not be.


class FollowUp(BaseModel):
    """A follow-up the buyer sends. Structurally a sibling of RFQ.

    Generating and sending are different acts, and this project only ever does
    the first. The questions are carried out of the RFQ's own confirmations by
    index - never chosen by a model, never conditionally dropped - so a question
    can only disappear because somebody demonstrably answered it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str
    supplier_id: str
    supplier_name: str
    subject: str
    questions: tuple[str, ...] = ()
    asks: tuple[str, ...] = Field(
        default=(),
        description="Sentences composed in Python from a row's blockers, never by the model.",
    )
    intro: str = ""
    closing: str = ""
