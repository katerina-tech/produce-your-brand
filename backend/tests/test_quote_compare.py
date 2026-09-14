"""Comparing supplier replies.

Every test here is a way a price column can lie. A total that mixes net with
gross, or 50 units with 100, looks authoritative and is wrong - and a buyer
acts on it. So the module's job is less "add the numbers" than "refuse, out
loud, when adding them would mislead".
"""

from __future__ import annotations

from datetime import date

from app.domain.enums import PriceBasis
from app.domain.quote import FieldEvidence, QuoteComparison, SupplierQuote
from app.services.quote_compare import compare

REPLY = (
    "Machbar. Fuer 100 Stueck kommen wir auf 8,50 pro Stueck netto, "
    "zzgl. 45 Euro Einrichtung, also 850 Euro gesamt, Lieferzeit 14 Tage."
)

CONFIRMATIONS = (
    "Feasibility on cotton jersey",
    "Lead time for 100 units",
    "Whether you accept customer-supplied garments",
)


def _quote(**overrides: object) -> SupplierQuote:
    fields: dict[str, object] = {
        "id": "q1",
        "project_id": "p1",
        "supplier_id": "syn-004",
        "supplier_name": "Prenzlauer Textildruck",
        "unit_price_eur": 8.5,
        "quoted_quantity": 100,
        "price_basis": PriceBasis.NET,
        "currency": "EUR",
        "lead_time_days": 14,
        "source_text": REPLY,
        "received_on": date(2026, 9, 14),
        # Every figure must point at the words it came from - the model refuses
        # a quote that carries a number with no source span, which is the whole
        # reason nothing here can be quietly invented.
        "evidence": (
            FieldEvidence(field="unit_price_eur", quote="8,50"),
            FieldEvidence(field="quoted_quantity", quote="100 Stueck"),
            FieldEvidence(field="lead_time_days", quote="14 Tage"),
            FieldEvidence(field="setup_cost_eur", quote="45 Euro Einrichtung"),
            FieldEvidence(field="total_price_eur", quote="850 Euro gesamt"),
        ),
    }
    fields.update(overrides)
    return SupplierQuote.model_validate(fields)


def test_a_straightforward_reply_is_totalled() -> None:
    comparison = compare([_quote()], requested_quantity=100, confirmations=CONFIRMATIONS)

    row = comparison.rows[0]
    assert row.comparable_total_eur == 850.0
    assert row.blockers == ()


def test_set_up_cost_is_part_of_what_the_buyer_pays() -> None:
    """Leaving it out would make a supplier who charges set-up look cheaper
    than one who folds it into the unit price."""
    comparison = compare([_quote(setup_cost_eur=45.0)], requested_quantity=100)

    assert comparison.rows[0].comparable_total_eur == 895.0


def test_an_unstated_price_basis_blocks_the_total() -> None:
    """Net against gross is a 19% error in Germany - large enough to reverse a
    ranking, and invisible once both are in one column."""
    comparison = compare(
        [_quote(price_basis=PriceBasis.UNSTATED)], requested_quantity=100
    )

    row = comparison.rows[0]
    assert row.comparable_total_eur is None
    assert any("basis" in blocker for blocker in row.blockers)


def test_a_price_for_a_different_quantity_blocks_the_total() -> None:
    comparison = compare([_quote(quoted_quantity=50)], requested_quantity=100)

    row = comparison.rows[0]
    assert row.comparable_total_eur is None
    assert any("50" in blocker and "100" in blocker for blocker in row.blockers)


def test_another_currency_is_named_rather_than_converted() -> None:
    """A conversion rate would be a number this system invented, stale by the
    time anybody read it. Naming the currency lets the buyer ask for euros."""
    comparison = compare([_quote(currency="CHF")], requested_quantity=100)

    row = comparison.rows[0]
    assert row.comparable_total_eur is None
    assert any("CHF" in blocker for blocker in row.blockers)


def test_a_reply_with_no_price_says_exactly_that() -> None:
    comparison = compare(
        [_quote(unit_price_eur=None, total_price_eur=None)], requested_quantity=100
    )

    assert comparison.rows[0].blockers == ("no price quoted",)


