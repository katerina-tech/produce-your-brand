"""Request for Quotation.

Structured rather than a text blob, for two reasons: the human edits individual
fields instead of re-writing prose, and the document structure is deterministic
Python (:mod:`app.services.rfq_builder`) rather than prompt output. The LLM only
polishes ``intro`` and ``closing``.

Nothing here is ever transmitted to a real supplier in the MVP.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ProductionMethod

DEFAULT_CONFIRMATIONS: tuple[str, ...] = (
    "Technical feasibility of the requested customisation",
    "Recommended production method and any deviation you would advise",
    "Total price for the stated quantity",
    "Setup / tooling costs",
    "Your minimum order quantity for this method",
    "Production time from artwork approval",
    "Sample availability, cost and lead time",
    "Artwork requirements (file format, colour space, minimum sizes)",
    "Acceptance of customer-owned goods supplied to your facility",
)


class RFQ(BaseModel):
    """A supplier-ready quotation request, pending human approval."""

    model_config = ConfigDict(extra="forbid")

    supplier_id: str
    supplier_name: str
    subject: str

    product_summary: str
    quantity: int | None = None
    customer_supplies_product: bool | None = None
    customization: str
    preferred_method: ProductionMethod
    design_status: str = Field(description="e.g. 'Available - vector file'.")
    deadline: date | None = None
    delivery_location: str | None = None

    intro: str = Field(description="Short opening paragraph. LLM-polished.")
    confirmations_requested: list[str] = Field(default_factory=lambda: list(DEFAULT_CONFIRMATIONS))
    additional_notes: list[str] = Field(default_factory=list)
    closing: str = Field(description="Short closing line. LLM-polished.")

    approved: bool = Field(
        default=False,
        description="Set only by an explicit human approval action. The workflow "
        "cannot complete while this is False.",
    )
