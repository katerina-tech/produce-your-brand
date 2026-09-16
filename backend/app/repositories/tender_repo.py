"""Public contract notices, in the same database as the companies that could bid.

Upsert rather than insert: a notice is re-published when it is corrected, and
the corrected version is the one worth showing. Nothing a person does lives on
a tender row, so there is no confirmation here to protect - unlike the partner
table, this one may be overwritten freely by a later import.

Filtering is SQL for the same reason it is in the partner repository: a month
of German notices is 23,000 rows before the CPV filter and a few hundred after,
and a year of those is where paging in Python stops being honest.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from app.domain.enums import ProductionMethod
from app.domain.tender import Tender
from app.logging_config import Event, log_event
from app.repositories.database import Database

logger = logging.getLogger(__name__)

_COLUMNS = (
    "id, title, description, cpv, family_prefix, family_label, implied_method, "
    "buyer, buyer_city, place_city, place_region, estimated_value, currency, "
    "published_on, deadline, suitable_for_smes, procedure_type, notice_type, source_url"
)


def _to_tender(row: Any) -> Tender:
    record: dict[str, Any] = dict(row)
    smes = record["suitable_for_smes"]
    deadline = record["deadline"]
    return Tender(
        id=str(record["id"]),
        title=str(record["title"]),
        description=str(record["description"] or ""),
        cpv=str(record["cpv"]),
        family_prefix=str(record["family_prefix"]),
        family_label=str(record["family_label"]),
        implied_method=(
            ProductionMethod(str(record["implied_method"])) if record["implied_method"] else None
        ),
        buyer=str(record["buyer"] or ""),
        buyer_city=str(record["buyer_city"] or ""),
        place_city=str(record["place_city"] or ""),
        place_region=str(record["place_region"] or ""),
        estimated_value=(
            float(record["estimated_value"]) if record["estimated_value"] is not None else None
        ),
        currency=str(record["currency"] or ""),
        published_on=date.fromisoformat(str(record["published_on"])),
        deadline=datetime.fromisoformat(str(deadline)) if deadline else None,
        # Three-valued all the way to the screen: the buyer not saying is not
        # the buyer saying no, and an INTEGER column that lost that would make
        # "we don't know" indistinguishable from "not for you".
        suitable_for_smes=(None if smes is None else bool(smes)),
        procedure_type=str(record["procedure_type"] or ""),
        notice_type=str(record["notice_type"] or ""),
        source_url=str(record["source_url"] or ""),
    )


class TenderRepository:
    """Notices, filtered the way somebody deciding whether to bid would filter."""

    def __init__(self, connection: Database) -> None:
        self._connection = connection

    # ------------------------------------------------------------- writing

    def save_all(self, tenders: tuple[Tender, ...]) -> int:
        """Store an import. Returns how many rows were new.

        Corrections overwrite: a notice republished with a later deadline is the
        same contract, and keeping the stale one would send somebody to a
        closed tender.
        """
        if not tenders:
            return 0

        now = datetime.now(UTC).isoformat(timespec="seconds")
        before = self.count()

        with self._connection:
            for tender in tenders:
                self._connection.execute(
                    f"INSERT INTO tenders ({_COLUMNS}, imported_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "  title = EXCLUDED.title, description = EXCLUDED.description, "
                    "  cpv = EXCLUDED.cpv, family_prefix = EXCLUDED.family_prefix, "
                    "  family_label = EXCLUDED.family_label, "
                    "  implied_method = EXCLUDED.implied_method, "
                    "  buyer = EXCLUDED.buyer, buyer_city = EXCLUDED.buyer_city, "
                    "  place_city = EXCLUDED.place_city, place_region = EXCLUDED.place_region, "
                    "  estimated_value = EXCLUDED.estimated_value, currency = EXCLUDED.currency, "
                    "  published_on = EXCLUDED.published_on, deadline = EXCLUDED.deadline, "
                    "  suitable_for_smes = EXCLUDED.suitable_for_smes, "
                    "  procedure_type = EXCLUDED.procedure_type, "
                    "  notice_type = EXCLUDED.notice_type, source_url = EXCLUDED.source_url",
                    (
                        tender.id,
                        tender.title,
                        tender.description,
                        tender.cpv,
                        tender.family_prefix,
                        tender.family_label,
                        tender.implied_method.value if tender.implied_method else None,
                        tender.buyer,
                        tender.buyer_city,
                        tender.place_city,
                        tender.place_region,
                        tender.estimated_value,
                        tender.currency,
                        tender.published_on.isoformat(),
                        tender.deadline.isoformat() if tender.deadline else None,
                        (
                            None
                            if tender.suitable_for_smes is None
                            else int(tender.suitable_for_smes)
                        ),
                        tender.procedure_type,
                        tender.notice_type,
                        tender.source_url,
                        now,
                    ),
                )

        added = self.count() - before
        log_event(
            logger,
            Event.SUPPLIER_CANDIDATES_FOUND,
            "tenders imported",
            seen=len(tenders),
            added=added,
        )
        return added

    # ------------------------------------------------------------- reading

    def get(self, tender_id: str) -> Tender | None:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM tenders WHERE id = ?", (tender_id,)
        ).fetchone()
        return _to_tender(row) if row else None

    def search(
        self,
        *,
        query: str | None = None,
        family: str | None = None,
        berlin_only: bool = False,
        smes_only: bool = False,
        open_only: bool = True,
        today: date | None = None,
        limit: int = 100,
    ) -> tuple[Tender, ...]:
        """The notices somebody could still act on, soonest deadline first.

        ``open_only`` defaults to True because a board of closed tenders is a
        board nobody can use. A notice with no stated deadline counts as open:
        hiding it because a field was empty would be this product deciding a
        contract is closed on no evidence.
        """
        clauses: list[str] = []
        params: list[object] = []

        if query and query.strip():
            needle = f"%{query.strip().lower()}%"
            clauses.append(
                "(LOWER(title) LIKE ? OR LOWER(description) LIKE ? OR LOWER(buyer) LIKE ?)"
            )
            params += [needle, needle, needle]
        if family and family.strip():
            clauses.append("family_prefix = ?")
            params.append(family.strip())
        if berlin_only:
            # By NUTS, with the city string as a second chance: a buyer writes
            # "Berlin-Mitte", "10115 Berlin" or nothing, and DE3 is the same
            # answer every time.
            clauses.append("(place_region LIKE 'DE3%' OR LOWER(place_city) LIKE 'berlin%')")
        if smes_only:
            clauses.append("suitable_for_smes = 1")
        if open_only:
            clauses.append("(deadline IS NULL OR deadline >= ?)")
            params.append((today or datetime.now(UTC).date()).isoformat())

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM tenders{where} "
            # Nulls last, so a notice that states when it closes outranks one
            # that does not - a date is more actionable than its absence.
            "ORDER BY CASE WHEN deadline IS NULL THEN 1 ELSE 0 END, deadline, published_on DESC "
            "LIMIT ?",
            tuple(params),
        ).fetchall()
        return tuple(_to_tender(row) for row in rows)

    def families(self) -> tuple[tuple[str, str, int], ...]:
        """Each family with something in it, as ``(prefix, label, count)``."""
        rows = self._connection.execute(
            "SELECT family_prefix, family_label, COUNT(*) AS n FROM tenders "
            "GROUP BY family_prefix, family_label ORDER BY n DESC, family_label"
        ).fetchall()
        return tuple(
            (str(dict(r)["family_prefix"]), str(dict(r)["family_label"]), int(dict(r)["n"]))
            for r in rows
        )

    def count(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) AS n FROM tenders").fetchone()
        return int(dict(row)["n"])

    def berlin_count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS n FROM tenders "
            "WHERE place_region LIKE 'DE3%' OR LOWER(place_city) LIKE 'berlin%'"
        ).fetchone()
        return int(dict(row)["n"])

    def newest_published(self) -> date | None:
        """The most recent publication day already held, or None when empty.

        What a scheduled catch-up starts from. Reading the data rather than
        counting back a fixed number of days means a run that was skipped, or a
        month that is 31 days rather than 30, cannot leave a hole nobody
        notices.
        """
        row = self._connection.execute("SELECT MAX(published_on) AS newest FROM tenders").fetchone()
        newest = dict(row)["newest"]
        return date.fromisoformat(str(newest)) if newest else None

    def latest_import(self) -> str:
        """When the newest row arrived, for a page that should say how fresh it is."""
        row = self._connection.execute("SELECT MAX(imported_at) AS latest FROM tenders").fetchone()
        return str(dict(row)["latest"] or "")
