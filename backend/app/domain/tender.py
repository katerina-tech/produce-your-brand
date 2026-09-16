"""A public contract somebody in Germany is asking to have printed, sewn or engraved.

The other half of the market. The directory answers "who can make this"; a
tender is a buyer who has already said what they want, in public, with a
deadline and usually a budget - and 136 Berlin companies who have never heard
of it.

**The data is CC0.** Germany's Datenservice Öffentlicher Einkauf publishes every
federal, state and municipal notice as open data, dedicated to the public
domain. Nothing here is scraped: there is an API, and it is meant to be used.
That also means this carries **below-threshold** notices, which is the half
that matters here - an EU-threshold contract is too large for a copyshop, and
the small municipal ones never reach TED at all.

**CPV is the gate, and it is a controlled vocabulary.** The EU's Common
Procurement Vocabulary says what is being bought, in codes, chosen by the buyer
rather than inferred by us. That makes it exactly the kind of thing this
codebase already trusts: a hard filter written down once, the same discipline
as the OpenStreetMap tag map. A model may later rank which company fits; it
never decides whether a tender is about printing.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ProductionMethod


class CpvFamily(BaseModel):
    """One group of CPV codes, in words a print shop would use."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prefix: str = Field(description="The CPV prefix this family covers, e.g. '798'.")
    label: str = Field(description="What it is called, in German, as the trade would say it.")
    english: str = Field(description="The same, for a reader who is not in the trade.")
    implied_method: ProductionMethod | None = Field(
        default=None,
        description=(
            "What the code obviously implies, where it obviously implies something. "
            "None is the ordinary case: 'occupational clothing' is a purchase of "
            "garments, and whether it wants embroidery is a question for the tender "
            "document, not for this table."
        ),
    )


# Ordered most specific first, because 30199 must win over nothing and 39298
# must not be swallowed by a broader neighbour. Six families, each chosen
# because a Berlin printer, textile shop or engraver could actually bid.
CPV_FAMILIES: tuple[CpvFamily, ...] = (
    CpvFamily(
        prefix="22",
        label="Druckerzeugnisse",
        english="Printed matter",
        implied_method=ProductionMethod.DIGITAL_PRINTING,
    ),
    CpvFamily(
        prefix="798",
        label="Druckdienstleistungen",
        english="Printing services",
        implied_method=ProductionMethod.DIGITAL_PRINTING,
    ),
    CpvFamily(
        prefix="30199",
        label="Geschäftsdrucksachen",
        english="Business stationery",
        implied_method=ProductionMethod.DIGITAL_PRINTING,
    ),
    CpvFamily(
        prefix="39298",
        label="Pokale & Gravuren",
        english="Trophies and engraving",
        implied_method=ProductionMethod.LASER_ENGRAVING,
    ),
    CpvFamily(
        prefix="18",
        label="Arbeitskleidung & Textilien",
        english="Workwear and textiles",
    ),
    CpvFamily(
        prefix="7934",
        label="Werbung & Kampagnen",
        english="Advertising and campaigns",
    ),
)

_BY_PREFIX = sorted(CPV_FAMILIES, key=lambda family: -len(family.prefix))


def family_for(code: str) -> CpvFamily | None:
    """The family a CPV code belongs to, or None when it is none of our business.

    Longest prefix wins. Without that, ``30199`` (printed stationery) would be
    read as whatever a shorter neighbour claimed, and the filter would quietly
    answer a different question than the one it names.
    """
    cleaned = code.strip()
    if not cleaned.isdigit():
        return None
    for family in _BY_PREFIX:
        if cleaned.startswith(family.prefix):
            return family
    return None


class Tender(BaseModel):
    """One public contract notice, as published.

    Every field is copied from the notice or left out. Nothing here is this
    product's reading of a tender: a buyer's own title and description are what
    a company needs in order to decide whether to open the documents.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(description="The publisher's notice identifier. Stable, and the key.")
    title: str
    description: str = ""

    cpv: str = Field(description="The main CPV code the buyer chose.")
    family_prefix: str = Field(description="Which of our families it fell into.")
    family_label: str
    implied_method: ProductionMethod | None = Field(
        default=None,
        description="What the CPV family implies, never what the tender confirmed.",
    )

    buyer: str = ""
    buyer_city: str = ""
    place_city: str = ""
    place_region: str = Field(
        default="",
        description=(
            "The NUTS code of where the work happens. DE3 is Berlin; the first three "
            "characters identify the Bundesland, which is what the region filter reads."
        ),
    )

    estimated_value: float | None = Field(
        default=None,
        description=(
            "Euros, when the buyer stated one. Very often they do not, and None says "
            "so rather than pretending to a zero."
        ),
    )
    currency: str = ""

    published_on: date
    deadline: datetime | None = Field(
        default=None, description="When bids close, when the notice says."
    )

    suitable_for_smes: bool | None = Field(
        default=None,
        description=(
            "The buyer's own declaration, three-valued. The single most useful field "
            "for a directory of small shops - and null means the buyer did not say, "
            "which is not the same as 'no'."
        ),
    )
    procedure_type: str = ""
    notice_type: str = ""
    source_url: str = ""

    @property
    def is_berlin(self) -> bool:
        """Whether the work happens in Berlin.

        By NUTS rather than by the city string: a buyer writes "Berlin-Mitte",
        "10115 Berlin" or nothing at all, and DE3 is the same answer every time.
        """
        return self.place_region.startswith("DE3") or self.place_city.casefold().startswith(
            "berlin"
        )

    @property
    def searchable_text(self) -> str:
        """What the capability matcher reads. Title first, because it is the
        line a buyer wrote to be understood at a glance."""
        return f"{self.title}\n{self.description}".strip()

    def is_open_on(self, today: date) -> bool:
        """Whether bids can still be submitted.

        A tender with no stated deadline counts as open: the notice exists, and
        hiding it because a field was empty would be this product deciding a
        contract is closed on no evidence.
        """
        if self.deadline is None:
            return True
        return self.deadline.date() >= today
