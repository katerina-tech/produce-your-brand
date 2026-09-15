"""The real-company directory, in the database.

It started as a file read straight off disk, which was right while the survey
was the only thing that ever wrote to it. It is not right any more: the next
step is confirming what these companies can do, and a confirmation is a fact a
person establishes - it cannot live in a file the next survey overwrites.

So the file is now **seed**, not storage. It fills an empty table once; after
that the database owns the rows, and a re-survey is an explicit act rather than
something a deployment does to somebody's work by restarting.

Filtering is SQL rather than Python because the database is where 135 rows
become 5,000 without anybody rewriting this module. The survey metadata -
attribution, which categories came back short - stays in the file: it describes
how the data was gathered, not the companies, and one row of provenance does
not want a table.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.domain.enums import ProductionMethod
from app.domain.partner import Partner, PartnerDirectory
from app.logging_config import Event, log_event
from app.repositories.database import Database

logger = logging.getLogger(__name__)

_COLUMNS = (
    "id, name, source, verified, address, city, district, borough, "
    "category, category_label, lat, lon, website, email, implied_method, phone"
)


def _to_partner(row: Any) -> Partner:
    """One row to a Partner. Both drivers hand back a mapping, so this is the
    same code on either database."""
    record: dict[str, Any] = dict(row)
    return Partner(
        id=str(record["id"]),
        name=str(record["name"]),
        source=str(record["source"]),
        verified=bool(record["verified"]),
        address=(record["address"] and str(record["address"])) or None,
        city=str(record["city"]),
        district=(record["district"] and str(record["district"])) or None,
        borough=(record["borough"] and str(record["borough"])) or None,
        category=(record["category"] and str(record["category"])) or None,
        category_label=(record["category_label"] and str(record["category_label"])) or None,
        lat=float(record["lat"]) if record["lat"] is not None else None,
        lon=float(record["lon"]) if record["lon"] is not None else None,
        website=(record["website"] and str(record["website"])) or None,
        email=(record["email"] and str(record["email"])) or None,
        phone=(record["phone"] and str(record["phone"])) or None,
        implied_method=(
            ProductionMethod(str(record["implied_method"])) if record["implied_method"] else None
        ),
    )


class PartnerRepository:
    """Companies, in the same database as the projects that will reference them."""

    def __init__(self, connection: Database, seed_file: Path | None = None) -> None:
        self._connection = connection
        self._seed_file = seed_file

    # ------------------------------------------------------------- seeding

    def seed_missing(self) -> int:
        """Insert the survey's companies that this table does not have yet.

        Returns how many were added. Existing rows are never touched - that is
        ``ON CONFLICT DO NOTHING``, not a guard that has to be remembered - so
        a deployment restarting, or a re-survey, cannot undo a capability
        somebody confirmed by hand.

        This used to refuse to run at all once the table had anything in it,
        which was safe and also wrong: the survey found a new Berlin business
        and nothing would ever have brought it in. Adding what is missing is
        the behaviour that was actually wanted; leaving existing rows alone is
        the part that mattered.
        """
        if self._seed_file is None or not self._seed_file.is_file():
            return 0

        raw = json.loads(self._seed_file.read_text(encoding="utf-8"))
        now = datetime.now(UTC).isoformat(timespec="seconds")
        inserted = 0

        with self._connection:
            for item in raw.get("partners", []):
                cursor = self._connection.execute(
                    f"INSERT INTO partners ({_COLUMNS}, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO NOTHING",
                    (
                        item["osm_id"],
                        item["name"],
                        (raw.get("source") and "openstreetmap") or "unknown",
                        0,
                        item.get("address"),
                        item.get("city") or "Berlin",
                        item.get("district"),
                        item.get("borough"),
                        item.get("osm_category"),
                        item.get("category_label"),
                        item.get("lat"),
                        item.get("lon"),
                        item.get("website"),
                        item.get("email"),
                        item.get("method_implied_by_tag"),
                        item.get("phone"),
                        now,
                    ),
                )
                # Counted from the statement rather than the loop: with
                # ON CONFLICT DO NOTHING, "attempted" and "inserted" differ on
                # every run after the first, and reporting the wrong one would
                # log 136 new companies each time a deployment restarts.
                inserted += cursor.rowcount or 0

        if inserted:
            log_event(
                logger,
                Event.SUPPLIER_CANDIDATES_FOUND,
                "companies added from the survey",
                partner_count=inserted,
                source=str(self._seed_file.name),
            )
        return inserted

    # ------------------------------------------------------------- reading

    def directory(self) -> PartnerDirectory:
        """The companies, plus the provenance of the survey they came from."""
        metadata: dict[str, Any] = {}
        if self._seed_file is not None and self._seed_file.is_file():
            metadata = json.loads(self._seed_file.read_text(encoding="utf-8"))

        return PartnerDirectory(
            partners=self.all(),
            attribution=str(metadata.get("attribution", "")),
            source=str(metadata.get("source", "")),
            area=str(metadata.get("area", "")),
            incomplete_categories=tuple(metadata.get("incomplete_categories") or ()),
        )

    def all(self) -> tuple[Partner, ...]:
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM partners ORDER BY LOWER(name)"
        ).fetchall()
        return tuple(_to_partner(row) for row in rows)

    def get(self, partner_id: str) -> Partner | None:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM partners WHERE id = ?", (partner_id,)
        ).fetchone()
        return _to_partner(row) if row else None

    def search(
        self,
        *,
        query: str | None = None,
        method: ProductionMethod | None = None,
        borough: str | None = None,
        category: str | None = None,
        with_email: bool = False,
        limit: int = 200,
    ) -> tuple[Partner, ...]:
        """Filter in SQL.

        ``with_email`` is the question actually being asked of this data: which
        of these can I write to today. Name and address are searched together,
        because "Kreuzberg" is how somebody looks for a printer near them and it
        lives in the address rather than the name.
        """
        clauses: list[str] = []
        params: list[object] = []

        if query and query.strip():
            needle = f"%{query.strip().lower()}%"
            clauses.append("(LOWER(name) LIKE ? OR LOWER(COALESCE(address, '')) LIKE ?)")
            params += [needle, needle]
        if method is not None:
            clauses.append("implied_method = ?")
            params.append(method.value)
        if borough and borough.strip():
            clauses.append("borough = ?")
            params.append(borough.strip())
        if category and category.strip():
            clauses.append("category = ?")
            params.append(category.strip())
        if with_email:
            clauses.append("email IS NOT NULL AND email <> ''")

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM partners{where} ORDER BY LOWER(name) LIMIT ?", tuple(params)
        ).fetchall()
        return tuple(_to_partner(row) for row in rows)

    def count(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) AS n FROM partners").fetchone()
        return int(dict(row)["n"])

    def contactable_count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS n FROM partners WHERE email IS NOT NULL AND email <> ''"
        ).fetchone()
        return int(dict(row)["n"])

    # ------------------------------------------------------- survey backfill

    def fill_in_districts(self) -> int:
        """Copy districts from the survey file onto rows that have none.

        The rule this follows is the one the seeding already sets: **facts the
        survey gathered flow from the file into the database; facts a person
        established live only in the database.** Where a business sits is the
        first kind, so a table seeded before the enrichment existed can be
        brought up to date without a re-seed - and without touching anybody's
        confirmation, which this statement cannot reach.
        """
        if self._seed_file is None or not self._seed_file.is_file():
            return 0

        raw = json.loads(self._seed_file.read_text(encoding="utf-8"))
        filled = 0
        with self._connection:
            for item in raw.get("partners", []):
                if not item.get("district") and not item.get("borough"):
                    continue
                cursor = self._connection.execute(
                    "UPDATE partners SET district = ?, borough = ? "
                    "WHERE id = ? AND district IS NULL",
                    (item.get("district"), item.get("borough"), item["osm_id"]),
                )
                filled += cursor.rowcount or 0
                if item.get("osm_category"):
                    self._connection.execute(
                        "UPDATE partners SET category = ?, category_label = ? "
                        "WHERE id = ? AND category IS NULL",
                        (item["osm_category"], item.get("category_label"), item["osm_id"]),
                    )

        if filled:
            log_event(
                logger,
                Event.SUPPLIER_CANDIDATES_FOUND,
                "districts filled in from the survey",
                partner_count=filled,
                source=str(self._seed_file.name),
            )
        return filled

    def categories(self) -> tuple[tuple[str, str, int], ...]:
        """Each kind of business present, with its label and how many, most first.

        ``(tag, label, count)``. The tag travels with the label so the filter's
        claim stays checkable against the public map it came from.
        """
        rows = self._connection.execute(
            "SELECT category, category_label, COUNT(*) AS n FROM partners "
            "WHERE category IS NOT NULL AND category <> '' "
            "GROUP BY category, category_label ORDER BY n DESC, category_label"
        ).fetchall()
        return tuple(
            (
                str(dict(row)["category"]),
                str(dict(row)["category_label"] or dict(row)["category"]),
                int(dict(row)["n"]),
            )
            for row in rows
        )

    def boroughs(self) -> tuple[tuple[str, int], ...]:
        """Each Bezirk that has businesses, with how many, most first.

        Counted rather than listed from a constant: a filter offering a borough
        with nothing behind it is a filter that answers "nothing here" to a
        question the data never had.
        """
        rows = self._connection.execute(
            "SELECT borough, COUNT(*) AS n FROM partners "
            "WHERE borough IS NOT NULL AND borough <> '' "
            "GROUP BY borough ORDER BY n DESC, borough"
        ).fetchall()
        return tuple((str(dict(row)["borough"]), int(dict(row)["n"])) for row in rows)

    # ------------------------------------------------------------- writing

    def mark_verified(self, partner_id: str, verified: bool = True) -> bool:
        """Record that a person confirmed this company. Returns whether it existed.

        The reason the file stopped being storage. A confirmation is somebody's
        work, and it has to survive the next survey.
        """
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE partners SET verified = ? WHERE id = ?",
                (1 if verified else 0, partner_id),
            )
        return cursor.rowcount == 1
