"""A real company, as opposed to a scored supplier.

The distinction this module exists to hold: a :class:`~app.domain.supplier.Supplier`
is something the matcher can score, because somebody established its materials,
minimum order and lead time. A :class:`Partner` is a real business that exists
at an address - and nothing more is claimed about it.

Keeping them as separate types is what stops the two from blurring. A scraped
directory entry that could be passed to the scorer would eventually be passed
to the scorer, and the product would start making claims about named companies
that nobody ever asked them.

What a Partner carries, it carries because the business published it. What it
does not carry is absent rather than guessed.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ProductionMethod


class Partner(BaseModel):
    """A real business, with the details it published itself."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(description="Stable id from the source, e.g. 'way/553786971'.")
    name: str
    source: str = Field(default="openstreetmap", description="Where this record came from.")
    verified: bool = Field(
        default=False,
        description=(
            "Whether a human confirmed this business can do what the record suggests. "
            "False for everything collected automatically."
        ),
    )
    verified_by: str | None = Field(
        default=None,
        description=(
            "'company' when the business confirmed it after proving control of its own "
            "website, 'operator' when we did. Different claims: the first is the "
            "strongest signal this directory can carry, and a badge that flattened "
            "both into one tick would throw that away."
        ),
    )

    address: str | None = None
    city: str = "Berlin"
    district: str | None = Field(
        default=None,
        description=(
            "The Ortsteil - Kreuzberg, Wedding, Prenzlauer Berg. What a person says "
            "out loud when they mean 'near me', and what half these addresses do not "
            "contain, which is why it is derived from the coordinates rather than "
            "parsed out of the street line."
        ),
    )
    borough: str | None = Field(
        default=None,
        description=(
            "The Bezirk - one of Berlin's twelve. The one of the two that makes a "
            "usable filter, because fifty Ortsteile in a dropdown is a list nobody "
            "reads. None for the handful of businesses just outside the city, which "
            "is the honest answer rather than the nearest Berlin name."
        ),
    )
    category: str | None = Field(
        default=None,
        description=(
            "The source tag this business was found under, e.g. 'craft=printer'. "
            "Carried alongside the label so a filter's claim stays checkable against "
            "the map anybody can look at."
        ),
    )
    category_label: str | None = Field(
        default=None,
        description=(
            "What that tag is called by the people who run these businesses - "
            "Druckerei, Copyshop, Stickerei. One label per tag, never two tags "
            "sharing one: a Druckerei and a Copyshop are different shops to "
            "anybody in Berlin."
        ),
    )

    lat: float | None = None
    lon: float | None = None

    website: str | None = None
    email: str | None = None
    email_source: str | None = Field(
        default=None,
        description=(
            "Where the address was read from: 'openstreetmap' for a map tag, "
            "'website' for the company's own page. Shown, because the two are not "
            "equally likely to still be watched and a person about to write deserves "
            "to know which they have."
        ),
    )
    phone: str | None = None
    summary: str | None = Field(
        default=None,
        description=(
            "The company's own one-line description of itself, from its site's meta "
            "description. Not a sentence this product chose out of their page, and "
            "not a model's paraphrase - their line, or nothing."
        ),
    )

    implied_method: ProductionMethod | None = Field(
        default=None,
        description=(
            "What the source's own category suggests, not what the business confirmed. "
            "A shop tagged 'printer' certainly prints; whether it screen-prints on PVC "
            "is a question for the shop. Named separately from Supplier.supported_methods "
            "so the two can never be mistaken for each other."
        ),
    )

    @property
    def is_contactable(self) -> bool:
        """Whether there is any way to reach them from this record alone."""
        return bool(self.email or self.phone or self.website)

    def distance_km(self, lat: float, lon: float) -> float | None:
        """Great-circle distance, or ``None`` when this record has no position.

        Kilometres rather than "same city": a business two streets away in
        Kreuzberg and one in Spandau are both "Berlin", and only one of them is
        somewhere you would drive a pallet of mats to.
        """
        if self.lat is None or self.lon is None:
            return None

        radius_km = 6371.0
        lat1, lon1, lat2, lon2 = map(math.radians, (self.lat, self.lon, lat, lon))
        a = (
            math.sin((lat2 - lat1) / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
        )
        return round(2 * radius_km * math.asin(math.sqrt(a)), 2)


class PartnerDirectory(BaseModel):
    """The collected set, with the provenance that travels with it.

    ``attribution`` is not decoration: OpenStreetMap data is licensed under the
    ODbL, which requires it, and a derived database that dropped it would be a
    licence breach rather than an oversight.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    partners: tuple[Partner, ...]
    attribution: str
    source: str
    area: str
    incomplete_categories: tuple[str, ...] = Field(
        default=(),
        description=(
            "Source categories that could not be fetched when this was built, so their "
            "businesses are missing entirely. Recorded because a silent zero and a real "
            "zero mean opposite things."
        ),
    )
