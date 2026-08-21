"""Deterministic RFQ assembly.

The document's *structure* is code, not prompt output. A quotation request that
silently omits "do you accept customer-owned goods" is worse than useless, so the
checklist is a constant rather than something a model decides to include.

The LLM's contribution in Phase 2 is limited to ``intro`` and ``closing`` prose.
Everything factual here is copied from the confirmed requirement - no field is
inferred, and unknown values are rendered as an explicit "not specified" rather
than quietly dropped.

Nothing in this module transmits anything. Generating an RFQ and sending one are
different acts, and the MVP only does the first.
"""

from __future__ import annotations

import logging

from app.domain.enums import ProductionMethod
from app.domain.requirement import ProductionRequirement
from app.domain.rfq import DEFAULT_CONFIRMATIONS, RFQ
from app.domain.supplier import Supplier
from app.logging_config import Event, log_event

logger = logging.getLogger(__name__)

NOT_SPECIFIED = "Not specified"


def _product_summary(requirement: ProductionRequirement) -> str:
    """e.g. '100 x black yoga mats (PVC)' from whatever is actually known."""
    parts: list[str] = []
    if requirement.quantity is not None:
        parts.append(f"{requirement.quantity} x")
    parts.append(requirement.product or "unspecified product")
    if requirement.material:
        parts.append(f"({requirement.material})")
    return " ".join(parts)


def _design_status(requirement: ProductionRequirement) -> str:
    if requirement.design_available is True:
        return "Available - will be supplied on request"
    if requirement.design_available is False:
        return "Not yet available"
    return NOT_SPECIFIED


def _additional_notes(requirement: ProductionRequirement) -> list[str]:
    """Constraints plus an honest note about anything still unconfirmed."""
    notes = list(requirement.additional_constraints)
    if requirement.preferred_finish:
        notes.append(f"Preferred finish: {requirement.preferred_finish}")
    if requirement.priority:
        notes.append(f"Customer priority: {requirement.priority.value}")
    if requirement.material is None:
        notes.append("Material has not been confirmed by the customer.")
    return notes


def build_rfq(
    requirement: ProductionRequirement,
    method: ProductionMethod,
    supplier: Supplier,
    intro: str | None = None,
    closing: str | None = None,
) -> RFQ:
    """Assemble an RFQ. ``approved`` is always False - approval is a human act.

    ``intro``/``closing`` accept LLM-polished prose; the defaults are neutral and
    complete, so a model failure degrades the tone rather than the document.
    """
    product_summary = _product_summary(requirement)
    method_label = method.value.replace("_", " ")

    rfq = RFQ(
        supplier_id=supplier.id,
        supplier_name=supplier.name,
        subject=f"Request for quotation - {product_summary}",
        product_summary=product_summary,
        quantity=requirement.quantity,
        customer_supplies_product=requirement.customer_owns_product,
        customization=requirement.customization_description or NOT_SPECIFIED,
        preferred_method=method,
        design_status=_design_status(requirement),
        deadline=requirement.deadline,
        delivery_location=requirement.location,
        intro=intro
        or (
            f"We are seeking a production partner for a {method_label} project and "
            f"would appreciate a quotation based on the details below."
        ),
        confirmations_requested=list(DEFAULT_CONFIRMATIONS),
        additional_notes=_additional_notes(requirement),
        closing=closing
        or "Thank you for your time - we look forward to your assessment and quotation.",
    )

    log_event(
        logger,
        Event.RFQ_GENERATED,
        supplier_id=supplier.id,
        method=method.value,
        quantity=requirement.quantity,
        approved=rfq.approved,
    )
    return rfq


def render_markdown(rfq: RFQ) -> str:
    """Render for display and copy-paste. Presentation only - no new facts."""
    supplies = {True: "Yes", False: "No", None: NOT_SPECIFIED}[rfq.customer_supplies_product]

    lines = [
        "# Request for Quotation",
        "",
        f"**To:** {rfq.supplier_name}",
        "",
        rfq.intro,
        "",
        "## Project",
        "",
        f"- **Product:** {rfq.product_summary}",
        f"- **Quantity:** {rfq.quantity if rfq.quantity is not None else NOT_SPECIFIED}",
        f"- **Customer supplies the product:** {supplies}",
        f"- **Customisation:** {rfq.customization}",
        f"- **Preferred production method:** {rfq.preferred_method.value.replace('_', ' ')}",
        f"- **Design:** {rfq.design_status}",
        f"- **Deadline:** {rfq.deadline.isoformat() if rfq.deadline else NOT_SPECIFIED}",
        f"- **Delivery:** {rfq.delivery_location or NOT_SPECIFIED}",
        "",
        "## Please confirm",
        "",
    ]
    lines += [f"{index}. {item}" for index, item in enumerate(rfq.confirmations_requested, 1)]

    if rfq.additional_notes:
        lines += ["", "## Notes", ""]
        lines += [f"- {note}" for note in rfq.additional_notes]

    lines += ["", rfq.closing]
    return "\n".join(lines)
