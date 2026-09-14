"""The Quote Desk: capture replies, compare them, chase what is missing.

Deliberately off the graph. The workflow ends when a quotation request is
approved, and what follows happens on the supplier's timetable rather than the
buyer's - days later, in any order, sometimes never. Modelling that as more
graph nodes would put an interrupt in front of a step that may simply not
happen, and would move the point at which a project counts as complete.

So this is an ordinary service beside the workflow, reading the project's own
record for the request it is answering.
"""

from __future__ import annotations

import logging
from datetime import date

from app.domain.project import Project
from app.domain.quote import FollowUp, QuoteComparison, SupplierQuote
from app.llm.factory import LLMProvider
from app.logging_config import Event, log_event
from app.repositories.quote_repo import QuoteRepository
from app.security.guard import InjectionGuard
from app.services.quote_capture import CaptureOutcome, capture_quote
from app.services.quote_compare import compare
from app.services.quote_followup import build_followup

logger = logging.getLogger(__name__)


class NoRequestToAnswerError(RuntimeError):
    """The project has no approved quotation request, so nothing can be a reply to it."""


class QuoteDesk:
    """Everything that happens after a request has been sent."""

    def __init__(
        self,
        quotes: QuoteRepository,
        guard: InjectionGuard,
        provider: LLMProvider | None,
        *,
        today: date | None = None,
    ) -> None:
        self._quotes = quotes
        self._guard = guard
        self._provider = provider
        self._today = today

    # --------------------------------------------------------------- capture

    def capture(self, project: Project, raw_reply: str) -> CaptureOutcome:
        """Read one pasted reply into a stored quote.

        The supplier is taken from the project's own request rather than from
        the caller: a reply is an answer to a specific enquiry, and letting a
        request name its own sender would be letting pasted text decide whose
        words it is.
        """
        rfq = project.rfq
        if rfq is None or not rfq.approved:
            raise NoRequestToAnswerError(project.id)

        outcome = capture_quote(
            raw_reply=raw_reply,
            project_id=project.id,
            supplier_id=rfq.supplier_id,
            supplier_name=rfq.supplier_name,
            confirmations=tuple(rfq.confirmations_requested),
            received_on=self._today or date.today(),
            guard=self._guard,
            provider=self._provider,
        )
        self._quotes.save(outcome.quote)

        log_event(
            logger,
            Event.PROJECT_PERSISTED,
            "supplier reply captured",
            project_id=project.id,
            quote_id=outcome.quote.id,
            blocked=outcome.blocked,
            model_failed=outcome.model_failed,
            dropped_fields=list(outcome.quote.unverified_fields),
        )
        return outcome

    # ------------------------------------------------------------ correcting

    def confirm(
        self, quote_id: str, corrections: dict[str, object] | None = None
    ) -> SupplierQuote | None:
        """Apply a human's corrections and mark the quote checked.

        ``confirmed_by_human`` is set here and never accepted from a request, so
        the flag can only mean what it says. Corrected fields are recorded per
        field: fixing a lead time must not quietly relabel a price as
        human-checked.
        """
        quote = self._quotes.get(quote_id)
        if quote is None:
            return None

        changes = {key: value for key, value in (corrections or {}).items() if key != "id"}
        corrected = tuple(sorted(set(quote.corrected_fields) | set(changes)))
        updated = quote.model_copy(
            update={
                **changes,
                "corrected_fields": corrected,
                "confirmed_by_human": True,
            }
        )
        # Re-validated rather than trusted: a correction can contradict a model
        # rule (a sample cost with no sample), and that must fail here rather
        # than reach the comparison.
        validated = SupplierQuote.model_validate(updated.model_dump())
        return self._quotes.save(validated)

    def remove(self, quote_id: str) -> bool:
        return self._quotes.delete(quote_id)

    # ------------------------------------------------------------ comparison

    def quotes_for(self, project: Project) -> tuple[SupplierQuote, ...]:
        return self._quotes.for_project(project.id)

    def comparison(self, project: Project) -> QuoteComparison:
        rfq = project.rfq
        confirmations = tuple(rfq.confirmations_requested) if rfq else ()
        requested = rfq.quantity if rfq else None
        return compare(
            self._quotes.for_project(project.id),
            requested_quantity=requested,
            confirmations=confirmations,
        )

    def followups(self, project: Project) -> tuple[FollowUp, ...]:
        """One per supplier with something still to answer, and none for the
        suppliers who answered everything."""
        rfq = project.rfq
        if rfq is None:
            return ()
        drafts = (build_followup(project.id, rfq, row) for row in self.comparison(project).rows)
        return tuple(draft for draft in drafts if draft is not None)
