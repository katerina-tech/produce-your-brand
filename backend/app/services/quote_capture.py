"""Reading one supplier reply: screen, extract, verify, and admit the gaps.

The buyer pastes a letter they already received. Three things then happen, in an
order that matters:

1. **Screen it.** A supplier's reply is authored outside this system, so it is
   assessed under :data:`Provenance.SUPPLIER_REPLY`, which fails closed. Note
   that this calls ``guard.assess`` rather than ``guard.screen``: ``screen``
   returns only the cleaned text and throws the blocked flag away, which is
   exactly the wrong shape for content that is allowed to be refused.
2. **Read it.** One model call, one closed schema, language only.
3. **Verify it.** Every figure must point at words that are really in the text,
   and :mod:`app.services.quote_verification` deletes the ones that cannot.

A blocked reply is not an error and not a loss: the text is kept verbatim, no
reading is attempted, and the buyer is told to enter the figures by hand. The
same is true when the model is unavailable. In both cases the correspondence
survives and only the convenience is lost, which is the right way round.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import PriceBasis, ProductionMethod
from app.domain.quote import FieldEvidence, SupplierQuote
from app.llm import prompts
from app.llm.factory import LLMError, LLMProvider
from app.logging_config import Event, log_event, redact_text
from app.security.guard import InjectionGuard, Provenance
from app.services.quote_verification import verify

logger = logging.getLogger(__name__)


class QuoteExtraction(BaseModel):
    """What the model is permitted to report about a reply.

    A strict subset of :class:`~app.domain.quote.SupplierQuote`. The omissions
    are the defence: there is no ``id``, ``project_id``, ``supplier_id``,
    ``is_demo``, ``received_on``, ``source_text`` or ``confirmed_by_human``,
    because identity and provenance are decided by code; and there is no
    ``total_price_eur``, because a total is arithmetic and arithmetic is not
    language work. A successful injection inside a supplier's letter has nothing
    here it could usefully set.
    """

    model_config = ConfigDict(extra="forbid")

    feasible: bool | None = None
    proposed_method: ProductionMethod | None = None
    method_deviation_note: str | None = None
    unit_price_eur: float | None = Field(default=None, ge=0)
    setup_cost_eur: float | None = Field(default=None, ge=0)
    sample_cost_eur: float | None = Field(default=None, ge=0)
    quoted_quantity: int | None = Field(default=None, ge=0)
    price_basis: PriceBasis = PriceBasis.UNSTATED
    price_is_estimate: bool | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    lead_time_days: int | None = Field(default=None, ge=0)
    lead_time_basis: str | None = None
    sample_available: bool | None = None
    accepts_customer_owned_goods: bool | None = None
    open_questions: tuple[str, ...] = ()
    source_language: str | None = None
    evidence: tuple[FieldEvidence, ...] = ()
    answered_indices: tuple[int, ...] = Field(
        default=(),
        description="Confirmations this reply answers, by index. Unanswered is the default.",
    )


@dataclass(frozen=True)
class CaptureOutcome:
    """The quote, plus why it may be thinner than the letter looks."""

    quote: SupplierQuote
    blocked: bool = False
    model_failed: bool = False

    @property
    def needs_manual_entry(self) -> bool:
        """Nothing was read, so the buyer has to type the figures themselves."""
        return self.blocked or self.model_failed


def capture_quote(
    *,
    raw_reply: str,
    project_id: str,
    supplier_id: str,
    supplier_name: str,
    confirmations: tuple[str, ...],
    received_on: date,
    guard: InjectionGuard,
    provider: LLMProvider | None,
    quote_id: str | None = None,
) -> CaptureOutcome:
    """Turn a pasted reply into a quote, or into an honest empty one."""
    screening = guard.assess(raw_reply, Provenance.SUPPLIER_REPLY)

    # Length and hash only. A supplier's reply is usually shorter than the
    # preview limit, so previewing it would copy a third party's whole letter
    # into logs that outlive the project.
    redacted = redact_text(raw_reply, preview=False)

    identity = {
        "id": quote_id or str(uuid.uuid4()),
        "project_id": project_id,
        "supplier_id": supplier_id,
        "supplier_name": supplier_name,
        "source_text": screening.text,
        "received_on": received_on,
        # A person pasted this out of their inbox, so it is a real reply by
        # definition - the flag means "seeded sample", and defaulting a
        # captured letter to True would mislabel every real one. Seeding
        # scripts set it themselves.
        "is_demo": False,
    }

    if screening.blocked:
        log_event(
            logger,
            Event.INJECTION_SUSPECTED,
            "supplier reply blocked; stored without a reading",
            level=logging.WARNING,
            project_id=project_id,
            supplier_id=supplier_id,
            signals=list(screening.signals),
            score=screening.score,
            **redacted,
        )
        return CaptureOutcome(
            quote=SupplierQuote(
                **identity,
                unanswered_indices=tuple(range(len(confirmations))),
            ),
            blocked=True,
        )

    if provider is None:
        return CaptureOutcome(
            quote=SupplierQuote(**identity, unanswered_indices=tuple(range(len(confirmations)))),
            model_failed=True,
        )

    try:
        extraction = provider.structured(
            QuoteExtraction,
            prompts.quote_extraction_messages(screening.text, confirmations),
            purpose="classifier",
        )
    except LLMError:
        log_event(
            logger,
            Event.TOOL_ERROR,
            "quote extraction failed; reply kept for manual entry",
            level=logging.WARNING,
            project_id=project_id,
            supplier_id=supplier_id,
            **redacted,
        )
        return CaptureOutcome(
            quote=SupplierQuote(**identity, unanswered_indices=tuple(range(len(confirmations)))),
            model_failed=True,
        )

    reported = extraction.model_dump(exclude={"evidence", "answered_indices"})
    checked = verify(reported, extraction.evidence, screening.text)

    values = dict(checked.values)
    # price_basis carries its own word for "unknown", so a dropped claim reverts
    # to UNSTATED rather than to None. The distinction is the whole reason the
    # enum has three members: an ungrounded "netto" must land on "not stated",
    # never on a null the model layer would refuse.
    if values.get("price_basis") is None:
        values["price_basis"] = PriceBasis.UNSTATED

    # A question counts as answered only on evidence that survived verification.
    # Inverting the default this way means silence can never retire a question:
    # the follow-up keeps asking until somebody demonstrably answers.
    answered = {index for index in extraction.answered_indices if 0 <= index < len(confirmations)}
    unanswered = tuple(index for index in range(len(confirmations)) if index not in answered)

    log_event(
        logger,
        Event.SUPPLIER_QUOTE_CAPTURED,
        "supplier reply read",
        project_id=project_id,
        supplier_id=supplier_id,
        dropped_fields=list(checked.dropped),
        answered=len(answered),
        asked=len(confirmations),
        **redacted,
    )

    return CaptureOutcome(
        quote=SupplierQuote(
            **identity,
            **values,
            evidence=extraction.evidence,
            unverified_fields=checked.dropped,
            unanswered_indices=unanswered,
        )
    )
