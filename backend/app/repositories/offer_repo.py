"""Offer data access - mirrors :mod:`app.repositories.supplier_repo` exactly.

One file, one repository, same reasoning: a few dozen records at most for the
MVP, so a JSON file avoids a database-and-JSON-file drifting apart. Filtering
lives in the caller (:mod:`app.services.offers`), not here, for the same
one-way-dependency reason supplier filtering lives in
``app.services.matching`` rather than in ``SupplierRepository``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import TypeAdapter

from app.domain.offer import Offer
from app.logging_config import Event, log_event

logger = logging.getLogger(__name__)

_OFFERS = TypeAdapter(tuple[Offer, ...])


class OfferRepository:
    """Loads and validates the offer dataset once, then serves it in memory."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._offers: tuple[Offer, ...] | None = None
        self._by_supplier: dict[str, list[Offer]] = {}

    def _load(self) -> tuple[Offer, ...]:
        if self._offers is not None:
            return self._offers

        raw = json.loads(self._path.read_text(encoding="utf-8"))
        offers = _OFFERS.validate_python(raw["offers"])

        duplicates = len(offers) - len({offer.id for offer in offers})
        if duplicates:
            raise ValueError(f"offer dataset contains {duplicates} duplicate id(s)")

        self._offers = offers
        by_supplier: dict[str, list[Offer]] = {}
        for offer in offers:
            by_supplier.setdefault(offer.supplier_id, []).append(offer)
        self._by_supplier = by_supplier

        log_event(
            logger,
            Event.OFFERS_LOADED,
            "offer dataset loaded",
            offer_count=len(offers),
            source=raw.get("_provenance", {}).get("data_source", "unknown"),
        )
        return offers

    def all(self) -> tuple[Offer, ...]:
        return self._load()

    def for_supplier(self, supplier_id: str) -> tuple[Offer, ...]:
        """Every offer on file for this supplier, regardless of validity window."""
        self._load()
        return tuple(self._by_supplier.get(supplier_id, ()))

    def count(self) -> int:
        return len(self._load())
