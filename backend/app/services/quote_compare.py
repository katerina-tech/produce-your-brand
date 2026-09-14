"""Put several supplier replies side by side, and refuse to compare what is not comparable.

No model call anywhere in this module. Comparing prices is arithmetic with
preconditions, and the preconditions are where a buyer actually gets hurt: a
column that silently totals a net price against a gross one, or a price for 50
units against a price for 100, produces a number that looks authoritative and
is wrong. So every total is either computed from figures that genuinely line
up, or absent with a stated reason.

The reason matters as much as the number. A blank cell in a money column reads
as "expensive" or "did not answer", and both are conclusions the buyer would
draw about a supplier who may simply have quoted per unit without saying for
how many.
"""

from __future__ import annotations

from app.domain.enums import PriceBasis
from app.domain.quote import ComparisonRow, QuoteComparison, SupplierQuote

# Everything is compared in euros. A figure in another currency is not converted
# here: a rate would be a number this system invented, and it would be stale by
# the time anybody read it.
COMPARISON_CURRENCY = "EUR"


def _blockers(quote: SupplierQuote, requested_quantity: int | None) -> list[str]:
    """Why this quote cannot be totalled, in words a buyer can act on."""
    reasons: list[str] = []

    if quote.unit_price_eur is None and quote.total_price_eur is None:
        reasons.append("no price quoted")
        return reasons

    if quote.currency is not None and quote.currency.upper() != COMPARISON_CURRENCY:
        # Stated and not euros. Converting would invent a rate; saying so lets
        # the buyer ask for a euro price, which is the actual remedy.
        reasons.append(f"quoted in {quote.currency.upper()}, not euros")

    if quote.price_basis is PriceBasis.UNSTATED:
        # Net against gross is a 19% error in Germany - large enough to reverse
        # a ranking, and invisible once the two are added into one column.
        reasons.append("price basis not stated (net or gross?)")

    quantity = quote.quoted_quantity
    if quote.total_price_eur is not None:
        # The model guarantees a total carries its quantity, so this is about
        # whether it is the quantity that was asked for.
        if requested_quantity is not None and quantity != requested_quantity:
            reasons.append(f"quoted for {quantity} units, you asked for {requested_quantity}")
    elif quantity is None:
        if requested_quantity is None:
            reasons.append("no quantity to multiply a unit price by")
    elif requested_quantity is not None and quantity != requested_quantity:
        reasons.append(f"priced per unit at {quantity} units, you asked for {requested_quantity}")

    return reasons


def _total(quote: SupplierQuote, requested_quantity: int | None) -> float | None:
    """The comparable total, assuming the blockers came back empty."""
    if quote.total_price_eur is not None:
        total = quote.total_price_eur
    else:
        # Only reached when the quantity lines up, or when the supplier priced
        # per unit for exactly the quantity requested.
        quantity = quote.quoted_quantity or requested_quantity
        if quote.unit_price_eur is None or quantity is None:
            return None
        total = quote.unit_price_eur * quantity

    if quote.setup_cost_eur is not None:
        # Set-up is part of what the buyer pays. Leaving it out would make a
        # supplier with a set-up fee look cheaper than one who includes it.
        total += quote.setup_cost_eur

    return round(total, 2)


def _unanswered(quote: SupplierQuote, confirmations: tuple[str, ...]) -> tuple[str, ...]:
    """The questions this reply left alone, by the RFQ's own wording.

    Carried by index out of the request rather than re-described, so a question
    reaches the follow-up in the words the supplier was originally asked.
    """
    return tuple(
        confirmations[index]
        for index in quote.unanswered_indices
        if 0 <= index < len(confirmations)
    )


def _row(
    quote: SupplierQuote, requested_quantity: int | None, confirmations: tuple[str, ...]
) -> ComparisonRow:
    blockers = _blockers(quote, requested_quantity)
    total = None if blockers else _total(quote, requested_quantity)

    if total is None and not blockers:
        # Belt and braces: the model refuses a row that is neither totalled nor
        # explained, and an unexplained arithmetic gap would raise there rather
        # than here. Saying it plainly is cheaper than debugging that later.
        blockers = ["price could not be totalled from what was quoted"]

    unanswered = _unanswered(quote, confirmations)
    return ComparisonRow(
        quote_id=quote.id,
        supplier_name=quote.supplier_name,
        comparable_total_eur=total,
        total_basis=quote.price_basis,
        lead_time_days=quote.lead_time_days,
        answered_count=max(len(confirmations) - len(unanswered), 0),
        unanswered=unanswered,
        blockers=tuple(blockers),
    )


def compare(
    quotes: tuple[SupplierQuote, ...] | list[SupplierQuote],
    *,
    requested_quantity: int | None = None,
    confirmations: tuple[str, ...] = (),
) -> QuoteComparison:
    """Build the comparison. Deterministic, and free of any model call.

    ``cheapest`` is named only among rows that share a price basis, because
    cheapest across a mixed basis is a claim about numbers that were never
    comparable. ``fastest`` needs no such care: days are days.
    """
    rows = tuple(_row(quote, requested_quantity, confirmations) for quote in quotes)

    totalled = [row for row in rows if row.comparable_total_eur is not None]
    bases = {row.total_basis for row in totalled}
    cheapest = (
        min(totalled, key=lambda row: row.comparable_total_eur or 0.0).quote_id
        if len(totalled) > 1 and len(bases) == 1
        else None
    )

    timed = [row for row in rows if row.lead_time_days is not None]
    fastest = (
        min(timed, key=lambda row: row.lead_time_days or 0).quote_id if len(timed) > 1 else None
    )

    # A question counts as unanswered by everyone only if every reply left it -
    # with no replies at all, nothing has been left unanswered yet.
    unanswered_by_everyone: tuple[str, ...] = ()
    if rows:
        common = set(rows[0].unanswered)
        for row in rows[1:]:
            common &= set(row.unanswered)
        unanswered_by_everyone = tuple(item for item in confirmations if item in common)

    return QuoteComparison(
        rows=rows,
        requested_quantity=requested_quantity,
        cheapest_quote_id=cheapest,
        fastest_quote_id=fastest,
        unanswered_by_everyone=unanswered_by_everyone,
        note=_note(len(totalled), len(rows), bases),
    )


def _note(totalled: int, total_rows: int, bases: set[PriceBasis]) -> str:
    """One sentence saying what the table can and cannot tell you."""
    if total_rows == 0:
        return "No replies captured yet."
    if totalled == 0:
        return "No reply could be totalled - see the reason beside each supplier."
    if totalled < total_rows:
        return f"{totalled} of {total_rows} replies could be totalled and compared."
    if len(bases) > 1:
        return "Totals are not ranked: these prices are not all on the same basis."
    return f"All {total_rows} replies could be totalled on the same basis."
