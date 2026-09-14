"""The verifier: proving a figure the supplier never wrote cannot survive.

These tests assert against :func:`verify` directly with hand-built evidence,
never through a scripted provider. A stubbed model returns whatever the stub was
told to return, so it can demonstrate that plumbing works but never that
grounding does - the thing worth proving here is that a span which does not
support a number causes that number to disappear, and only a direct call can
show it.
"""

from __future__ import annotations

import pytest

from app.domain.quote import FieldEvidence
from app.services.quote_verification import candidate_values, verify

REPLY = "Machbar, aber bei 100 Stück kommen wir auf 14 Tage. ca. 8,50/Stück netto."


def _evidence(*pairs: tuple[str, str]) -> tuple[FieldEvidence, ...]:
    return tuple(FieldEvidence(field=field, quote=quote) for field, quote in pairs)


# ------------------------------------------------------- reading the numerals


@pytest.mark.parametrize(
    ("span", "expected"),
    [
        ("ca. 8,50/Stück", {8.5}),
        ("8.50 each", {8.5}),
        ("EUR 1,234.56", {1234.56}),
        ("1.234,56 EUR", {1234.56}),
        ("14 Tage", {14.0}),
        ("1.000 Stück", {1.0, 1000.0}),
    ],
)
def test_a_span_yields_the_numbers_a_human_would_read(span: str, expected: set[float]) -> None:
    assert candidate_values(span) == expected


def test_a_decimal_comma_is_never_read_as_thousands() -> None:
    """The rule that makes the value check worth having.

    Without it a model could report 850 while quoting "8,50" and pass, which is
    precisely the class of error this module exists to catch.
    """
    assert 850.0 not in candidate_values("ca. 8,50/Stück")


def test_a_genuinely_ambiguous_token_keeps_both_readings() -> None:
    """ "1.000" is a thousand in German and one in English. Picking a side would
    delete a correct figure whenever the guess was wrong."""
    assert candidate_values("1.000 Stück") == {1.0, 1000.0}


# ----------------------------------------------------- the span must be there


def test_an_honest_reading_survives_untouched() -> None:
    result = verify(
        {"unit_price_eur": 8.50, "lead_time_days": 14, "quoted_quantity": 100},
        _evidence(
            ("unit_price_eur", "ca. 8,50/Stück"),
            ("lead_time_days", "14 Tage"),
            ("quoted_quantity", "bei 100 Stück"),
        ),
        REPLY,
    )

    assert result.values["unit_price_eur"] == 8.50
    assert result.values["lead_time_days"] == 14
    assert result.dropped == ()
    assert result.anything_dropped is False


def test_a_figure_with_no_span_at_all_is_deleted() -> None:
    result = verify({"unit_price_eur": 8.50}, (), REPLY)

    assert result.values["unit_price_eur"] is None
    assert result.dropped == ("unit_price_eur",)


def test_a_span_that_is_not_in_the_reply_is_deleted() -> None:
    """The model quoted words the supplier never wrote - a fabricated citation
    is exactly as dangerous as a fabricated number."""
    result = verify(
        {"unit_price_eur": 8.50},
        _evidence(("unit_price_eur", "Preis 8,50 pro Stück inkl. MwSt")),
        REPLY,
    )

    assert result.values["unit_price_eur"] is None
    assert result.dropped == ("unit_price_eur",)


# ------------------------------------------- the value must be inside the span


def test_a_real_span_does_not_license_a_different_number() -> None:
    """The graft that turns a citation into evidence.

    Quoting a genuine sentence while reporting a number that is not in it would
    otherwise pass every check, and it is the likeliest shape of a plausible
    hallucination.
    """
    result = verify(
        {"unit_price_eur": 12.00},
        _evidence(("unit_price_eur", "ca. 8,50/Stück")),
        REPLY,
    )

    assert result.values["unit_price_eur"] is None
    assert result.dropped == ("unit_price_eur",)


def test_quoting_the_lead_time_does_not_license_a_price() -> None:
    result = verify(
        {"unit_price_eur": 14.0},
        _evidence(("unit_price_eur", "14 Tage")),
        REPLY,
    )

    # 14 is genuinely in that span, so this one is allowed through: the verifier
    # proves the number is present, not that the model understood the sentence.
    # The confirm gate is where a human catches a mis-read of meaning.
    assert result.values["unit_price_eur"] == 14.0


# --------------------------------------------------------- non-numeric fields


def test_a_non_numeric_claim_still_needs_words() -> None:
    """feasible, price_basis and the rest are just as actionable as a figure."""
    result = verify({"feasible": True}, (), REPLY)

    assert result.values["feasible"] is None
    assert "feasible" in result.dropped


def test_a_non_numeric_claim_with_a_real_span_survives() -> None:
    result = verify({"feasible": True}, _evidence(("feasible", "Machbar")), REPLY)

    assert result.values["feasible"] is True


def test_prose_is_left_alone() -> None:
    """open_questions carries no figure and enters no calculation, so grounding
    it would cost accuracy without buying safety."""
    result = verify(
        {"open_questions": ("Welche Dateiformate?",)},
        (),
        REPLY,
    )

    assert result.values["open_questions"] == ("Welche Dateiformate?",)


# --------------------------------------------------------------- resilience


def test_obfuscated_text_still_matches_after_folding() -> None:
    """The model saw the folded text, so the verifier compares folded text.

    Otherwise a zero-width character in the reply would silently delete every
    honest figure read from it.
    """
    obfuscated = "Machbar, ca.​ 8,50/Stück netto."

    result = verify(
        {"unit_price_eur": 8.50},
        _evidence(("unit_price_eur", "ca. 8,50/Stück")),
        obfuscated,
    )

    assert result.values["unit_price_eur"] == 8.50


def test_the_verifier_only_ever_removes() -> None:
    """It must never add a key or change one it did not delete."""
    given = {"unit_price_eur": 8.50, "source_language": "de"}

    result = verify(given, (), REPLY)

    assert set(result.values) == set(given)
    assert result.values["source_language"] == "de"


def test_an_empty_span_cannot_ground_anything() -> None:
    """A whitespace-only quote is present in every text ever written."""
    result = verify(
        {"lead_time_days": 14},
        _evidence(("lead_time_days", "   ")),
        REPLY,
    )

    assert result.values["lead_time_days"] is None
