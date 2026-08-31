"""Supplier offers - current pricing, capacity and special conditions.

Added per the first customer-discovery interview (see README's Product
hypothesis section): a supplier record alone answers "can they do this?", not
"what would it actually cost, and is there a current deal?" - and the latter is
exactly the structured intelligence a generic ChatGPT/Google search cannot
surface, which is where this product's differentiation is supposed to live.

Same null discipline as :mod:`app.domain.supplier`, and it matters even more
here: pricing is the field a user is most likely to over-trust, so an unknown
``price_from`` must render as "Price on request", never as a guess or a zero.

``is_demo`` is not optional decoration. The MVP dataset has zero real supplier
offers (real pricing cannot be reliably scraped - see the interview note this
was built from), so every seeded record is demo data, and the UI must say so
everywhere an offer is shown. This field is what makes that possible to check
in one place rather than trusting every call site to remember.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import ProductionMethod


class Offer(BaseModel):
    """A supplier's current pricing/capacity for a production method.

    Distinct from :class:`~app.domain.supplier.Supplier`: a supplier record is
    slow-changing capability data (what they *can* do); an offer is a
    time-boxed claim about price, capacity or terms *right now*, and is
    expected to go stale and be replaced far more often.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    supplier_id: str
    title: str
    description: str | None = None
    production_method: ProductionMethod | None = Field(
        default=None, description="Null when the offer applies broadly, not to one method."
    )
    materials: tuple[str, ...] | None = None
    min_quantity: int | None = Field(default=None, ge=0)
    max_quantity: int | None = Field(default=None, ge=0)
    price_from: float | None = Field(
        default=None, ge=0, description="Null means unknown, never assumed to be zero or free."
    )
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    lead_time_days: int | None = Field(default=None, ge=0)
    valid_from: date | None = None
    valid_until: date | None = None
    discount_percentage: float | None = Field(default=None, ge=0, le=100)
    special_conditions: str | None = None

    verified: bool = Field(
        default=False,
        description="True only for a human-confirmed offer. Never set by the LLM.",
    )
    source: str = Field(
        description="Provenance: 'demo_seed', 'discovered', 'supplier_provided', "
        "or 'manually_verified'. Drives how the UI labels the offer."
    )
    last_updated: date

    is_demo: bool = Field(
        description="True for every record in the seeded MVP dataset. The UI "
        "must show a demo label wherever an offer with is_demo=True appears - "
        "see app/services/offers.py."
    )

    @model_validator(mode="after")
    def _demo_offers_cannot_claim_verification(self) -> Offer:
        """A demo/seed record is not a fact about a real supplier - it cannot
        also claim to be verified, or the two flags would contradict each
        other in front of a user."""
        if self.is_demo and self.verified:
            raise ValueError("a demo offer cannot also be verified")
        return self

    def is_active(self, today: date) -> bool:
        """Whether this offer's validity window covers ``today``.

        A missing bound is open-ended on that side - "valid_until: null" means
        no known expiry, not "already expired".
        """
        if self.valid_from is not None and today < self.valid_from:
            return False
        return not (self.valid_until is not None and today > self.valid_until)
