"""The real-company directory.

Reads the file ``scripts/build_berlin_partners.py`` produces. Written against
an interface rather than against SQL so that moving this to Postgres later is a
change of implementation and not a change of every caller - the same reason
:class:`~app.repositories.supplier_repo.SupplierRepository` is shaped this way.

Filtering happens in Python for now. At 135 records that is instant and the
code is readable; at 50,000 it will not be, and that is the point at which the
query belongs in the database rather than here. Writing it as SQL today would
be paying for a scale that does not exist yet.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import TypeAdapter

from app.domain.enums import ProductionMethod
from app.domain.partner import Partner, PartnerDirectory
from app.logging_config import Event, log_event

logger = logging.getLogger(__name__)

_PARTNERS = TypeAdapter(tuple[Partner, ...])


def _to_partner(raw: dict[str, object]) -> dict[str, object]:
    """Map the build script's field names onto the domain model's.

    ``method_implied_by_tag`` becomes ``implied_method``: the file says where
    the value came from, the model says what it means.
    """
    return {
        "id": raw["osm_id"],
        "name": raw["name"],
        "address": raw.get("address"),
        "city": raw.get("city") or "Berlin",
        "lat": raw.get("lat"),
        "lon": raw.get("lon"),
        "website": raw.get("website"),
        "email": raw.get("email"),
        "phone": raw.get("phone"),
        "implied_method": raw.get("method_implied_by_tag"),
    }


class PartnerRepository:
    """Loads and validates the directory once, then serves it in memory."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._directory: PartnerDirectory | None = None

    def _load(self) -> PartnerDirectory:
        if self._directory is not None:
            return self._directory

        if not self._path.is_file():
            # A missing directory is a deployment that has not run the build
            # script, not a broken one. Empty and loud beats a crash on a page
            # that has plenty else to show.
            log_event(
                logger,
                Event.TOOL_ERROR,
                "partner directory file not found",
                level=logging.WARNING,
                path=str(self._path),
            )
            self._directory = PartnerDirectory(
                partners=(), attribution="", source="", area="", incomplete_categories=()
            )
            return self._directory

        raw = json.loads(self._path.read_text(encoding="utf-8"))
        partners = _PARTNERS.validate_python([_to_partner(item) for item in raw["partners"]])

        self._directory = PartnerDirectory(
            partners=partners,
            attribution=raw.get("attribution", ""),
            source=raw.get("source", ""),
            area=raw.get("area", ""),
            incomplete_categories=tuple(raw.get("incomplete_categories") or ()),
        )
        log_event(
            logger,
            Event.SUPPLIER_CANDIDATES_FOUND,
            "partner directory loaded",
            partner_count=len(partners),
            contactable=sum(1 for partner in partners if partner.is_contactable),
            source=self._directory.source,
        )
        return self._directory

    def directory(self) -> PartnerDirectory:
        return self._load()

    def all(self) -> tuple[Partner, ...]:
        return self._load().partners

    def get(self, partner_id: str) -> Partner | None:
        return next((p for p in self.all() if p.id == partner_id), None)

    def search(
        self,
        *,
        query: str | None = None,
        method: ProductionMethod | None = None,
        with_email: bool = False,
        limit: int = 200,
    ) -> tuple[Partner, ...]:
        """Filter the directory.

        ``with_email`` exists because it is the question actually being asked of
        this data: which of these can I write to today. Searching name and
        address together, because "Kreuzberg" is how somebody looks for a
        printer near them and it lives in the address, not the name.
        """
        results = list(self.all())

        if query:
            needle = query.strip().casefold()
            results = [
                partner
                for partner in results
                if needle in partner.name.casefold()
                or (partner.address or "").casefold().find(needle) >= 0
            ]

        if method is not None:
            results = [partner for partner in results if partner.implied_method is method]

        if with_email:
            results = [partner for partner in results if partner.email]

        results.sort(key=lambda partner: partner.name.casefold())
        return tuple(results[:limit])

    def count(self) -> int:
        return len(self.all())

    def contactable_count(self) -> int:
        return sum(1 for partner in self.all() if partner.email)
