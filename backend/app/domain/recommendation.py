"""Recommendation perspectives - alternate lenses over the same match set.

Added per the first customer-discovery interview: a single ranked list makes
"which one is objectively best" easy to answer, but a buyer juggling several
priorities also wants "which is cheapest" and "which is fastest" without
re-deriving that from six factor scores themselves. This is presentation over
data that :mod:`app.services.matching` already computed deterministically -
it does not re-score anything, and it never appears where the underlying data
does not exist (see :func:`app.services.recommendations.build_perspectives`).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RecommendationPerspective(BaseModel):
    """One supplier, framed for one specific question a buyer might ask."""

    model_config = ConfigDict(extra="forbid")

    supplier_id: str
    supplier_name: str
    headline: str = Field(description="e.g. '94% compatibility', '€3.20 estimated'.")
    detail: str | None = Field(
        default=None, description="e.g. an offer's title, or 'Price on request'."
    )
    offer_id: str | None = Field(
        default=None, description="Set only when this perspective is backed by an Offer."
    )
    is_demo: bool = Field(
        default=False, description="True when backed by a demo/seed offer, never a real one."
    )


class RecommendationPerspectives(BaseModel):
    """Up to three perspectives. Each is None when there is not enough real
    data to populate it - never filled with an invented price or lead time."""

    model_config = ConfigDict(extra="forbid")

    best_match: RecommendationPerspective | None = None
    best_price: RecommendationPerspective | None = None
    fastest: RecommendationPerspective | None = None
