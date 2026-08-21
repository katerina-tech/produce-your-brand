"""Deterministic completeness check for a Production Brief.

Which fields are missing is not a judgement call, so no model is involved. The
LLM's job (Phase 2) is only to *phrase* the question for the field this module
selects.

The tiering matters to the product: showing a user a twelve-field form defeats
the purpose. Only fields that genuinely block the next step are asked about.
Everything else stays ``None``, is reported to the UI, and is handled downstream
by partial scoring plus a risk flag - an unknown deadline should cost a supplier
some points, not interrogate the customer.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.requirement import ProductionRequirement

# Ordered by how much the answer unblocks. The first missing field is the one we
# ask about, so this tuple is the question priority.
CRITICAL_FIELD_ORDER: tuple[str, ...] = (
    "product",
    "quantity",
    "customization_description",
    "customer_owns_product",
    "material",
)

# Known-but-absent is acceptable here: matching degrades gracefully instead.
NON_BLOCKING_FIELDS: tuple[str, ...] = (
    "product_category",
    "design_available",
    "preferred_finish",
    "deadline",
    "location",
    "priority",
)

# Backend owns the labels so the UI and the clarification flow cannot drift.
FIELD_LABELS: dict[str, str] = {
    "product": "Product",
    "product_category": "Category",
    "material": "Material",
    "quantity": "Quantity",
    "customer_owns_product": "Product source",
    "customization_description": "Customisation",
    "design_available": "Design",
    "preferred_finish": "Preferred finish",
    "deadline": "Deadline",
    "location": "Delivery location",
    "priority": "Priority",
    "additional_constraints": "Additional constraints",
}

# Why each critical field blocks progress. Surfaced in the UI next to the
# question so the user understands why they are being asked.
BLOCKING_REASONS: dict[str, str] = {
    "product": "Nothing can be sourced without knowing what the product is.",
    "quantity": (
        "Quantity decides which partners are viable at all, via their minimum order quantity."
    ),
    "customization_description": "The customisation determines which production technique applies.",
    "customer_owns_product": (
        "Whether you supply the goods or the partner sources them changes which "
        "partners can take the job."
    ),
    "material": "Material decides whether a technique is technically feasible on this product.",
}


class CompletenessReport(BaseModel):
    """Outcome of the check. ``next_field`` is what to ask about, if anything."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    missing_critical: tuple[str, ...]
    missing_optional: tuple[str, ...]
    next_field: str | None
    is_ready_for_review: bool

    @property
    def blocking_reason(self) -> str | None:
        return BLOCKING_REASONS.get(self.next_field) if self.next_field else None


def check(requirement: ProductionRequirement) -> CompletenessReport:
    """Report what is missing, and which single field to ask about next.

    Pure function: same requirement in, same report out. No I/O, no model call.
    """
    known = requirement.known_fields()

    missing_critical = tuple(field for field in CRITICAL_FIELD_ORDER if field not in known)
    missing_optional = tuple(field for field in NON_BLOCKING_FIELDS if field not in known)

    return CompletenessReport(
        missing_critical=missing_critical,
        missing_optional=missing_optional,
        next_field=missing_critical[0] if missing_critical else None,
        is_ready_for_review=not missing_critical,
    )


def describe_missing(report: CompletenessReport) -> tuple[str, ...]:
    """Human-readable labels for the missing critical fields, for the UI."""
    return tuple(FIELD_LABELS.get(field, field) for field in report.missing_critical)
