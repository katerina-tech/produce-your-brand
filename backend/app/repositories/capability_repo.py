"""What was read from a company's website, kept so a person can confirm it.

The extraction is the expensive half of the reviewer's pipeline - a fetch, a
model call, and a verifier pass per company - and its output is the thing a
human then judges. Both of those are reasons it belongs in the database rather
than in a file rebuilt by the next run.

Two tables, because a claim is a row somebody reads. The reading itself carries
the provenance - which pages, which day, how many claims the verifier deleted -
and the claims carry the words. A reading with no claims is still a reading:
"we looked at this site and it said nothing about what they make" is a finding,
and it is not the same as never having looked.

``confirmed_by_human`` is not stored here. It lives in ``partners.verified``,
because the thing a person confirms is a company, and one fact should not be
written in two places where they can disagree.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from typing import Any

from app.domain.capability import CapabilityClaim, SupplierCapabilities
from app.domain.enums import ProductionMethod
from app.repositories.database import Database

logger = logging.getLogger(__name__)


def _to_claim(row: Any) -> CapabilityClaim:
    record: dict[str, Any] = dict(row)
    method = record["method"]
    return CapabilityClaim(
        text=str(record["text"]),
        quote=str(record["quote"]),
        kind=str(record["kind"]),  # type: ignore[arg-type]
        method=ProductionMethod(str(method)) if method else None,
    )


class Reading:
    """One company's extraction, including the parts that failed.

    A thin carrier rather than a domain model: ``SupplierCapabilities`` is the
    thing the rest of the application reasons about, and why a reading came back
    thin is an operational question about the run, not a fact about the company.
    """

    def __init__(
        self,
        capabilities: SupplierCapabilities,
        *,
        blocked: bool = False,
        model_failed: bool = False,
    ) -> None:
        self.capabilities = capabilities
        self.blocked = blocked
        self.model_failed = model_failed

    @property
    def explanation(self) -> str:
        """Why this company has nothing to show, in words a person can act on."""
        if not self.capabilities.is_empty:
            return ""
        if self.blocked:
            return "The site's text was refused by the injection screen; nothing was read from it."
        if self.model_failed:
            return "The reading did not complete. Running the extraction again should fix it."
        return "The pages were read and said nothing specific about what this company makes."


class CapabilityRepository:
    """Extracted capabilities, in the same database as the companies they describe."""

    def __init__(self, connection: Database) -> None:
        self._connection = connection

    # ------------------------------------------------------------- writing

    def save(
        self,
        capabilities: SupplierCapabilities,
        *,
        blocked: bool = False,
        model_failed: bool = False,
    ) -> None:
        """Replace this company's reading with a newer one.

        Replace rather than append: a second run over the same site produces a
        better reading of the same company, not a second company. The claims go
        first so a reading that used to have six and now has two does not leave
        four behind.
        """
        now = datetime.now(UTC).isoformat(timespec="seconds")
        partner_id = capabilities.partner_id

        with self._connection:
            self._connection.execute(
                "DELETE FROM partner_claims WHERE partner_id = ?", (partner_id,)
            )
            self._connection.execute(
                "INSERT INTO partner_capabilities "
                "(partner_id, partner_name, source_urls, extracted_on, dropped_count, "
                " blocked, model_failed, created_at) "
                "VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(partner_id) DO UPDATE SET "
                "  partner_name = EXCLUDED.partner_name, "
                "  source_urls = EXCLUDED.source_urls, "
                "  extracted_on = EXCLUDED.extracted_on, "
                "  dropped_count = EXCLUDED.dropped_count, "
                "  blocked = EXCLUDED.blocked, "
                "  model_failed = EXCLUDED.model_failed",
                (
                    partner_id,
                    capabilities.partner_name,
                    json.dumps(list(capabilities.source_urls)),
                    capabilities.extracted_on.isoformat(),
                    capabilities.dropped_count,
                    1 if blocked else 0,
                    1 if model_failed else 0,
                    now,
                ),
            )
            for position, claim in enumerate(capabilities.claims):
                self._connection.execute(
                    "INSERT INTO partner_claims "
                    "(partner_id, position, text, quote, kind, method) VALUES (?,?,?,?,?,?)",
                    (
                        partner_id,
                        position,
                        claim.text,
                        claim.quote,
                        claim.kind,
                        claim.method.value if claim.method else None,
                    ),
                )

    # ------------------------------------------------------------- reading

    def _claims_for(self, partner_id: str) -> tuple[CapabilityClaim, ...]:
        rows = self._connection.execute(
            "SELECT text, quote, kind, method FROM partner_claims "
            "WHERE partner_id = ? ORDER BY position",
            (partner_id,),
        ).fetchall()
        return tuple(_to_claim(row) for row in rows)

    def _to_reading(self, row: Any) -> Reading:
        record: dict[str, Any] = dict(row)
        partner_id = str(record["partner_id"])
        return Reading(
            SupplierCapabilities(
                partner_id=partner_id,
                partner_name=str(record["partner_name"]),
                source_urls=tuple(json.loads(str(record["source_urls"]))),
                claims=self._claims_for(partner_id),
                extracted_on=date.fromisoformat(str(record["extracted_on"])),
                dropped_count=int(record["dropped_count"]),
                confirmed_by_human=bool(record.get("verified", False)),
            ),
            blocked=bool(record["blocked"]),
            model_failed=bool(record["model_failed"]),
        )

    def get(self, partner_id: str) -> Reading | None:
        """This company's reading, or None when nobody has looked at its site."""
        row = self._connection.execute(
            "SELECT c.*, p.verified FROM partner_capabilities c "
            "LEFT JOIN partners p ON p.id = c.partner_id WHERE c.partner_id = ?",
            (partner_id,),
        ).fetchone()
        return self._to_reading(row) if row else None

    def all(self) -> tuple[SupplierCapabilities, ...]:
        """Every reading, for building the search index."""
        rows = self._connection.execute(
            "SELECT c.*, p.verified FROM partner_capabilities c "
            "LEFT JOIN partners p ON p.id = c.partner_id ORDER BY LOWER(c.partner_name)"
        ).fetchall()
        return tuple(self._to_reading(row).capabilities for row in rows)

    def already_read(self) -> set[str]:
        """The companies a run can skip.

        Extraction costs a model call per company, and a run that crashed at
        company sixty should resume rather than pay for the first fifty-nine
        again.

        A reading whose model call failed is deliberately **not** skipped. That
        row records an outage - a dead key, an exhausted balance - and nothing
        about the company. Treating it as read would quietly write off every
        company a bad afternoon touched, and only a full ``--refresh`` of all
        ninety would ever bring them back.
        """
        rows = self._connection.execute(
            "SELECT partner_id FROM partner_capabilities WHERE model_failed = 0"
        ).fetchall()
        return {str(dict(row)["partner_id"]) for row in rows}

    def count(self) -> int:
        """Companies whose site has been read."""
        row = self._connection.execute("SELECT COUNT(*) AS n FROM partner_capabilities").fetchone()
        return int(dict(row)["n"])

    def with_claims_count(self) -> int:
        """Companies that actually said something. The number worth quoting."""
        row = self._connection.execute(
            "SELECT COUNT(DISTINCT partner_id) AS n FROM partner_claims"
        ).fetchone()
        return int(dict(row)["n"])

    def claim_count(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) AS n FROM partner_claims").fetchone()
        return int(dict(row)["n"])
