"""Compose the follow-up a partial reply earns.

Deterministic, like the outreach email and for the same reason: this text is
meant to leave for a third party, and a model asked to "write a polite chaser"
could soften a question until it stops being the question that was asked.

The questions are carried out of the original request by index. They are not
re-worded, not re-ordered and not summarised, so a supplier reading the
follow-up sees the same sentence they saw the first time - which is the
difference between a reminder and a new enquiry.
"""

from __future__ import annotations

from app.domain.quote import ComparisonRow, FollowUp
from app.domain.rfq import RFQ


def _asks_from_blockers(blockers: tuple[str, ...]) -> tuple[str, ...]:
    """Turn "why this could not be compared" into "what to ask for".

    Composed in Python from the blocker text rather than by a model. Each
    mapping is a fact about arithmetic, and a sentence that drifted from its
    blocker would ask the supplier for something other than what is missing.
    """
    asks: list[str] = []
    for blocker in blockers:
        lowered = blocker.lower()
        if "basis" in lowered:
            asks.append("Could you confirm whether the price is net or gross?")
        elif "not euros" in lowered:
            asks.append("Could you quote in euros, so we can compare like with like?")
        elif "asked for" in lowered:
            # The blocker already names both quantities, so it carries the
            # detail the supplier needs to answer precisely.
            asks.append(f"Could you quote for the quantity we asked about? ({blocker})")
        elif "no price" in lowered:
            asks.append("Could you give us a price, even an indicative one?")
        elif "no quantity" in lowered:
            asks.append("Could you say what quantity your price refers to?")
        else:
            asks.append(f"Could you help us with this: {blocker}")
    return tuple(asks)


def build_followup(project_id: str, rfq: RFQ, row: ComparisonRow) -> FollowUp | None:
    """The follow-up for one supplier, or ``None`` when there is nothing to ask.

    ``None`` rather than an empty, polite nudge: a supplier who answered
    everything and quoted comparably has earned not being chased, and a chaser
    with nothing in it costs goodwill the next enquiry will need.
    """
    questions = row.unanswered
    asks = _asks_from_blockers(row.blockers)
    if not questions and not asks:
        return None

    return FollowUp(
        project_id=project_id,
        supplier_id=rfq.supplier_id,
        supplier_name=row.supplier_name,
        subject=f"Re: {rfq.subject}",
        questions=questions,
        asks=asks,
    )
