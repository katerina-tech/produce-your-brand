"""Supplier data access - the single source of supplier truth.

The dataset is read-only reference data of two dozen records, so it lives in
``data/suppliers.json`` rather than a table. One file means a JSON copy and a
database copy cannot drift apart. This class hides that choice: moving to a table
later changes this module only.

Filtering deliberately does *not* live here. Structural search is business logic
and belongs in ``app.services.matching``, which keeps the dependency direction
one-way (services never import repositories' logic, and repositories never
import services).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import TypeAdapter

from app.domain.supplier import Supplier
from app.logging_config import Event, log_event

logger = logging.getLogger(__name__)

_SUPPLIERS = TypeAdapter(tuple[Supplier, ...])


class SupplierRepository:
    """Loads and validates the supplier dataset once, then serves it in memory."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._suppliers: tuple[Supplier, ...] | None = None
        self._by_id: dict[str, Supplier] = {}

    def _load(self) -> tuple[Supplier, ...]:
        """Parse and validate on first use.

        Validation happens here rather than at the point of use, so a malformed
        dataset fails loudly at startup instead of producing a silently empty
        match list later.
        """
        if self._suppliers is not None:
            return self._suppliers

        raw = json.loads(self._path.read_text(encoding="utf-8"))
        suppliers = _SUPPLIERS.validate_python(raw["suppliers"])

        duplicates = len(suppliers) - len({supplier.id for supplier in suppliers})
        if duplicates:
            raise ValueError(f"supplier dataset contains {duplicates} duplicate id(s)")

        self._suppliers = suppliers
        self._by_id = {supplier.id: supplier for supplier in suppliers}
        log_event(
            logger,
            Event.SUPPLIER_CANDIDATES_FOUND,
            "supplier dataset loaded",
            supplier_count=len(suppliers),
            source=raw.get("_provenance", {}).get("data_source", "unknown"),
        )
        return suppliers

    def all(self) -> tuple[Supplier, ...]:
        return self._load()

    def get(self, supplier_id: str) -> Supplier | None:
        """Look up by id. Returns None for unknown ids rather than raising.

        This is the check that makes invented suppliers impossible: any id an LLM
        produces is resolved through here, and an unknown one is dropped.
        """
        self._load()
        return self._by_id.get(supplier_id)

    def exists(self, supplier_id: str) -> bool:
        return self.get(supplier_id) is not None

    def count(self) -> int:
        return len(self._load())
