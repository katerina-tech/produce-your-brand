"""Who speaks for which company.

One row per company, enforced by the database: ``partner_id`` is the primary
key, so a listing cannot be claimed by two accounts at once. The first claimer
holds it while their claim is live; once verified they hold it until somebody
takes it away deliberately.

An unverified claim expires. Without that, starting a claim and never finishing
it would be enough to hold a real business's listing for ever - which is a
denial of service dressed as a feature.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.domain.company import CompanyClaim
from app.logging_config import Event, log_event
from app.repositories.database import Database

logger = logging.getLogger(__name__)

_COLUMNS = "partner_id, user_id, token, created_at, verified_at"


def _to_claim(row: Any) -> CompanyClaim:
    record: dict[str, Any] = dict(row)
    verified = record["verified_at"]
    return CompanyClaim(
        partner_id=str(record["partner_id"]),
        user_id=str(record["user_id"]),
        token=str(record["token"]),
        created_at=datetime.fromisoformat(str(record["created_at"])),
        verified_at=datetime.fromisoformat(str(verified)) if verified else None,
    )


class ClaimRepository:
    """Company claims, live and expired."""

    def __init__(self, connection: Database) -> None:
        self._connection = connection

    # ------------------------------------------------------------- writing

    def start(self, claim: CompanyClaim) -> None:
        """Record an attempt, replacing any expired one on the same company."""
        with self._connection:
            self._connection.execute(
                f"INSERT INTO company_claims ({_COLUMNS}) VALUES (?,?,?,?,?) "
                "ON CONFLICT(partner_id) DO UPDATE SET "
                "  user_id = EXCLUDED.user_id, token = EXCLUDED.token, "
                "  created_at = EXCLUDED.created_at, verified_at = EXCLUDED.verified_at",
                (
                    claim.partner_id,
                    claim.user_id,
                    claim.token,
                    claim.created_at.isoformat(),
                    claim.verified_at.isoformat() if claim.verified_at else None,
                ),
            )
        log_event(
            logger,
            Event.COMPANY_CLAIM_STARTED,
            "company claim started",
            partner_id=claim.partner_id,
        )

    def mark_verified(self, partner_id: str, moment: datetime | None = None) -> bool:
        """Accept the proof. Returns whether there was an outstanding claim."""
        when = (moment or datetime.now(UTC)).isoformat()
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE company_claims SET verified_at = ? "
                "WHERE partner_id = ? AND verified_at IS NULL",
                (when, partner_id),
            )
        if cursor.rowcount:
            log_event(
                logger,
                Event.COMPANY_CLAIM_VERIFIED,
                "company claim verified",
                partner_id=partner_id,
            )
        return bool(cursor.rowcount)

    def release(self, partner_id: str) -> bool:
        """Give the listing up. A delete, so nothing lingers half-owned."""
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM company_claims WHERE partner_id = ?", (partner_id,)
            )
        return bool(cursor.rowcount)

    # ------------------------------------------------------------- reading

    def for_partner(self, partner_id: str) -> CompanyClaim | None:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM company_claims WHERE partner_id = ?", (partner_id,)
        ).fetchone()
        return _to_claim(row) if row else None

    def for_user(self, user_id: str) -> CompanyClaim | None:
        """The company this account speaks for, verified or still proving it."""
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM company_claims WHERE user_id = ? "
            "ORDER BY CASE WHEN verified_at IS NULL THEN 1 ELSE 0 END, created_at DESC",
            (user_id,),
        ).fetchone()
        return _to_claim(row) if row else None

    def speaks_for(self, user_id: str, partner_id: str) -> bool:
        """Whether this account may act as this company.

        The question every write about a named business has to ask, in one
        place so no endpoint has to assemble the answer for itself.
        """
        claim = self.for_partner(partner_id)
        return claim is not None and claim.is_verified and claim.user_id == user_id

    def verified_count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS n FROM company_claims WHERE verified_at IS NOT NULL"
        ).fetchone()
        return int(dict(row)["n"])
