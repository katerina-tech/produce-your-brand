"""Turning an approved RFQ into a sendable email.

The property worth more than the rest: what leaves is what was approved. This
is the only text in the system meant to reach a third party, so a figure that
appears here without appearing in the RFQ would be the product putting words
in its user's mouth.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from app.domain.enums import ProductionMethod
from app.domain.rfq import RFQ
from app.services.outreach import RFQNotApprovedError, render_email


def _rfq(**overrides: object) -> RFQ:
    fields: dict[str, object] = {
        "supplier_id": "syn-001",
        "supplier_name": "Kreuzberg Laser Atelier",
        "subject": "Quotation request: 100 t-shirts with a printed logo",
        "product_summary": "t-shirts",
        "quantity": 100,
        "customer_supplies_product": True,
        "customization": "gold logo, front centre",
        "preferred_method": ProductionMethod.SCREEN_PRINTING,
        "design_status": "Available - vector file",
        "deadline": date(2026, 12, 15),
        "delivery_location": "Berlin",
        "intro": "We are sourcing a print run and would value your quotation.",
        "confirmations_requested": ["Feasibility on cotton", "Lead time for 100 units"],
        "additional_notes": ["We already own the blanks."],
        "closing": "Thank you.",
        "approved": True,
    }
    fields.update(overrides)
    return RFQ.model_validate(fields)


def test_an_unapproved_rfq_cannot_become_an_email() -> None:
    """The one guard that is not ceremony: unapproved text must never be one
    click away from a supplier's inbox."""
    with pytest.raises(RFQNotApprovedError):
        render_email(_rfq(approved=False))


def test_the_subject_is_the_approved_subject_unchanged() -> None:
    rfq = _rfq()

    assert render_email(rfq).subject == rfq.subject


def test_every_fact_in_the_body_came_from_the_rfq() -> None:
    email = render_email(_rfq())

    assert "t-shirts" in email.body
    assert "100" in email.body
    assert "gold logo, front centre" in email.body
    assert "screen printing" in email.body
    assert "15.12.2026" in email.body, "German dates, for German suppliers"
    assert "Berlin" in email.body
    assert email.body.startswith("We are sourcing a print run")
    assert email.body.rstrip().endswith("Thank you.")


def test_no_figure_appears_that_the_rfq_does_not_carry() -> None:
    """The failure this is built to make impossible. A summarising model could
    round 100 to "about a hundred" or invent a price; assembling the text from
    the approved fields cannot."""
    # The confirmations carry figures of their own and numbers of their own, so
    # they are cleared here to leave the quantity as the only thing in the body
    # that a digit could legitimately come from.
    rfq = _rfq(quantity=250, confirmations_requested=[], additional_notes=[])
    email = render_email(rfq)

    digits = {chunk for chunk in email.body.replace("\n", " ").split() if chunk.isdigit()}
    assert digits == {"250"}, f"unexplained figures: {digits}"


def test_the_confirmations_are_numbered_so_a_reply_can_refer_to_them() -> None:
    email = render_email(_rfq())

    assert "1. Feasibility on cotton" in email.body
    assert "2. Lead time for 100 units" in email.body


def test_fields_the_brief_never_established_are_simply_absent() -> None:
    """Silence, not a guess and not the word "None" - an unknown deadline that
    renders as "Needed by: None" is how a supplier learns to distrust the whole
    message."""
    email = render_email(
        _rfq(deadline=None, delivery_location=None, quantity=None, customer_supplies_product=None)
    )

    assert "None" not in email.body
    assert "Needed by" not in email.body
    assert "Delivery" not in email.body
    assert "Quantity" not in email.body


def test_customer_owned_goods_are_stated_rather_than_implied() -> None:
    """The fact that decides whether a supplier can quote at all."""
    owned = render_email(_rfq(customer_supplies_product=True)).body
    made = render_email(_rfq(customer_supplies_product=False)).body

    assert "already exist and are supplied by us" in owned
    assert "to be produced" in made


# ------------------------------------------------------------------- the links


def test_the_gmail_link_opens_a_compose_window_and_nothing_else() -> None:
    """``view=cm`` is Gmail's compose view. There is no parameter here that
    sends, and that is the point: the buyer presses send, so the buyer is the
    sender."""
    email = render_email(_rfq(), to="hallo@example.de")

    parsed = urlparse(email.gmail_url)
    query = parse_qs(parsed.query)

    assert parsed.netloc == "mail.google.com"
    assert query["view"] == ["cm"]
    assert query["to"] == ["hallo@example.de"]
    assert query["su"] == [email.subject]
    assert query["body"] == [email.body]


def test_an_address_we_do_not_have_leaves_the_field_empty() -> None:
    """This product stores no supplier email addresses - holding them would be
    the processing it exists without. The sender fills this in."""
    email = render_email(_rfq())

    assert email.to == ""
    # keep_blank_values, or parse_qs silently drops the very field under test.
    query = parse_qs(urlparse(email.gmail_url).query, keep_blank_values=True)
    assert query["to"] == [""]


def test_a_newline_survives_into_the_link() -> None:
    """Encoded, not dropped. A body arriving as one run-on paragraph is the
    classic way a mailto link fails without anybody noticing."""
    email = render_email(_rfq())

    assert "%0A" in email.gmail_url
    assert "%0A" in email.mailto_url


def test_a_message_too_long_for_a_url_says_so_instead_of_being_cut() -> None:
    """Silent truncation would put half an email in the compose window."""
    short = render_email(_rfq())
    long = render_email(_rfq(additional_notes=["a very long note " * 400]))

    assert short.fits_in_a_url is True
    assert long.fits_in_a_url is False
