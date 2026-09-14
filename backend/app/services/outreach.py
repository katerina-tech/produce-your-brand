"""Turn an approved RFQ into an email body.

Deterministic on purpose. Every line below comes from a field the user read and
approved at the quotation gate, so what arrives in the supplier's inbox is what
was on screen when they pressed approve. There is no model call here and there
should never be one: the cheapest way to break this product's central promise -
that a person approves every step - is to let something rewrite the text after
the approval.

That also makes it free, which matters more than it should: the deployment has
run out of model credit twice, and a feature that works anyway is worth more
than a slightly smoother sentence.
"""

from __future__ import annotations

from app.domain.outreach import OutreachEmail
from app.domain.rfq import RFQ

# German dates, because the suppliers this addresses are German and a deadline
# is the one field a misreading turns into a missed delivery.
_DATE_FORMAT = "%d.%m.%Y"


class RFQNotApprovedError(RuntimeError):
    """An unapproved RFQ has no business being turned into an email."""


def _detail_lines(rfq: RFQ) -> list[str]:
    """The facts, one per line, in the order a quoting supplier reads them."""
    lines = [f"- Product: {rfq.product_summary}"]

    if rfq.quantity is not None:
        lines.append(f"- Quantity: {rfq.quantity}")
    if rfq.customer_supplies_product is True:
        lines.append("- The goods already exist and are supplied by us")
    elif rfq.customer_supplies_product is False:
        lines.append("- The goods are to be produced, not supplied by us")

    lines.append(f"- Customisation: {rfq.customization}")
    lines.append(f"- Proposed method: {rfq.preferred_method.value.replace('_', ' ')}")
    lines.append(f"- Design: {rfq.design_status}")

    if rfq.deadline is not None:
        lines.append(f"- Needed by: {rfq.deadline.strftime(_DATE_FORMAT)}")
    if rfq.delivery_location:
        lines.append(f"- Delivery: {rfq.delivery_location}")

    return lines


def render_email(rfq: RFQ, *, to: str = "") -> OutreachEmail:
    """Compose the message. Raises if the RFQ was never approved.

    The guard is not ceremony. This is the only function in the codebase whose
    output is meant to leave for a third party, and an unapproved RFQ reaching
    it would mean text the user never agreed to was one click from a supplier's
    inbox.
    """
    if not rfq.approved:
        raise RFQNotApprovedError(rfq.supplier_id)

    parts = [rfq.intro, "", *_detail_lines(rfq)]

    if rfq.confirmations_requested:
        parts += ["", "Could you please confirm:"]
        parts += [f"{index}. {item}" for index, item in enumerate(rfq.confirmations_requested, 1)]

    if rfq.additional_notes:
        parts += ["", *(f"- {note}" for note in rfq.additional_notes)]

    parts += ["", rfq.closing]

    return OutreachEmail(to=to, subject=rfq.subject, body="\n".join(parts))
