"""Captured supplier replies, stored whole.

The quote is written as JSON rather than spread across columns, and that is a
decision rather than laziness: the record's value is that every figure carries
the words it was read from, and a column layout would either lose the evidence
or turn one reply into three tables. Read back through the same Pydantic model
that wrote it, so a record that no longer validates is a loud failure instead
of a half-populated object.

The reply text is personal-ish data - a named supplier's own words, sometimes
with a signature - so it lives under the project it belongs to and is deleted
with it, by the foreign key rather than by anybody remembering.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime

from app.domain.quote import SupplierQuote
from app.logging_config import Event, log_event

logger = logging.getLogger(__name__)


class QuoteRepository:
    """Quotes, in the same SQLite database as the projects they answer."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def save(self, quote: SupplierQuote) -> SupplierQuote:
        """Insert or replace. Replacing matters: the confirm gate rewrites a
        quote after a human corrects a field, and that is the same quote rather
        than a second one."""
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO project_quotes (id, project_id, quote_json, created_at)
                VALUES (?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET quote_json = excluded.quote_json
                """,
                (
                    quote.id,
                    quote.project_id,
                    quote.model_dump_json(),
                    datetime.now(UTC).isoformat(timespec="seconds"),
                ),
            )
        log_event(
            logger,
            Event.PROJECT_PERSISTED,
            "supplier quote stored",
            project_id=quote.project_id,
            quote_id=quote.id,
            confirmed=quote.confirmed_by_human,
        )
        return quote

    def for_project(self, project_id: str) -> tuple[SupplierQuote, ...]:
        """Every reply captured against a project, oldest first - the order they
        arrived is the order a buyer remembers them in."""
        rows = self._connection.execute(
            "SELECT quote_json FROM project_quotes WHERE project_id = ? ORDER BY created_at, id",
            (project_id,),
        ).fetchall()
        return tuple(SupplierQuote.model_validate_json(row["quote_json"]) for row in rows)

    def get(self, quote_id: str) -> SupplierQuote | None:
        row = self._connection.execute(
            "SELECT quote_json FROM project_quotes WHERE id = ?", (quote_id,)
        ).fetchone()
        return SupplierQuote.model_validate_json(row["quote_json"]) if row else None

    def delete(self, quote_id: str) -> bool:
        """Remove one captured reply. Returns whether there was one to remove.

        Worth having rather than leaving to a database console: a reply pasted
        into the wrong project is somebody else's business correspondence
        sitting where it does not belong.
        """
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM project_quotes WHERE id = ?", (quote_id,)
            )
        return cursor.rowcount == 1

    def count(self, project_id: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS n FROM project_quotes WHERE project_id = ?", (project_id,)
        ).fetchone()
        return int(row["n"])


def as_json(quote: SupplierQuote) -> dict[str, object]:
    """The record as a plain dict, for an event payload."""
    return dict(json.loads(quote.model_dump_json()))
