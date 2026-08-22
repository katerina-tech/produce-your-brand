"""Typed function tools.

Each tool is a thin, typed wrapper over a deterministic service or repository.
The wrapper exists for three reasons: a schema the model can be given, a single
audited entry point per capability, and a place to log tool failures without
letting them crash a node.

Note what is *not* here. Scoring is not a tool the model may influence - it is
called by a node with data the model never touches. Tools in this system read
facts and compute; they do not let the model decide outcomes.
"""

from __future__ import annotations

import logging
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ProductCategory, ProductionMethod
from app.domain.matching import MatchResult
from app.domain.requirement import ProductionRequirement
from app.domain.supplier import Supplier, SupplierQuery
from app.logging_config import Event, log_event
from app.repositories.supplier_repo import SupplierRepository
from app.services import matching

logger = logging.getLogger(__name__)


class ToolError(RuntimeError):
    """A tool could not complete. Nodes convert this into a workflow error."""


# ------------------------------------------------------------------- schemas


class SupplierSearchResult(BaseModel):
    """Ids and names only - full records stay in the repository."""

    model_config = ConfigDict(extra="forbid")

    supplier_ids: list[str]
    count: int


class SupplierCapabilities(BaseModel):
    """A partner's stored capabilities, verbatim. Nothing inferred."""

    model_config = ConfigDict(extra="forbid")

    supplier_id: str
    name: str
    city: str
    country: str
    supported_methods: list[ProductionMethod]
    supported_materials: list[str] | None
    product_categories: list[ProductCategory]
    min_order_quantity: int | None
    max_order_quantity: int | None
    accepts_customer_owned_products: bool | None = Field(
        description="null means unconfirmed, which is not the same as false."
    )
    typical_lead_time_days: int | None
    verified: bool
    notes: str | None


class MatchCalculation(BaseModel):
    """Deterministic scoring output, ranked."""

    model_config = ConfigDict(extra="forbid")

    matches: list[MatchResult]
    excluded: list[MatchResult]
    considered_count: int


# --------------------------------------------------------------------- tools


class ProductionTools:
    """The tool surface, bound to a supplier repository."""

    def __init__(self, suppliers: SupplierRepository) -> None:
        self._suppliers = suppliers

    def search_suppliers(
        self,
        method: ProductionMethod,
        category: ProductCategory | None = None,
        country: str | None = None,
    ) -> SupplierSearchResult:
        """Structurally filter partners. No free text, so phrasing cannot sway it."""
        log_event(
            logger,
            Event.SUPPLIER_SEARCH_STARTED,
            method=method.value,
            category=category.value if category else None,
            country=country,
        )
        try:
            found = matching.search_suppliers(
                self._suppliers.all(),
                SupplierQuery(method=method, category=category, country=country),
            )
        except Exception as error:
            log_event(
                logger,
                Event.TOOL_ERROR,
                "search_suppliers failed",
                level=logging.ERROR,
                error_type=type(error).__name__,
            )
            raise ToolError("supplier search failed") from error

        log_event(
            logger,
            Event.SUPPLIER_CANDIDATES_FOUND,
            method=method.value,
            candidate_count=len(found),
        )
        return SupplierSearchResult(
            supplier_ids=[supplier.id for supplier in found], count=len(found)
        )

    def get_supplier_capabilities(self, supplier_id: str) -> SupplierCapabilities | None:
        """Read one partner's stored facts. Returns None for an unknown id.

        Unknown ids return None rather than raising, because the common cause is
        a model naming a partner that does not exist - which must be dropped
        quietly rather than becoming an error the user sees.
        """
        supplier = self._suppliers.get(supplier_id)
        if supplier is None:
            log_event(
                logger,
                Event.TOOL_ERROR,
                "unknown supplier id requested",
                level=logging.WARNING,
                supplier_id=supplier_id,
            )
            return None

        return SupplierCapabilities(
            supplier_id=supplier.id,
            name=supplier.name,
            city=supplier.location.city,
            country=supplier.location.country,
            supported_methods=list(supplier.supported_methods),
            supported_materials=(
                list(supplier.supported_materials) if supplier.supported_materials else None
            ),
            product_categories=list(supplier.product_categories),
            min_order_quantity=supplier.min_order_quantity,
            max_order_quantity=supplier.max_order_quantity,
            accepts_customer_owned_products=supplier.accepts_customer_owned_products,
            typical_lead_time_days=supplier.typical_lead_time_days,
            verified=supplier.verified,
            notes=supplier.notes,
        )

    def calculate_supplier_matches(
        self,
        requirement: ProductionRequirement,
        method: ProductionMethod,
        today: date,
        top_n: int = 3,
        buffer_days: int = matching.DEFAULT_DEADLINE_BUFFER_DAYS,
    ) -> MatchCalculation:
        """Score and rank partners. Deterministic; the model has no input here."""
        try:
            outcome = matching.rank_matches(
                self._suppliers.all(),
                requirement,
                method,
                today,
                top_n=top_n,
                buffer_days=buffer_days,
            )
        except Exception as error:
            log_event(
                logger,
                Event.TOOL_ERROR,
                "match calculation failed",
                level=logging.ERROR,
                error_type=type(error).__name__,
            )
            raise ToolError("supplier match calculation failed") from error

        log_event(
            logger,
            Event.SUPPLIER_MATCHING_COMPLETED,
            method=method.value,
            considered=outcome.considered_count,
            ranked=len(outcome.top),
            excluded=len(outcome.excluded),
            top_score=outcome.top[0].score if outcome.top else None,
        )
        return MatchCalculation(
            matches=outcome.top,
            excluded=outcome.excluded,
            considered_count=outcome.considered_count,
        )

    def resolve_supplier(self, supplier_id: str) -> Supplier | None:
        """Resolve an id to a full record, or None if we do not have it."""
        return self._suppliers.get(supplier_id)
