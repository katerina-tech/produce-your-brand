"""Track-record data access - mirrors :mod:`app.repositories.offer_repo` exactly.

Same shape and same reasoning: one JSON file, validated once, served from
memory. Keeping the third dataset identical in structure to the first two is
deliberate - a reader who has understood one repository has understood all
three, and a new dataset should not invent a new way of being loaded.

A missing file is not an error. Track records are the newest dataset and a
deployment may legitimately not carry one yet; in that case every supplier is
simply a partner with no history, which is a real state the interface already
has to render.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import TypeAdapter

from app.domain.track_record import TrackRecord
from app.logging_config import Event, log_event

logger = logging.getLogger(__name__)

_RECORDS = TypeAdapter(tuple[TrackRecord, ...])


class TrackRecordRepository:
    """Loads and validates the track-record dataset once, then serves it."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._records: tuple[TrackRecord, ...] | None = None
        self._by_supplier: dict[str, TrackRecord] = {}

    def _load(self) -> tuple[TrackRecord, ...]:
        if self._records is not None:
            return self._records

        if not self._path.exists():
            # Not a failure: no dataset means no supplier has a history yet.
            self._records = ()
            self._by_supplier = {}
            return self._records

        raw = json.loads(self._path.read_text(encoding="utf-8"))
        records = _RECORDS.validate_python(raw["track_records"])

        duplicates = len(records) - len({record.supplier_id for record in records})
        if duplicates:
            raise ValueError(f"track-record dataset contains {duplicates} duplicate supplier id(s)")

        self._records = records
        self._by_supplier = {record.supplier_id: record for record in records}

        log_event(
            logger,
            Event.OFFERS_LOADED,
            "track-record dataset loaded",
            record_count=len(records),
            source=raw.get("_provenance", {}).get("data_source", "unknown"),
        )
        return records

    def all(self) -> tuple[TrackRecord, ...]:
        return self._load()

    def for_supplier(self, supplier_id: str) -> TrackRecord | None:
        """The supplier's history, or ``None`` when nothing is recorded.

        ``None`` rather than an empty record on purpose: the caller should have
        to decide how "no history" is presented, instead of receiving zeroes
        that look like measurements.
        """
        self._load()
        return self._by_supplier.get(supplier_id)
