"""build_perspectives: pure, deterministic, no I/O - see the module docstring
on why that matters (same guarantee as app.services.matching).

Every "no data -> None, never invented" case gets its own test, because that
is the one rule this module exists to enforce.
"""

from __future__ import annotations

from datetime import date

from app.domain.enums import ProductCategory, ProductionMethod
from app.domain.matching import MatchResult
from app.domain.offer import Offer
from app.domain.supplier import Location, Supplier
from app.services.recommendations import build_perspectives

TODAY = date(2026, 8, 21)
METHOD = ProductionMethod.SCREEN_PRINTING


def _supplier(supplier_id: str, **overrides: object) -> Supplier:
    defaults: dict[str, object] = {
        "id": supplier_id,
        "name": f"Supplier {supplier_id}",
        "location": Location(city="Berlin", country="DE"),
        "supported_methods": (METHOD,),
        "product_categories": (ProductCategory.TEXTILES,),
    }
    defaults.update(overrides)
    return Supplier.model_validate(defaults)


def _match(supplier_id: str, score: float = 80.0) -> MatchResult:
    return MatchResult(
        supplier_id=supplier_id,
        supplier_name=f"Supplier {supplier_id}",
        score=score,
        eligible=True,
        factors=(),
    )


def _offer(offer_id: str, supplier_id: str, **overrides: object) -> Offer:
    defaults: dict[str, object] = {
        "id": offer_id,
        "supplier_id": supplier_id,
        "title": f"Offer {offer_id}",
        "source": "demo_seed",
        "last_updated": TODAY,
        "is_demo": True,
    }
    defaults.update(overrides)
    return Offer.model_validate(defaults)


def test_no_matches_yields_no_perspectives() -> None:
    result = build_perspectives([], {}, {}, METHOD, TODAY)
    assert result.best_match is None
    assert result.best_price is None
    assert result.fastest is None


def test_best_match_is_always_the_top_ranked_entry() -> None:
    matches = [_match("syn-A", score=91.0), _match("syn-B", score=60.0)]
    result = build_perspectives(matches, {}, {}, METHOD, TODAY)
    assert result.best_match is not None
    assert result.best_match.supplier_id == "syn-A"
    assert result.best_match.headline == "91% compatibility"


def test_no_offers_and_no_lead_time_data_leaves_price_and_speed_unset() -> None:
    matches = [_match("syn-A")]
    suppliers = {"syn-A": _supplier("syn-A")}
    result = build_perspectives(matches, suppliers, {}, METHOD, TODAY)
    assert result.best_price is None
    assert result.fastest is None


def test_fastest_falls_back_to_supplier_typical_lead_time_with_no_offer() -> None:
    matches = [_match("syn-A")]
    suppliers = {"syn-A": _supplier("syn-A", typical_lead_time_days=9)}
    result = build_perspectives(matches, suppliers, {}, METHOD, TODAY)
    assert result.fastest is not None
    assert result.fastest.headline == "9 working days"
    assert result.fastest.is_demo is False


def test_an_active_priced_offer_becomes_best_price() -> None:
    matches = [_match("syn-A")]
    suppliers = {"syn-A": _supplier("syn-A")}
    offer = _offer("off-1", "syn-A", price_from=4.5, currency="EUR")
    result = build_perspectives(matches, suppliers, {"syn-A": (offer,)}, METHOD, TODAY)
    assert result.best_price is not None
    assert result.best_price.headline == "EUR 4.50 estimated"
    assert result.best_price.offer_id == "off-1"
    assert result.best_price.is_demo is True


def test_cheapest_offer_wins_across_suppliers() -> None:
    matches = [_match("syn-A"), _match("syn-B")]
    suppliers = {"syn-A": _supplier("syn-A"), "syn-B": _supplier("syn-B")}
    offers: dict[str, tuple[Offer, ...]] = {
        "syn-A": (_offer("off-A", "syn-A", price_from=9.0),),
        "syn-B": (_offer("off-B", "syn-B", price_from=3.0),),
    }
    result = build_perspectives(matches, suppliers, offers, METHOD, TODAY)
    assert result.best_price is not None
    assert result.best_price.supplier_id == "syn-B"


def test_an_offer_still_lacking_a_price_never_becomes_best_price() -> None:
    matches = [_match("syn-A")]
    suppliers = {"syn-A": _supplier("syn-A")}
    offer = _offer("off-1", "syn-A", price_from=None)
    result = build_perspectives(matches, suppliers, {"syn-A": (offer,)}, METHOD, TODAY)
    assert result.best_price is None


def test_an_expired_offer_is_ignored() -> None:
    matches = [_match("syn-A")]
    suppliers = {"syn-A": _supplier("syn-A")}
    offer = _offer("off-1", "syn-A", price_from=1.0, valid_until=date(2026, 1, 1))
    result = build_perspectives(matches, suppliers, {"syn-A": (offer,)}, METHOD, TODAY)
    assert result.best_price is None


def test_an_offer_for_a_different_method_is_ignored() -> None:
    matches = [_match("syn-A")]
    suppliers = {"syn-A": _supplier("syn-A")}
    offer = _offer(
        "off-1", "syn-A", price_from=1.0, production_method=ProductionMethod.LASER_ENGRAVING
    )
    result = build_perspectives(matches, suppliers, {"syn-A": (offer,)}, METHOD, TODAY)
    assert result.best_price is None


def test_an_offer_with_no_method_restriction_applies_broadly() -> None:
    matches = [_match("syn-A")]
    suppliers = {"syn-A": _supplier("syn-A")}
    offer = _offer("off-1", "syn-A", price_from=1.0, production_method=None)
    result = build_perspectives(matches, suppliers, {"syn-A": (offer,)}, METHOD, TODAY)
    assert result.best_price is not None


def test_an_offers_lead_time_is_preferred_over_the_suppliers_general_one() -> None:
    matches = [_match("syn-A")]
    suppliers = {"syn-A": _supplier("syn-A", typical_lead_time_days=20)}
    offer = _offer("off-1", "syn-A", lead_time_days=5)
    result = build_perspectives(matches, suppliers, {"syn-A": (offer,)}, METHOD, TODAY)
    assert result.fastest is not None
    assert result.fastest.headline == "5 working days"
    assert result.fastest.offer_id == "off-1"
    assert result.fastest.is_demo is True
