"""Supplier capability records.

``data/suppliers.json`` is the single source of truth for supplier facts. The LLM
never produces a ``Supplier``; it is only ever loaded from that file and
validated here. That is what structurally prevents invented capabilities.

Null discipline matters especially here: ``accepts_customer_owned_products=None``
means "we have not confirmed this", which is materially different from ``False``.
The matching service treats them differently - unknown scores partially and
raises a risk flag, whereas an explicit ``False`` is a hard incompatibility.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ProductCategory, ProductionMethod


class Location(BaseModel):
    """Where a supplier produces. ``region`` enables coarse proximity scoring."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    city: str
    country: str = Field(description="ISO 3166-1 alpha-2, e.g. 'DE'.", min_length=2, max_length=2)
    region: str = Field(default="EU", description="Coarse bloc, e.g. 'EU'.")


class Supplier(BaseModel):
    """A production partner's stored, reviewable capabilities."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    location: Location
    website: str | None = None
    supported_methods: tuple[ProductionMethod, ...]
    supported_materials: tuple[str, ...] | None = None
    product_categories: tuple[ProductCategory, ...]
    min_order_quantity: int | None = Field(default=None, ge=0)
    max_order_quantity: int | None = Field(default=None, ge=0)
    accepts_customer_owned_products: bool | None = None
    typical_lead_time_days: int | None = Field(default=None, ge=0)
    verified: bool = False
    notes: str | None = None
    data_source: str = Field(
        default="synthetic",
        description="Provenance. 'synthetic' for the curated MVP dataset; real "
        "partners carry their source so the UI can label them honestly.",
    )


class SupplierQuery(BaseModel):
    """Deterministic filter for :func:`app.services.matching.search_suppliers`.

    Purely structural - no free-text search, so results cannot depend on prompt
    phrasing.
    """

    model_config = ConfigDict(extra="forbid")

    method: ProductionMethod
    category: ProductCategory | None = None
    country: str | None = None
