"""Budget: captured, passed on, and deliberately not scored.

A customer who writes "I have EUR 10,000 for this" has told the system something
load-bearing, and until now it was dropped: there was no field, so the sentence
vanished into free text and the product behaved as though it had never been
said. That is worse than not supporting budgets, because the customer believes
they were heard.

What a budget must *not* do here is influence the ranking. The product holds no
reliable price data - the customer-discovery interview established that print
pricing cannot be scraped because it sits in non-public business logic - so
scoring a supplier against a budget would mean inventing the very numbers this
system refuses to invent. The honest handling is to state it in the request for
quotation and let the people who know their costs answer against it.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.enums import ProductionMethod
from app.domain.requirement import ProductionRequirement
from app.domain.supplier import Location, Supplier
from app.services import completeness, rfq_builder


def _requirement(**overrides: object) -> ProductionRequirement:
    base: dict[str, object] = {"product": "tote bags", "quantity": 500}
    base.update(overrides)
    return ProductionRequirement(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------- the field


def test_an_unstated_budget_is_none_not_zero() -> None:
    """Zero would read as "no money", which is a different statement entirely."""
    assert _requirement().budget_eur is None


def test_a_budget_must_be_positive() -> None:
    with pytest.raises(ValueError):
        _requirement(budget_eur=0)


def test_a_stated_budget_is_kept() -> None:
    assert _requirement(budget_eur=10_000).budget_eur == 10_000


# ------------------------------------------------------------- completeness


def test_budget_never_blocks_a_project() -> None:
    """Most customers do not state one, and sourcing is perfectly possible
    without it. Blocking on a budget would stop real work for no gain."""
    assert "budget_eur" not in completeness.CRITICAL_FIELD_ORDER
    assert "budget_eur" in completeness.NON_BLOCKING_FIELDS


def test_budget_has_a_human_label() -> None:
    """The backend owns labels so the interface and the clarification flow
    cannot drift apart."""
    assert completeness.FIELD_LABELS["budget_eur"] == "Budget"


# ----------------------------------------------------------------- the RFQ


def test_a_stated_budget_reaches_the_supplier() -> None:
    notes = rfq_builder._additional_notes(_requirement(budget_eur=10_000))

    assert any("10,000" in note for note in notes), (
        "a budget the customer stated must appear in the request they send"
    )


def test_an_absent_budget_says_nothing_at_all() -> None:
    """Silence, not "budget: not specified" - an RFQ should not draw a
    supplier's attention to a constraint the customer never set."""
    notes = rfq_builder._additional_notes(_requirement())

    assert not any("budget" in note.lower() for note in notes)


def test_the_budget_note_is_stated_as_a_total() -> None:
    """A per-unit misreading would be expensive for both sides."""
    notes = rfq_builder._additional_notes(_requirement(budget_eur=7_500))
    budget_notes = [note for note in notes if "udget" in note]

    assert budget_notes, "expected a budget note"
    assert "total" in budget_notes[0].lower()


# ------------------------------------------- the decision: stated, not scored


def _supplier(**overrides: object) -> Supplier:
    base: dict[str, object] = {
        "id": "s1",
        "name": "Test Werk",
        "location": Location(city="Berlin", country="DE"),
        "supported_methods": (ProductionMethod.SCREEN_PRINTING,),
        "product_categories": (),
    }
    base.update(overrides)
    return Supplier(**base)  # type: ignore[arg-type]


def test_budget_does_not_change_any_score() -> None:
    """The load-bearing test.

    The ranking claims to be explainable from six stated capability factors. A
    budget is not one of them, and it must not become one by accident - the
    product has no price data to judge against, so any influence would be
    invented.
    """
    from app.services import matching

    supplier = _supplier()
    today = date(2026, 9, 13)

    without = matching.score_supplier(
        supplier, _requirement(), ProductionMethod.SCREEN_PRINTING, today
    )
    with_budget = matching.score_supplier(
        supplier, _requirement(budget_eur=50), ProductionMethod.SCREEN_PRINTING, today
    )

    assert without.score == with_budget.score, "a budget moved a score"
    assert without.factors == with_budget.factors, "a budget changed a factor breakdown"


def test_an_absurdly_small_budget_does_not_exclude_anyone() -> None:
    """Deliberate: we do not know what anything costs, so we are in no position
    to tell a customer that their budget rules a supplier out."""
    from app.services import matching

    result = matching.score_supplier(
        _supplier(), _requirement(budget_eur=1), ProductionMethod.SCREEN_PRINTING, date(2026, 9, 13)
    )

    assert result.eligible is True
