"""Phase 0 foundations: contracts, dataset integrity, API boot, secret hygiene.

These are the invariants later phases build on. They are cheap and they fail
loudly if someone weakens a contract - notably the null discipline, which is what
stops the agent inventing supplier capabilities.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.matching import MAX_SCORE, WEIGHTS
from app.domain.offer import Offer
from app.domain.project import Project
from app.domain.requirement import ProductionRequirement
from app.domain.rfq import RFQ
from app.domain.supplier import Supplier
from app.logging_config import Event, redact_text

# --------------------------------------------------------------- contracts


def test_match_weights_match_the_documented_algorithm() -> None:
    """The README's weighting table and the code must not drift apart."""
    from app.domain.matching import MatchFactor

    assert MAX_SCORE == 100.0
    assert WEIGHTS == {
        MatchFactor.METHOD: 30.0,
        MatchFactor.MATERIAL: 20.0,
        MatchFactor.QUANTITY: 15.0,
        MatchFactor.CUSTOMER_OWNED: 15.0,
        MatchFactor.DEADLINE: 10.0,
        MatchFactor.LOCATION: 10.0,
    }


def test_requirement_defaults_to_all_unknown() -> None:
    """An empty requirement holds no invented values."""
    req = ProductionRequirement()
    assert req.known_fields() == set()
    assert req.quantity is None
    assert req.additional_constraints == []


def test_requirement_rejects_unknown_fields() -> None:
    """extra='forbid' is what makes a hallucinated field a validation error."""
    with pytest.raises(ValueError):
        ProductionRequirement.model_validate({"product": "mats", "colour_hex": "#FFD700"})


def test_requirement_merge_only_fills_gaps() -> None:
    """A clarification answer may add information, never silently revise it."""
    original = ProductionRequirement(product="black yoga mats", quantity=100)
    answer = ProductionRequirement(material="pvc", quantity=999, deadline=date(2026, 9, 15))

    merged = original.merge(answer)

    assert merged.material == "pvc"
    assert merged.quantity == 100, "an existing value must not be overwritten"
    assert merged.deadline == date(2026, 9, 15)


def test_rfq_is_not_approved_by_default() -> None:
    """Human approval must be an explicit act, never a default."""
    rfq = RFQ(
        supplier_id="syn-004",
        supplier_name="Neukoelln Foil and Finish",
        subject="RFQ",
        product_summary="100 black yoga mats",
        customization="Gold logo",
        preferred_method="heat_transfer",
        design_status="Available",
        intro="Hello",
        closing="Thanks",
    )
    assert rfq.approved is False
    assert len(rfq.confirmations_requested) == 9


def test_project_is_incomplete_without_approved_rfq() -> None:
    from datetime import datetime

    now = datetime(2026, 8, 21, 12, 0)
    project = Project(
        id="p1", thread_id="t1", raw_request="100 mats", created_at=now, updated_at=now
    )
    assert project.is_complete is False


# ------------------------------------------------------- dataset integrity


def test_supplier_dataset_validates(suppliers: tuple[Supplier, ...]) -> None:
    assert len(suppliers) == 24
    assert len({s.id for s in suppliers}) == len(suppliers), "supplier ids must be unique"


def test_supplier_dataset_is_labelled_synthetic(suppliers: tuple[Supplier, ...]) -> None:
    """Synthetic data must be honestly labelled and must not point at real firms."""
    assert all(s.data_source == "synthetic" for s in suppliers)
    assert all(s.website is None for s in suppliers)


def test_supplier_dataset_preserves_unknowns(suppliers: tuple[Supplier, ...]) -> None:
    """Unknown capabilities are null, not False and not zero.

    The matching service depends on this distinction: an unconfirmed policy
    scores partially with a risk flag, while an explicit False is a hard gate.
    """
    unknown_owned = [s for s in suppliers if s.accepts_customer_owned_products is None]
    explicit_no = [s for s in suppliers if s.accepts_customer_owned_products is False]
    assert unknown_owned, "dataset must exercise the unknown-policy path"
    assert explicit_no, "dataset must exercise the hard-incompatibility path"
    assert any(s.min_order_quantity is None for s in suppliers)
    assert any(s.typical_lead_time_days is None for s in suppliers)


