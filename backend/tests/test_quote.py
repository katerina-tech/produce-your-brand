"""The quote domain: every rule that stops a number meaning more than it should.

One test per rejected combination, because each validator here exists to block a
specific way the interface could mislead somebody spending money. The most
important is the last group: a figure the model produced must carry the words it
read that figure from, and a figure a human typed must not.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.enums import PriceBasis, ProductionMethod
from app.domain.quote import ComparisonRow, FieldEvidence, QuoteComparison, SupplierQuote

REPLY = "Machbar, aber bei 100 Stück kommen wir auf 14 Tage. ca. 8,50/Stück netto."


def _quote(**overrides: object) -> SupplierQuote:
    base: dict[str, object] = {
        "id": "q1",
        "project_id": "p1",
        "supplier_id": "syn-001",
        "supplier_name": "Spree Textildruck",
        "source_text": REPLY,
        "received_on": date(2026, 9, 13),
    }
    base.update(overrides)
    return SupplierQuote(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------- the answers


def test_silence_about_price_is_none_not_zero() -> None:
    """A reply that says nothing about money has not quoted zero."""
    quote = _quote()

    assert quote.unit_price_eur is None
    assert quote.total_price_eur is None


def test_an_unclear_reply_is_not_a_refusal() -> None:
    """feasible is set only from an explicit statement. A warm, vague reply
    must never be rendered to the buyer as "they said no"."""
    assert _quote().feasible is None


def test_an_unstated_price_basis_is_its_own_answer() -> None:
    """Between net and gross lies 19% VAT. Guessing is the most expensive
    invention this system could make."""
    assert _quote().price_basis is PriceBasis.UNSTATED


def test_a_price_without_a_known_basis_is_not_a_usable_price() -> None:
    quote = _quote(
        unit_price_eur=8.5,
        evidence=(FieldEvidence(field="unit_price_eur", quote="8,50"),),
    )

    assert quote.has_price is False, "a figure whose net/gross status is unknown is not a price"


def test_a_price_with_a_basis_is_usable() -> None:
    quote = _quote(
        unit_price_eur=8.5,
        price_basis=PriceBasis.NET,
        evidence=(FieldEvidence(field="unit_price_eur", quote="8,50"),),
    )

    assert quote.has_price is True


# ------------------------------------------------------------- the validators


def test_a_total_price_must_say_what_quantity_it_is_for() -> None:
    """A total with no quantity cannot be compared, and cannot be fixed later
    without asking the supplier again."""
    with pytest.raises(ValueError, match="what quantity it is for"):
        _quote(
            total_price_eur=850.0,
            evidence=(FieldEvidence(field="total_price_eur", quote="850"),),
        )


def test_a_demo_quote_cannot_be_human_confirmed() -> None:
    """Verbatim mirror of the rule Offer carries."""
    with pytest.raises(ValueError, match="demo quote cannot also be human-confirmed"):
        _quote(is_demo=True, confirmed_by_human=True)


def test_a_sample_cost_implies_a_sample() -> None:
    with pytest.raises(ValueError, match="sample cost implies"):
        _quote(
            sample_cost_eur=20.0,
            sample_available=False,
            evidence=(FieldEvidence(field="sample_cost_eur", quote="20"),),
        )


def test_evidence_cannot_name_a_field_that_does_not_exist() -> None:
    with pytest.raises(ValueError, match="unknown fields"):
        _quote(evidence=(FieldEvidence(field="discount_percent", quote="10%"),))


# --------------------------------- the invariant: a figure quotes its source


def test_a_model_extracted_figure_without_a_span_is_refused() -> None:
    """The load-bearing rule. An invented price must be unstorable, not merely
    discouraged."""
    with pytest.raises(ValueError, match="needs the words it came from"):
        _quote(unit_price_eur=8.5, price_basis=PriceBasis.NET)


def test_every_numeric_field_is_covered_by_the_rule() -> None:
    """Not just price - a fabricated lead time is just as actionable."""
    for field, value in (
        ("unit_price_eur", 8.5),
        ("total_price_eur", 850.0),
        ("setup_cost_eur", 40.0),
        ("sample_cost_eur", 20.0),
        ("lead_time_days", 14),
    ):
        with pytest.raises(ValueError, match="needs the words it came from"):
            # quoted_quantity is supplied so the total-price rule is not what fires.
            _quote(
                **{field: value},  # type: ignore[arg-type]
                quoted_quantity=100,
                evidence=(FieldEvidence(field="quoted_quantity", quote="100 Stück"),),
            )


def test_a_human_corrected_figure_needs_no_span() -> None:
    """Provenance is per field for exactly this reason: a person may know a
    figure the letter never stated, and correcting a lead time must not relabel
    the price as human-checked."""
    quote = _quote(lead_time_days=14, corrected_fields=("lead_time_days",))

    assert quote.lead_time_days == 14


def test_correcting_one_field_does_not_exempt_another() -> None:
    with pytest.raises(ValueError, match="unit_price_eur"):
        _quote(
            lead_time_days=14,
            unit_price_eur=8.5,
            corrected_fields=("lead_time_days",),
        )


# ------------------------------------------------------------------ display


def test_the_summary_never_invents_a_total() -> None:
    quote = _quote(
        unit_price_eur=8.5,
        quoted_quantity=100,
        price_basis=PriceBasis.NET,
        price_is_estimate=True,
        lead_time_days=14,
        currency="EUR",
        evidence=(
            FieldEvidence(field="unit_price_eur", quote="8,50"),
            FieldEvidence(field="quoted_quantity", quote="100 Stück"),
            FieldEvidence(field="lead_time_days", quote="14 Tage"),
        ),
    )

    summary = quote.summary()

    assert "8.50/unit" in summary
    assert "net" in summary
    assert "(estimate)" in summary, "a hedged figure must stay visibly hedged"
    assert "850" not in summary, "the summary must not multiply anything"


def test_an_unreadable_reply_says_so() -> None:
    assert _quote().summary() == "Nothing readable in this reply"
    assert _quote().is_empty is True


def test_a_priced_reply_is_not_empty() -> None:
    quote = _quote(feasible=True)

    assert quote.is_empty is False


def test_a_deviation_keeps_the_suppliers_own_words() -> None:
    quote = _quote(
        proposed_method=ProductionMethod.HEAT_TRANSFER,
        method_deviation_note="Siebdruck geht nicht auf PVC",
    )

    assert quote.method_deviation_note == "Siebdruck geht nicht auf PVC"


# --------------------------------------------------------------- comparison


def test_a_money_cell_is_either_computed_or_explained() -> None:
    """No silent blanks in a money column: a blank with no reason would let a
    buyer assume a supplier was expensive when nobody actually knew."""
    with pytest.raises(ValueError, match="must say why"):
        ComparisonRow(quote_id="q1", supplier_name="Spree")


def test_a_row_cannot_be_both_totalled_and_blocked() -> None:
    with pytest.raises(ValueError, match="must not also be blocked"):
        ComparisonRow(
            quote_id="q1",
            supplier_name="Spree",
            comparable_total_eur=850.0,
            blockers=("price basis not stated",),
        )


def test_a_blocked_row_states_its_reason() -> None:
    row = ComparisonRow(quote_id="q1", supplier_name="Spree", blockers=("currency is CHF",))

    assert row.comparable_total_eur is None
    assert row.blockers == ("currency is CHF",)


def test_the_comparison_has_no_best_and_no_score() -> None:
    """Deliberate absence. Cheapest and fastest are facts a column sort defends;
    "best" is a judgement, and at two or three quotes a weighted model would be
    theatre."""
    fields = set(QuoteComparison.model_fields)

    assert "best_quote_id" not in fields
    assert not any("score" in name for name in fields)
