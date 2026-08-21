"""Deterministic supplier match results.

The numeric score is computed in :mod:`app.services.matching` in plain Python.
The LLM receives the completed breakdown and may only populate
``ai_explanation``. It never produces or adjusts ``score``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class MatchFactor(StrEnum):
    """The six weighted factors, with their maximum point values in WEIGHTS."""

    METHOD = "method"
    MATERIAL = "material"
    QUANTITY = "quantity"
    CUSTOMER_OWNED = "customer_owned"
    DEADLINE = "deadline"
    LOCATION = "location"


WEIGHTS: dict[MatchFactor, float] = {
    MatchFactor.METHOD: 30.0,
    MatchFactor.MATERIAL: 20.0,
    MatchFactor.QUANTITY: 15.0,
    MatchFactor.CUSTOMER_OWNED: 15.0,
    MatchFactor.DEADLINE: 10.0,
    MatchFactor.LOCATION: 10.0,
}

MAX_SCORE = sum(WEIGHTS.values())


class Verdict(StrEnum):
    """Per-factor outcome. ``UNKNOWN`` is distinct from ``MISMATCH`` on purpose."""

    MATCH = "match"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    MISMATCH = "mismatch"


class FactorScore(BaseModel):
    """One factor's contribution, with a reason generated in Python."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    factor: MatchFactor
    awarded: float
    max_points: float
    verdict: Verdict
    explanation: str


class MatchResult(BaseModel):
    """A supplier's deterministic fit against the confirmed requirement."""

    model_config = ConfigDict(extra="forbid")

    supplier_id: str
    supplier_name: str
    score: float = Field(ge=0.0, le=MAX_SCORE)
    eligible: bool = Field(
        description="False when a hard incompatibility applies. Ineligible "
        "suppliers are reported separately and never ranked into the top matches."
    )
    exclusion_reason: str | None = None
    factors: tuple[FactorScore, ...]
    risk_flags: tuple[str, ...] = ()
    ai_explanation: str | None = Field(
        default=None,
        description="Optional LLM prose. The only LLM-written field on this model.",
    )