def test_supplier_dataset_covers_every_supported_method(
    suppliers: tuple[Supplier, ...],
) -> None:
    """Every method the enum offers must be sourceable, or the enum is a lie."""
    from app.domain.enums import ProductionMethod

    covered = {method for s in suppliers for method in s.supported_methods}
    assert covered == set(ProductionMethod)


def test_supplier_provenance_block_matches_record_count() -> None:
    from tests.conftest import BACKEND_ROOT

    raw = json.loads((BACKEND_ROOT / "data" / "suppliers.json").read_text(encoding="utf-8"))
    assert raw["_provenance"]["record_count"] == len(raw["suppliers"])


def test_offer_dataset_validates(offers: tuple[Offer, ...]) -> None:
    assert len(offers) > 0
    assert len({o.id for o in offers}) == len(offers), "offer ids must be unique"
    assert all(o.supplier_id for o in offers)


def test_offer_dataset_is_labelled_demo(offers: tuple[Offer, ...]) -> None:
    """The MVP has zero real supplier offers - every seeded record must say so,
    and none may simultaneously claim to be verified (see Offer's validator)."""
    assert all(o.is_demo for o in offers)
    assert all(o.source == "demo_seed" for o in offers)
    assert all(not o.verified for o in offers)


def test_offer_dataset_preserves_unknown_price(offers: tuple[Offer, ...]) -> None:
    """Price on request is a real, exercised case - not every offer names a
    price, and the ones that do not must stay null rather than defaulting to
    a number that would read as free or arbitrary."""
    assert any(o.price_from is None for o in offers)
    assert any(o.price_from is not None for o in offers)


def test_offer_dataset_references_real_suppliers(
    offers: tuple[Offer, ...], suppliers: tuple[Supplier, ...]
) -> None:
    supplier_ids = {s.id for s in suppliers}
    assert all(o.supplier_id in supplier_ids for o in offers)


def test_offer_dataset_offers_methods_the_supplier_actually_supports(
    offers: tuple[Offer, ...], suppliers: tuple[Supplier, ...]
) -> None:
    by_id = {s.id: s for s in suppliers}
    for offer in offers:
        if offer.production_method is None:
            continue
        supplier = by_id[offer.supplier_id]
        assert offer.production_method in supplier.supported_methods, (
            f"{offer.id} offers {offer.production_method} but {supplier.id} does not support it"
        )


# ------------------------------------------------------------ secret hygiene


def test_settings_never_stringify_the_api_key() -> None:
    """SecretStr means an accidental log of settings cannot leak credentials."""
    loaded = Settings(OPENAI_API_KEY="sk-super-secret-value")
    assert "sk-super-secret-value" not in repr(loaded)
    assert "sk-super-secret-value" not in str(loaded.openai_api_key)
    assert loaded.openai_api_key.get_secret_value() == "sk-super-secret-value"


def test_redact_text_does_not_return_full_content() -> None:
    """User text is summarised for logs, never reproduced in full."""
    secretish = "confidential design brief " * 40
    redacted = redact_text(secretish)
    assert redacted["text_len"] == len(secretish)
    assert len(str(redacted["text_preview"])) < len(secretish)
    assert redacted["text_sha256"] is not None


def test_log_events_are_a_closed_set() -> None:
    """Event names live in one enum so logs stay greppable and consistent."""
    assert Event.SUPPLIER_MATCHING_COMPLETED.value == "supplier_matching_completed"
    assert len(set(Event)) == len(list(Event))


# ----------------------------------------------------------------- api boot


def test_health_endpoint_reports_readiness(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["checks"]["suppliers_file_present"] is True
    assert isinstance(body["checks"]["api_key_configured"], bool)


def test_health_response_contains_no_secret(client: TestClient) -> None:
    assert "sk-" not in client.get("/api/health").text


def test_unknown_route_returns_typed_error(client: TestClient) -> None:
    """Errors use the shared envelope so the frontend has one error path."""
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_404"
    assert response.json()["error"]["recoverable"] is True
