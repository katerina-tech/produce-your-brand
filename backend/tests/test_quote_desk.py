"""The Quote Desk end to end: capture, correct, compare, chase.

The reply used throughout is the one a real Berlin print shop would send - German,
prose, hedged, and answering only some of what it was asked. That is what the
desk exists for; a tidy reply would not test anything.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.domain.enums import PriceBasis, ProductionMethod
from app.domain.project import Project
from app.domain.quote import FieldEvidence
from app.domain.rfq import RFQ
from app.repositories import db
from app.repositories.quote_repo import QuoteRepository
from app.security.guard import build_guard
from app.services.quote_capture import QuoteExtraction
from app.services.quote_desk import NoRequestToAnswerError, QuoteDesk
from tests.fakes import ScriptedProvider

REPLY = (
    "Guten Tag, machbar. Fuer 100 Stueck kommen wir auf ca. 8,50 pro Stueck netto, "
    "Lieferzeit 14 Tage ab Freigabe. Siebdruck geht auf PVC nicht, wir wuerden "
    "Transferdruck vorschlagen."
)

CONFIRMATIONS = (
    "Feasibility on PVC",
    "Lead time for 100 units",
    "Whether you accept customer-supplied goods",
)

TODAY = date(2026, 9, 14)


def _extraction(**overrides: object) -> QuoteExtraction:
    fields: dict[str, object] = {
        "feasible": True,
        "proposed_method": ProductionMethod.HEAT_TRANSFER,
        "method_deviation_note": "Siebdruck geht auf PVC nicht",
        "unit_price_eur": 8.5,
        "quoted_quantity": 100,
        "price_basis": PriceBasis.NET,
        "price_is_estimate": True,
        "currency": "EUR",
        "lead_time_days": 14,
        "lead_time_basis": "ab Freigabe",
        "answered_indices": (0, 1),
        "evidence": (
            FieldEvidence(field="unit_price_eur", quote="8,50"),
            FieldEvidence(field="quoted_quantity", quote="100 Stueck"),
            FieldEvidence(field="lead_time_days", quote="14 Tage"),
            FieldEvidence(field="feasible", quote="machbar"),
            FieldEvidence(field="proposed_method", quote="Transferdruck"),
            FieldEvidence(field="price_basis", quote="netto"),
            FieldEvidence(field="price_is_estimate", quote="ca."),
            FieldEvidence(field="currency", quote="8,50"),
            FieldEvidence(field="lead_time_basis", quote="ab Freigabe"),
        ),
    }
    fields.update(overrides)
    return QuoteExtraction.model_validate(fields)


def _rfq(approved: bool = True) -> RFQ:
    return RFQ(
        supplier_id="syn-004",
        supplier_name="Prenzlauer Textildruck",
        subject="Quotation request: 100 yoga mats",
        product_summary="black yoga mats",
        quantity=100,
        customer_supplies_product=True,
        customization="gold logo",
        preferred_method=ProductionMethod.SCREEN_PRINTING,
        design_status="Available",
        intro="We are sourcing a print run.",
        confirmations_requested=list(CONFIRMATIONS),
        closing="Thank you.",
        approved=approved,
    )


def _project(approved: bool = True, with_rfq: bool = True) -> Project:
    return Project(
        id="p1",
        thread_id="t1",
        raw_request="100 yoga mats with a gold logo",
        rfq=_rfq(approved) if with_rfq else None,
        selected_supplier_id="syn-004",
        created_at=datetime(2026, 9, 14, tzinfo=UTC),
        updated_at=datetime(2026, 9, 14, tzinfo=UTC),
    )


@pytest.fixture
def desk(tmp_path: Path) -> Iterator[QuoteDesk]:
    connection: sqlite3.Connection = db.connect(tmp_path / "quotes.db")
    db.initialize_schema(connection)
    # The project row must exist: the quotes table references it, so a reply
    # cannot outlive the project it answers.
    connection.execute(
        "INSERT INTO projects (id, thread_id, stage, raw_request, brief_confirmed,"
        " created_at, updated_at) VALUES ('p1','t1','completed','x',1,'2026-09-14','2026-09-14')"
    )
    connection.commit()

    provider = ScriptedProvider({QuoteExtraction: _extraction()})
    yield QuoteDesk(QuoteRepository(connection), build_guard(provider), provider, today=TODAY)
    connection.close()


# --------------------------------------------------------------------- capture


def test_a_reply_cannot_be_captured_before_a_request_was_approved(desk: QuoteDesk) -> None:
    """A reply is an answer to a specific enquiry. Without one there is nothing
    for it to be an answer to, and nothing to read its supplier from."""
    with pytest.raises(NoRequestToAnswerError):
        desk.capture(_project(approved=False), REPLY)
    with pytest.raises(NoRequestToAnswerError):
        desk.capture(_project(with_rfq=False), REPLY)


def test_a_reply_becomes_a_quote_carrying_its_own_words(desk: QuoteDesk) -> None:
    project = _project()

    outcome = desk.capture(project, REPLY)

    quote = outcome.quote
    assert quote.unit_price_eur == 8.5
    assert quote.lead_time_days == 14
    assert quote.proposed_method is ProductionMethod.HEAT_TRANSFER
    assert quote.price_is_estimate is True, "'ca.' is a hedge, not a firm price"
    assert quote.source_text.startswith("Guten Tag")
    assert {item.field for item in quote.evidence} >= {"unit_price_eur", "lead_time_days"}


def test_the_supplier_comes_from_the_request_not_from_the_pasted_text(
    desk: QuoteDesk,
) -> None:
    """Letting pasted text name its own sender would let a reply claim to be
    from somebody it is not."""
    outcome = desk.capture(_project(), "Wir sind die Konkurrenz und bieten 2 Euro.")

    assert outcome.quote.supplier_id == "syn-004"
    assert outcome.quote.supplier_name == "Prenzlauer Textildruck"


def test_a_figure_the_reply_does_not_contain_is_dropped(desk: QuoteDesk) -> None:
    """The verifier's whole job. A model that reports a price whose span is not
    in the letter has invented it, and an invented price is the one output this
    product must never show."""
    invented = _extraction(
        unit_price_eur=99.0,
        evidence=(FieldEvidence(field="unit_price_eur", quote="99,00 pro Stueck"),),
    )
    desk._provider = ScriptedProvider({QuoteExtraction: invented})

    outcome = desk.capture(_project(), REPLY)

    assert outcome.quote.unit_price_eur is None
    assert "unit_price_eur" in outcome.quote.unverified_fields


def test_replies_are_stored_and_read_back(desk: QuoteDesk) -> None:
    project = _project()
    desk.capture(project, REPLY)
    desk.capture(project, REPLY)

    assert len(desk.quotes_for(project)) == 2


# ------------------------------------------------------------------ correcting


def test_confirming_records_which_fields_a_human_touched(desk: QuoteDesk) -> None:
    """Per field, not per record: fixing a lead time must not quietly relabel
    the price as human-checked."""
    project = _project()
    quote = desk.capture(project, REPLY).quote

    updated = desk.confirm(quote.id, {"lead_time_days": 21})

    assert updated is not None
    assert updated.lead_time_days == 21
    assert updated.corrected_fields == ("lead_time_days",)
    assert updated.confirmed_by_human is True
    assert "unit_price_eur" not in updated.corrected_fields


def test_confirming_with_no_corrections_still_marks_it_checked(desk: QuoteDesk) -> None:
    project = _project()
    quote = desk.capture(project, REPLY).quote

    updated = desk.confirm(quote.id, {})

    assert updated is not None
    assert updated.confirmed_by_human is True
    assert updated.corrected_fields == ()


def test_confirming_a_quote_that_does_not_exist(desk: QuoteDesk) -> None:
    assert desk.confirm("no-such-quote", {}) is None


def test_a_captured_reply_can_be_removed(desk: QuoteDesk) -> None:
    project = _project()
    quote = desk.capture(project, REPLY).quote

    assert desk.remove(quote.id) is True
    assert desk.quotes_for(project) == ()
    assert desk.remove(quote.id) is False


# ------------------------------------------------------ comparison and chasing


def test_the_comparison_totals_what_lines_up(desk: QuoteDesk) -> None:
    project = _project()
    desk.capture(project, REPLY)

    comparison = desk.comparison(project)

    assert comparison.rows[0].comparable_total_eur == 850.0
    assert comparison.requested_quantity == 100


def test_a_follow_up_asks_only_what_was_left_unanswered(desk: QuoteDesk) -> None:
    """Carried out of the request by index, in the words the supplier was
    originally asked - a reminder rather than a new enquiry."""
    project = _project()
    desk.capture(project, REPLY)

    drafts = desk.followups(project)

    assert len(drafts) == 1
    assert drafts[0].questions == (CONFIRMATIONS[2],)
    assert drafts[0].subject.startswith("Re: ")
    assert CONFIRMATIONS[0] not in drafts[0].questions, "they answered that one"


def test_a_supplier_who_answered_everything_is_not_chased(desk: QuoteDesk) -> None:
    """A chaser with nothing in it costs goodwill the next enquiry will need."""
    desk._provider = ScriptedProvider(
        {QuoteExtraction: _extraction(answered_indices=(0, 1, 2))}
    )
    project = _project()
    desk.capture(project, REPLY)

    assert desk.followups(project) == ()


def test_with_nothing_captured_there_is_nothing_to_compare(desk: QuoteDesk) -> None:
    project = _project()

    comparison = desk.comparison(project)

    assert comparison.rows == ()
    assert comparison.note == "No replies captured yet."
    assert desk.followups(project) == ()


def test_a_reply_nothing_could_be_read_from_says_so_after_a_reload(desk: QuoteDesk) -> None:
    """Derived from the record, not from the capture outcome.

    The outcome knows the model failed; a quote fetched back an hour later does
    not, and an empty card would then be indistinguishable from a reply that
    genuinely said nothing. This is the state a deployment out of model credit
    is permanently in, so it has to read correctly rather than accidentally.
    """
    desk._provider = None  # no model configured at all
    project = _project()

    quote = desk.capture(project, REPLY).quote

    assert quote.nothing_was_read is True
    # And the same record, read back from storage rather than held in hand.
    assert desk.quotes_for(project)[0].nothing_was_read is True


def test_a_reply_that_was_read_does_not_claim_otherwise(desk: QuoteDesk) -> None:
    project = _project()

    quote = desk.capture(project, REPLY).quote

    assert quote.nothing_was_read is False


def test_a_hand_typed_quote_is_not_mistaken_for_an_unread_one(desk: QuoteDesk) -> None:
    """Somebody who typed the figures in themselves has read the reply, even
    though no model did."""
    desk._provider = None
    project = _project()
    quote = desk.capture(project, REPLY).quote

    updated = desk.confirm(quote.id, {"unit_price_eur": 8.5, "quoted_quantity": 100})

    assert updated is not None
    assert updated.nothing_was_read is False