def test_a_blank_money_cell_never_appears_without_a_reason() -> None:
    """The property the whole module exists for. A blank cell reads as
    "expensive" or "did not answer", and both are conclusions a buyer would
    draw about a supplier who simply priced per unit."""
    quotes = [
        _quote(id="a"),
        _quote(id="b", price_basis=PriceBasis.UNSTATED),
        _quote(id="c", unit_price_eur=None, total_price_eur=None),
        _quote(id="d", currency="CHF"),
    ]

    comparison = compare(quotes, requested_quantity=100)

    for row in comparison.rows:
        assert (row.comparable_total_eur is not None) ^ bool(row.blockers)


# ------------------------------------------------------------------- ranking


def test_cheapest_is_named_when_the_bases_agree() -> None:
    quotes = [_quote(id="a", unit_price_eur=8.5), _quote(id="b", unit_price_eur=7.9)]

    comparison = compare(quotes, requested_quantity=100)

    assert comparison.cheapest_quote_id == "b"


def test_cheapest_is_withheld_when_the_bases_do_not_agree() -> None:
    """Cheapest across a mixed basis is a claim about numbers that were never
    comparable - the same restraint the match score is held to."""
    quotes = [
        _quote(id="a", unit_price_eur=8.5, price_basis=PriceBasis.NET),
        _quote(id="b", unit_price_eur=7.9, price_basis=PriceBasis.GROSS),
    ]

    comparison = compare(quotes, requested_quantity=100)

    assert comparison.cheapest_quote_id is None
    assert "not all on the same basis" in comparison.note


def test_a_single_reply_is_not_the_cheapest_of_anything() -> None:
    comparison = compare([_quote()], requested_quantity=100)

    assert comparison.cheapest_quote_id is None
    assert comparison.fastest_quote_id is None


def test_fastest_needs_no_such_care_because_days_are_days() -> None:
    quotes = [_quote(id="a", lead_time_days=14), _quote(id="b", lead_time_days=9)]

    comparison = compare(quotes, requested_quantity=100)

    assert comparison.fastest_quote_id == "b"


def test_there_is_no_best_and_no_score() -> None:
    """Deliberately absent. Cheapest and fastest are facts a column sort can
    defend; "best" is a judgement, and at three quotes a weighted model would
    be theatre."""
    comparison = compare([_quote()], requested_quantity=100)

    assert not hasattr(comparison, "best_quote_id")
    assert not any("score" in field for field in QuoteComparison.model_fields)


# ------------------------------------------------------- unanswered questions


def test_unanswered_questions_are_carried_in_the_words_they_were_asked() -> None:
    comparison = compare(
        [_quote(unanswered_indices=(0, 2))], requested_quantity=100, confirmations=CONFIRMATIONS
    )

    assert comparison.rows[0].unanswered == (CONFIRMATIONS[0], CONFIRMATIONS[2])
    assert comparison.rows[0].answered_count == 1


def test_a_question_nobody_answered_is_surfaced_once() -> None:
    """This is what a follow-up is made of, and it writes itself."""
    quotes = [_quote(id="a", unanswered_indices=(1,)), _quote(id="b", unanswered_indices=(0, 1))]

    comparison = compare(quotes, requested_quantity=100, confirmations=CONFIRMATIONS)

    assert comparison.unanswered_by_everyone == (CONFIRMATIONS[1],)


def test_with_no_replies_nothing_has_been_left_unanswered() -> None:
    comparison = compare([], requested_quantity=100, confirmations=CONFIRMATIONS)

    assert comparison.rows == ()
    assert comparison.unanswered_by_everyone == ()
    assert comparison.note == "No replies captured yet."


def test_an_index_outside_the_request_is_dropped_rather_than_crashing() -> None:
    """The indices arrive from an extraction. A stale or invented one must cost
    a missing line in a follow-up, not an exception on the comparison screen."""
    comparison = compare(
        [_quote(unanswered_indices=(0, 99))], requested_quantity=100, confirmations=CONFIRMATIONS
    )

    assert comparison.rows[0].unanswered == (CONFIRMATIONS[0],)
