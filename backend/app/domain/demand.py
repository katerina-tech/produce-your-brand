"""A buyer's request, published on purpose so companies can find it.

The third side of the market. Tenders are public demand from government; the
directory is supply; this is private demand, from somebody who wants a hundred
yoga mats printed and would rather be found than do the finding.

**This is a narrowing, not a copy.** A ``ProductionRequirement`` is what a buyer
told this product in confidence. Publishing it wholesale would leak three
different things at once, so the projection is deliberate and each omission has
a reason:

* **No name and no email, ever.** A public board carrying contact details is a
  board that gets harvested, and the person who wrote "I need 100 mats" would
  receive forty cold emails - which is both § 7 UWG and a bad afternoon. The
  buyer chooses who to answer.
* **The budget is hidden unless the buyer says otherwise.** What somebody is
  willing to pay is the one fact that weakens their position in every
  negotiation that follows. Default off, and a field they tick rather than one
  they must remember to clear.
* **A city, never an address.** ``location`` in a requirement is "as stated" and
  is routinely a doorstep. The listing carries the city and nothing finer.
* **Its own id.** Not the project id: a project id in a public URL is the
  address of a private page, and putting one on a board would hand out both.

Nothing is published that the buyer has not read *as public text*. The API
returns the exact listing before it goes live, and they edit it there - which is
why ``customization_description`` and ``note`` are the buyer's own words for
strangers rather than lifted out of a brief they wrote for us.
"""

from __future__ import annotations

import secrets
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ProductCategory, ProductionMethod
from app.domain.project import Project

# How long a listing stands when the buyer named no deadline. Long enough to be
# worth publishing, short enough that a board of forgotten requests does not
# accumulate - a stale board is worse than a small one, because a company that
# answers a dead request once does not come back.
DEFAULT_DAYS_LIVE = 60

# Room for a sentence or two of detail, not an essay. The structured fields
# carry the substance; this is for the thing that does not fit them.
MAX_NOTE_CHARS = 600


def new_request_id() -> str:
    """A public id with nothing derivable in it.

    Random rather than derived from the project: anything derived is something
    that can be worked backwards, and the whole point of this id is that it
    reveals nothing about the private page behind it.
    """
    return f"req_{secrets.token_urlsafe(9)}"


class PublicRequest(BaseModel):
    """One buyer's request, as strangers see it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    project_id: str = Field(
        description="Never sent to the public. Server-side only, so the buyer's own "
        "screens can find their listing."
    )

    product: str
    product_category: ProductCategory | None = None
    material: str | None = None
    quantity: int | None = None
    customer_owns_product: bool | None = Field(
        default=None,
        description=(
            "Whether the goods already exist and need decorating. Three-valued, and "
            "the single most useful line on the board: half of Berlin's print shops "
            "will not touch customer-owned stock, and the ones that will want to know."
        ),
    )
    method: ProductionMethod | None = Field(
        default=None, description="The method the buyer confirmed, when they confirmed one."
    )

    city: str = Field(default="", description="A city. Never a street, never a postcode.")
    deadline: date | None = None
    budget_eur: float | None = Field(
        default=None,
        description="Only present when the buyer chose to show it. Absent by default.",
    )
    note: str = Field(default="", max_length=MAX_NOTE_CHARS)

    published_at: datetime
    expires_on: date

    def is_open_on(self, today: date) -> bool:
        return self.expires_on >= today

    @property
    def searchable_text(self) -> str:
        """What the capability matcher reads, if it is ever pointed at this."""
        parts = [self.product, self.material or "", self.note]
        return "\n".join(part for part in parts if part).strip()


def _city_of(location: str | None) -> str:
    """The city out of a location a buyer typed freely.

    Last comma-separated part, because "Wrangelstraße 12, 10997 Berlin" is how
    people write it and the city is at the end. Any digits are dropped with the
    postcode: a listing is not the place for either half of an address.
    """
    if not location:
        return ""
    tail = location.split(",")[-1].strip()
    words = [word for word in tail.split() if not any(char.isdigit() for char in word)]
    return " ".join(words)[:60]


def draft_from(
    project: Project,
    *,
    show_budget: bool = False,
    note: str = "",
    request_id: str | None = None,
    now: datetime | None = None,
) -> PublicRequest | None:
    """The listing a project would publish, or None when it has nothing to say.

    Built from the **confirmed** brief rather than the model's first reading:
    a listing is a claim a buyer makes to strangers, and an unconfirmed
    extraction is not yet theirs.
    """
    requirement = project.requirement
    if requirement is None or not project.brief_confirmed:
        return None
    if not requirement.product:
        return None

    moment = now or datetime.now(UTC)
    deadline = requirement.deadline
    return PublicRequest(
        id=request_id or new_request_id(),
        project_id=project.id,
        product=requirement.product,
        product_category=requirement.product_category,
        material=requirement.material,
        quantity=requirement.quantity,
        customer_owns_product=requirement.customer_owns_product,
        method=project.confirmed_method,
        city=_city_of(requirement.location),
        deadline=deadline,
        budget_eur=requirement.budget_eur if show_budget else None,
        note=note.strip()[:MAX_NOTE_CHARS],
        published_at=moment,
        expires_on=deadline or (moment.date() + timedelta(days=DEFAULT_DAYS_LIVE)),
    )
