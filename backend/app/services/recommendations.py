"""Build recommendation perspectives from already-computed matches and offers.

Pure and deterministic, like :mod:`app.services.matching` - no LLM import, no
clock read (``today`` is a parameter), and it takes plain domain objects
rather than repositories, so it is testable with no I/O. It never re-scores a
supplier; ``best_match`` is simply the top-ranked entry the matcher already
produced.
"""

from __future__ import annotations

from datetime import date

from app.domain.enums import ProductionMethod
from app.domain.matching import MatchResult
from app.domain.offer import Offer
from app.domain.recommendation import RecommendationPerspective, RecommendationPerspectives
from app.domain.supplier import Supplier


def _active_offers_for(
    supplier_id: str,
    method: ProductionMethod,
    offers_by_supplier: dict[str, tuple[Offer, ...]],
    today: date,
) -> list[Offer]:
    """Offers on file for this supplier that are live today and apply to the
    confirmed method (or apply broadly - a null ``production_method``)."""
    candidates = offers_by_supplier.get(supplier_id, ())
    return [
        offer
        for offer in candidates
        if offer.is_active(today) and offer.production_method in (None, method)
    ]


def build_perspectives(
    matches: list[MatchResult],
    suppliers: dict[str, Supplier],
    offers_by_supplier: dict[str, tuple[Offer, ...]],
    method: ProductionMethod,
    today: date,
) -> RecommendationPerspectives:
    """``matches`` must already be the ranked, *eligible* top matches - the
    same list the UI's main ranking shows. Each perspective is left ``None``,
    not guessed, when nothing in ``matches`` actually has the data for it.
    """
    if not matches:
        return RecommendationPerspectives()

    best_match = RecommendationPerspective(
        supplier_id=matches[0].supplier_id,
        supplier_name=matches[0].supplier_name,
        headline=f"{matches[0].score:.0f}% compatibility",
    )

    best_price_value: float | None = None
    best_price: RecommendationPerspective | None = None
    fastest_days: int | None = None
    fastest: RecommendationPerspective | None = None

    for match in matches:
        supplier = suppliers.get(match.supplier_id)
        active_offers = _active_offers_for(match.supplier_id, method, offers_by_supplier, today)

        # Best price: only ever from an offer's price_from. Supplier records
        # carry no price field at all, so there is nothing to fall back to -
        # and nothing to invent.
        priced_offers = [offer for offer in active_offers if offer.price_from is not None]
        if priced_offers:
            cheapest = min(priced_offers, key=lambda offer: offer.price_from)  # type: ignore[arg-type,return-value]
            price = cheapest.price_from
            assert price is not None  # narrowed by the filter above
            if best_price_value is None or price < best_price_value:
                best_price_value = price
                best_price = RecommendationPerspective(
                    supplier_id=match.supplier_id,
                    supplier_name=match.supplier_name,
                    headline=f"{cheapest.currency} {price:.2f} estimated",
                    detail=cheapest.title,
                    offer_id=cheapest.id,
                    is_demo=cheapest.is_demo,
                )

        # Fastest: an offer's own lead_time_days is more specific (and more
        # recently updated) than the supplier's general typical_lead_time_days,
        # so prefer it when both exist.
        candidate_days: int | None = None
        candidate_offer: Offer | None = None
        offer_days = [offer for offer in active_offers if offer.lead_time_days is not None]
        if offer_days:
            candidate_offer = min(offer_days, key=lambda offer: offer.lead_time_days)  # type: ignore[arg-type,return-value]
            candidate_days = candidate_offer.lead_time_days
        elif supplier is not None and supplier.typical_lead_time_days is not None:
            candidate_days = supplier.typical_lead_time_days

        if candidate_days is not None and (fastest_days is None or candidate_days < fastest_days):
            fastest_days = candidate_days
            fastest = RecommendationPerspective(
                supplier_id=match.supplier_id,
                supplier_name=match.supplier_name,
                headline=f"{candidate_days} working days",
                detail=candidate_offer.title if candidate_offer else None,
                offer_id=candidate_offer.id if candidate_offer else None,
                is_demo=candidate_offer.is_demo if candidate_offer else False,
            )

    return RecommendationPerspectives(best_match=best_match, best_price=best_price, fastest=fastest)
