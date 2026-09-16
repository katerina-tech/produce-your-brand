"""Buyers' requests that are published, and nothing that is not.

One row per project, enforced by the database rather than remembered by the
code: ``project_id`` is UNIQUE, so publishing twice replaces the listing
instead of putting the same request on the board twice under two ids.

Unpublishing is a delete. There is no ``is_published`` flag, deliberately - a
row that is present but hidden is a row somebody will eventually read without
checking the flag, and this table's whole content is text a buyer agreed to
make public. Absent is the only safe shape for "taken down".
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from app.domain.demand import PublicRequest
from app.domain.enums import ProductCategory, ProductionMethod
from app.logging_config import Event, log_event
from app.repositories.database import Database

logger = logging.getLogger(__name__)

_COLUMNS = (
    "id, project_id, product, product_category, material, quantity, "
    "customer_owns_product, method, city, deadline, budget_eur, note, "
    "published_at, expires_on"
)


def _to_request(row: Any) -> PublicRequest:
    record: dict[str, Any] = dict(row)
    owns = record["customer_owns_product"]
    return PublicRequest(
        id=str(record["id"]),
        project_id=str(record["project_id"]),
        product=str(record["product"]),
        product_category=(
            ProductCategory(str(record["product_category"])) if record["product_category"] else None
        ),
        material=(record["material"] and str(record["material"])) or None,
        quantity=int(record["quantity"]) if record["quantity"] is not None else None,
        # Three-valued through the database too: "the buyer did not say whether
        # the goods already exist" is not "they do not", and a shop that will
        # not touch customer stock needs the difference.
        customer_owns_product=(None if owns is None else bool(owns)),
        method=(ProductionMethod(str(record["method"])) if record["method"] else None),
        city=str(record["city"] or ""),
        deadline=date.fromisoformat(str(record["deadline"])) if record["deadline"] else None,
        budget_eur=(float(record["budget_eur"]) if record["budget_eur"] is not None else None),
        note=str(record["note"] or ""),
        published_at=datetime.fromisoformat(str(record["published_at"])),
        expires_on=date.fromisoformat(str(record["expires_on"])),
    )


class DemandRepository:
    """The public board of buyers' requests."""

    def __init__(self, connection: Database) -> None:
        self._connection = connection

    # ------------------------------------------------------------- writing

    def publish(self, request: PublicRequest) -> PublicRequest:
        """Put a request on the board, replacing this project's earlier listing.

        Returns what is now live - which is the listing's own id, kept across a
        re-publish so a link somebody already shared does not break when the
        buyer edits their note.
        """
        existing = self.for_project(request.project_id)
        live = request if existing is None else request.model_copy(update={"id": existing.id})

        with self._connection:
            self._connection.execute(
                f"INSERT INTO public_requests ({_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(project_id) DO UPDATE SET "
                "  product = EXCLUDED.product, "
                "  product_category = EXCLUDED.product_category, "
                "  material = EXCLUDED.material, quantity = EXCLUDED.quantity, "
                "  customer_owns_product = EXCLUDED.customer_owns_product, "
                "  method = EXCLUDED.method, city = EXCLUDED.city, "
                "  deadline = EXCLUDED.deadline, budget_eur = EXCLUDED.budget_eur, "
                "  note = EXCLUDED.note, published_at = EXCLUDED.published_at, "
                "  expires_on = EXCLUDED.expires_on",
                (
                    live.id,
                    live.project_id,
                    live.product,
                    live.product_category.value if live.product_category else None,
                    live.material,
                    live.quantity,
                    (
                        None
                        if live.customer_owns_product is None
                        else int(live.customer_owns_product)
                    ),
                    live.method.value if live.method else None,
                    live.city,
                    live.deadline.isoformat() if live.deadline else None,
                    live.budget_eur,
                    live.note,
                    live.published_at.isoformat(),
                    live.expires_on.isoformat(),
                ),
            )

        log_event(
            logger,
            Event.REQUEST_PUBLISHED,
            "request published to the board",
            project_id=live.project_id,
            request_id=live.id,
            shows_budget=live.budget_eur is not None,
        )
        return live

    def withdraw(self, project_id: str) -> bool:
        """Take a project's listing down. Returns whether there was one.

        A delete rather than a flag: everything in this table is text somebody
        agreed to publish, and "present but hidden" is a state a future reader
        will eventually get wrong.
        """
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM public_requests WHERE project_id = ?", (project_id,)
            )
        if cursor.rowcount:
            log_event(
                logger,
                Event.REQUEST_WITHDRAWN,
                "request withdrawn from the board",
                project_id=project_id,
            )
        return bool(cursor.rowcount)

    # ------------------------------------------------------------- reading

    def for_project(self, project_id: str) -> PublicRequest | None:
        """This project's listing, for the buyer's own screen."""
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM public_requests WHERE project_id = ?", (project_id,)
        ).fetchone()
        return _to_request(row) if row else None

    def get(self, request_id: str) -> PublicRequest | None:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM public_requests WHERE id = ?", (request_id,)
        ).fetchone()
        return _to_request(row) if row else None

    def search(
        self,
        *,
        query: str | None = None,
        method: ProductionMethod | None = None,
        customer_owned: bool = False,
        today: date | None = None,
        limit: int = 100,
    ) -> tuple[PublicRequest, ...]:
        """Open requests, soonest deadline first.

        Expired listings are never returned. Unlike a tender - where an undated
        notice is still a real notice - every listing here has an end date,
        because one was given or one was assigned. A board of forgotten requests
        is worse than a small one: a company that answers a dead request once
        does not come back.
        """
        clauses = ["expires_on >= ?"]
        params: list[object] = [(today or datetime.now(UTC).date()).isoformat()]

        if query and query.strip():
            needle = f"%{query.strip().lower()}%"
            clauses.append(
                "(LOWER(product) LIKE ? OR LOWER(COALESCE(material, '')) LIKE ? "
                "OR LOWER(note) LIKE ?)"
            )
            params += [needle, needle, needle]
        if method is not None:
            clauses.append("method = ?")
            params.append(method.value)
        if customer_owned:
            clauses.append("customer_owns_product = 1")

        params.append(limit)
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM public_requests WHERE {' AND '.join(clauses)} "
            "ORDER BY COALESCE(deadline, expires_on), published_at DESC LIMIT ?",
            tuple(params),
        ).fetchall()
        return tuple(_to_request(row) for row in rows)

    def count_open(self, today: date | None = None) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS n FROM public_requests WHERE expires_on >= ?",
            ((today or datetime.now(UTC).date()).isoformat(),),
        ).fetchone()
        return int(dict(row)["n"])

    def purge_expired(self, today: date | None = None) -> int:
        """Delete listings whose end date has passed. Returns how many.

        Run at startup. An expired listing is already invisible to the search,
        so this is not about correctness - it is about not keeping a buyer's
        published text one day longer than they agreed to.
        """
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM public_requests WHERE expires_on < ?",
                ((today or datetime.now(UTC).date()).isoformat(),),
            )
        removed = cursor.rowcount or 0
        if removed:
            log_event(
                logger,
                Event.REQUESTS_EXPIRED,
                "expired requests removed from the board",
                removed=removed,
            )
        return removed
