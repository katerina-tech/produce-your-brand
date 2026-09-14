"""What a supplier has actually done - ratings and completed jobs.

Built directly from the customer-discovery interview. Asked what would make a
product like this worth using at all, the print shop answered:

    "ChatGPT macht keine Bewertungen."   - ChatGPT does not rate suppliers.

and, in the same breath, named *erfolgreiche Angebote* - proven past quotes -
as the trust signal they would want to show. Until now the product quoted that
line as its differentiator without delivering it: it could tell you a supplier
was *capable*, never that anyone had been satisfied.

**Shown, deliberately not scored.** A track record does not enter
:mod:`app.services.matching`. This is the significant design decision in this
module and it is not caution for its own sake:

* A rating from three reviews must not be able to reorder a supplier list. The
  ranking's whole claim is that it is explainable from six stated capability
  factors; letting a thin, gameable number move it would quietly break that.
* Ratings are supplier-influenceable in a way that minimum order quantity is
  not. Anything that decides money must stay on data the supplier cannot talk
  up.
* The user still gets the information - next to the score, never inside it -
  and can weigh it themselves. That is the honest division: the system ranks on
  what it can defend, and reports what it merely knows.

Same provenance discipline as :class:`~app.domain.offer.Offer`, for the same
reason: the MVP has no real ratings, so every seeded record says so, and the
interface can be made to admit it in one place rather than trusting every call
site to remember.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TrackRecord(BaseModel):
    """A supplier's demonstrated history, as far as it is actually known.

    Every field is optional on purpose. "No rating yet" is a real and common
    state for a new partner, and it must be presentable as such - never as a
    zero, which would read as a bad rating rather than an absent one. This is
    the same ``null`` is not ``false`` rule the rest of the domain follows.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    supplier_id: str

    average_rating: float | None = Field(
        default=None,
        ge=1.0,
        le=5.0,
        description="Mean of received ratings, 1-5. None means nobody has rated yet.",
    )
    rating_count: int = Field(
        default=0,
        ge=0,
        description="How many ratings the average rests on. Displayed alongside it always.",
    )
    completed_orders: int = Field(
        default=0,
        ge=0,
        description="Jobs this supplier completed through the platform - the interview's "
        "'erfolgreiche Angebote'. Counted, never estimated.",
    )
    last_completed_on: date | None = None

    # ---- provenance, mirroring Offer ----
    is_demo: bool = Field(
        default=True,
        description="Seeded sample data rather than a real history. Defaults to True so "
        "a record can only become trustworthy by someone deciding it is.",
    )
    source: str | None = Field(
        default=None,
        description="Where the figures came from - platform records, an import, an interview.",
    )
    last_updated: date | None = None

    @model_validator(mode="after")
    def _check_internal_consistency(self) -> TrackRecord:
        """Reject the combinations that would let the interface mislead.

        These are assertions about meaning, not formatting: each one is a way
        the number could be read as stronger evidence than it is.
        """
        if self.average_rating is not None and self.rating_count == 0:
            raise ValueError("an average rating cannot rest on zero ratings")

        if self.average_rating is None and self.rating_count > 0:
            raise ValueError("ratings were counted but no average was given")

        if self.last_completed_on is not None and self.completed_orders == 0:
            raise ValueError("a completion date implies at least one completed order")

        return self

    @property
    def has_ratings(self) -> bool:
        """Whether a rating may be displayed at all."""
        return self.average_rating is not None and self.rating_count > 0

    @property
    def is_empty(self) -> bool:
        """No history of any kind. The interface should say "new partner",
        which is information, rather than showing zeroes, which reads as bad."""
        return not self.has_ratings and self.completed_orders == 0

    def summary(self) -> str:
        """One line for display. Never invents a figure it does not have."""
        if self.is_empty:
            return "No completed orders yet"

        parts: list[str] = []
        if self.has_ratings:
            assert self.average_rating is not None  # guaranteed by has_ratings
            noun = "rating" if self.rating_count == 1 else "ratings"
            parts.append(f"{self.average_rating:.1f}/5 from {self.rating_count} {noun}")
        if self.completed_orders:
            noun = "order" if self.completed_orders == 1 else "orders"
            parts.append(f"{self.completed_orders} completed {noun}")

        return " · ".join(parts)
