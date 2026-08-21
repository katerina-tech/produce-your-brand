"""The structured Production Brief.

This is the output of requirement extraction and the input to every downstream
step. The null discipline is the important part: an unknown value stays ``None``
so that the completeness check can ask about it and the matching service can flag
it. A guessed value is worse than a missing one, because it silently produces a
confident wrong match.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Priority, ProductCategory


class ProductionRequirement(BaseModel):
    """Structured representation of what the customer wants produced.

    ``extra="forbid"`` means the LLM cannot invent fields; every optional field
    defaults to ``None`` so it cannot invent values either.
    """

    model_config = ConfigDict(extra="forbid")

    product: str | None = Field(
        default=None, description="What the physical product is, e.g. 'black yoga mats'."
    )
    product_category: ProductCategory | None = Field(
        default=None, description="Category, only if clearly implied by the product."
    )
    material: str | None = Field(
        default=None, description="Material as stated by the customer, e.g. 'natural rubber'."
    )
    quantity: int | None = Field(default=None, gt=0, description="Number of units.")
    customer_owns_product: bool | None = Field(
        default=None,
        description="True if the customer already owns the blank goods and will supply them.",
    )
    customization_description: str | None = Field(
        default=None, description="What should be applied, e.g. 'gold logo on the corner'."
    )
    design_available: bool | None = Field(
        default=None, description="True if artwork already exists."
    )
    preferred_finish: str | None = Field(
        default=None, description="Requested finish, e.g. 'gold', 'matte', 'debossed'."
    )
    deadline: date | None = Field(default=None, description="Required delivery date.")
    location: str | None = Field(default=None, description="Delivery location as stated.")
    priority: Priority | None = Field(default=None, description="Only if explicitly stated.")
    additional_constraints: list[str] = Field(
        default_factory=list, description="Other stated constraints. Empty if none."
    )

    def known_fields(self) -> set[str]:
        """Field names that currently hold a value."""
        return {
            name for name in type(self).model_fields if getattr(self, name) not in (None, [], "")
        }

    def merge(self, other: ProductionRequirement) -> ProductionRequirement:
        """Fill gaps in ``self`` from ``other`` without overwriting known values.

        Used by the clarification loop: an answer may only add information, never
        silently revise something the user already told us.
        """
        merged = self.model_dump()
        for name in type(self).model_fields:
            current = merged.get(name)
            incoming = getattr(other, name)
            if current in (None, [], "") and incoming not in (None, [], ""):
                merged[name] = incoming
        return ProductionRequirement.model_validate(merged)
