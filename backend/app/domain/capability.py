"""What a company says it can do, in its own words.

The reviewer's point, and it is correct: no schema of eight production methods
will ever hold what a Berlin print shop actually offers. "UV-Direktdruck auf
Hohlkörper", "Flexdruck auf Sportbekleidung", "Sublimation nur auf Polyester" -
an enum either drops these or distorts them into the nearest listed thing,
which is worse.

So a claim is **text**, kept as the company wrote it, and a production method
is attached only when one obviously applies. The free text is what gets
embedded and searched; the enum, where present, is what the deterministic gates
can still use.

Every claim carries the words it came from, for the same reason a quoted price
does: a capability the company never stated is a claim this product would be
making on their behalf.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import ProductionMethod

ClaimKind = Literal["method", "material", "product", "constraint", "other"]


class CapabilityClaim(BaseModel):
    """One thing a company says about what it can do."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(
        min_length=2,
        max_length=300,
        description="The capability, close to how the company put it.",
    )
    quote: str = Field(
        min_length=2,
        description="Verbatim span from the page. Checked literally, never fuzzily.",
    )
    kind: ClaimKind = Field(
        default="other",
        description=(
            "A loose bucket, not a taxonomy. Useful for grouping on screen; nothing "
            "depends on it being right."
        ),
    )
    method: ProductionMethod | None = Field(
        default=None,
        description=(
            "Attached only when the text obviously names a method this system knows. "
            "None is the ordinary case and is not a gap - it means the claim is richer "
            "than the enum, which is the whole reason the text is kept."
        ),
    )


class SupplierCapabilities(BaseModel):
    """Everything read from one company's website, with where it came from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    partner_id: str
    partner_name: str
    source_urls: tuple[str, ...] = Field(
        description="The pages read. Empty is not allowed - a claim needs a page."
    )
    claims: tuple[CapabilityClaim, ...] = ()
    extracted_on: date
    dropped_count: int = Field(
        default=0,
        ge=0,
        description=(
            "Claims the verifier deleted because their words were not on the page. "
            "Kept as a number so a company whose reading went badly is visible rather "
            "than silently thin."
        ),
    )
    confirmed_by_human: bool = Field(
        default=False,
        description="Set server-side only. A read page is not a confirmed capability.",
    )

    @model_validator(mode="after")
    def _claims_need_a_page_they_came_from(self) -> SupplierCapabilities:
        if self.claims and not self.source_urls:
            raise ValueError("capability claims must name the pages they were read from")
        return self

    @property
    def searchable_text(self) -> str:
        """What gets embedded.

        The claims joined, not the whole page. A services page is mostly
        navigation, history and telephone numbers; embedding all of it buries
        the four sentences that say what the company does under six hundred
        that do not.
        """
        return "\n".join(claim.text for claim in self.claims)

    @property
    def methods(self) -> tuple[ProductionMethod, ...]:
        """The methods that mapped onto the enum, deduplicated.

        What the deterministic gates can still use. Deliberately a subset of
        what the company can do, and never treated as the whole of it.
        """
        seen: list[ProductionMethod] = []
        for claim in self.claims:
            if claim.method is not None and claim.method not in seen:
                seen.append(claim.method)
        return tuple(seen)

    @property
    def is_empty(self) -> bool:
        return not self.claims
