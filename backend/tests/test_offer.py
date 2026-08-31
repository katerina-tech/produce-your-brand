"""The Offer domain model: validity windows and the demo/verified guard.

Dataset-level checks (every seeded record is labelled demo, references a real
supplier, etc.) live in test_foundations.py alongside the equivalent supplier
dataset checks. This file is about the model's own behaviour in isolation.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.domain.offer import Offer

TODAY = date(2026, 8, 21)


def _offer(**overrides: object) -> Offer:
    defaults: dict[str, object] = {
        "id": "off-test",
        "supplier_id": "syn-002",
        "title": "Test offer",
        "source": "demo_seed",
        "last_updated": TODAY,
        "is_demo": True,
    }
    defaults.update(overrides)
    return Offer.model_validate(defaults)


def test_a_demo_offer_cannot_also_be_verified() -> None:
    with pytest.raises(ValidationError, match="cannot also be verified"):
        _offer(is_demo=True, verified=True)


def test_a_non_demo_offer_may_be_verified() -> None:
    offer = _offer(is_demo=False, verified=True, source="manually_verified")
    assert offer.verified is True


def test_open_ended_offer_is_always_active() -> None:
    offer = _offer(valid_from=None, valid_until=None)
    assert offer.is_active(TODAY) is True
    assert offer.is_active(date(2030, 1, 1)) is True


def test_offer_is_inactive_before_its_start_date() -> None:
    offer = _offer(valid_from=date(2026, 9, 1), valid_until=None)
    assert offer.is_active(TODAY) is False
    assert offer.is_active(date(2026, 9, 1)) is True


def test_offer_is_inactive_after_its_end_date() -> None:
    offer = _offer(valid_from=None, valid_until=date(2026, 8, 1))
    assert offer.is_active(TODAY) is False
    assert offer.is_active(date(2026, 8, 1)) is True


def test_unknown_price_stays_null_not_zero() -> None:
    offer = _offer(price_from=None)
    assert offer.price_from is None
