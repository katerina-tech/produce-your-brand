"""Production method recommendation.

Technical claims are presented with explicit uncertainty: ``open_questions`` and
``confidence`` exist so the UI never renders an unverified claim as a guarantee.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Confidence, ProductionMethod
from app.domain.knowledge import KnowledgeCitation


class MethodRecommendation(BaseModel):
    """Recommended technique plus the caveats a human needs to approve it."""

    model_config = ConfigDict(extra="forbid")

    primary: ProductionMethod
    alternative: ProductionMethod | None = None
    rationale: str = Field(description="Why this method suits the product and finish.")
    constraints: list[str] = Field(
        default_factory=list, description="Technical limitations the customer should know."
    )
    artwork_requirements: list[str] = Field(
        default_factory=list, description="What the supplier will need from the design."
    )
    open_questions: list[str] = Field(
        default_factory=list, description="What remains genuinely unverified."
    )
    confidence: Confidence = Confidence.MEDIUM
    sources: list[KnowledgeCitation] = Field(
        default_factory=list,
        description="Empty when the recommendation did not require retrieval.",
    )
    retrieval_used: bool = False
