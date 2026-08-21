"""Deterministic supplier matching.

Covers the sprint's required matching behaviours: an incompatible supplier is not
highly ranked, MOQ incompatibility affects the score, customer-owned compatibility
affects the score, and the score is deterministic.

Every test runs against the real ``data/suppliers.json`` with a fixed ``today``,
so these assert production behaviour rather than fixture behaviour.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.enums import ProductCategory, ProductionMethod
from app.domain.matching import MAX_SCORE, FactorScore, MatchFactor, MatchResult, Verdict
from app.domain.requirement import ProductionRequirement
from app.domain.supplier import Supplier, SupplierQuery
from app.services import matching
from tests.conftest import DEMO_DEADLINE, TODAY


@pytest.fixture
def demo_requirement() -> ProductionRequirement:
    """The demo scenario: 100 customer-owned black yoga mats, gold logo, Berlin."""
    return ProductionRequirement(
        product="black yoga mats",
        product_category=ProductCategory.SPORTS_EQUIPMENT,
        material="PVC",
        quantity=100,
        customer_owns_product=True,
        customization_description="gold logo",
        design_available=True,
        preferred_finish="gold",
        deadline=DEMO_DEADLINE,
        location="Berlin",
    )


def _by_id(suppliers: tuple[Supplier, ...], supplier_id: str) -> Supplier:
    return next(supplier for supplier in suppliers if supplier.id == supplier_id)


def _factor(result: MatchResult, factor: MatchFactor) -> FactorScore:
    """Pull one factor out of a result, so assertions read as intent."""
    return next(score for score in result.factors if score.factor is factor)


# ------------------------------------------------------------- determinism


def test_score_is_deterministic_across_runs(
    suppliers: tuple[Supplier, ...], demo_requirement: ProductionRequirement
) -> None:
    """Identical inputs must produce byte-identical output, tie order included."""
    first = matching.rank_matches(
        suppliers, demo_requirement, ProductionMethod.HEAT_TRANSFER, TODAY
    )
    second = matching.rank_matches(
        suppliers, demo_requirement, ProductionMethod.HEAT_TRANSFER, TODAY
    )
    assert first.model_dump_json() == second.model_dump_json()


def test_ranking_is_stable_under_input_reordering(
    suppliers: tuple[Supplier, ...], demo_requirement: ProductionRequirement
) -> None:
    """Result order must come from the score, not from dataset order."""
    forward = matching.rank_matches(
        suppliers, demo_requirement, ProductionMethod.HEAT_TRANSFER, TODAY
    )
    reversed_input = matching.rank_matches(
        tuple(reversed(suppliers)), demo_requirement, ProductionMethod.HEAT_TRANSFER, TODAY
    )
    assert [m.supplier_id for m in forward.top] == [m.supplier_id for m in reversed_input.top]


def test_scorer_does_not_read_the_clock(
    suppliers: tuple[Supplier, ...], demo_requirement: ProductionRequirement
) -> None:
    """``today`` is a parameter, so a different 'today' must change the outcome.

    This is the property that makes deadline scoring testable at all.
    """
    near = matching.rank_matches(suppliers, demo_requirement, ProductionMethod.HEAT_TRANSFER, TODAY)
    late = matching.rank_matches(
        suppliers, demo_requirement, ProductionMethod.HEAT_TRANSFER, date(2026, 9, 14)
    )
    assert near.top[0].score != late.top[0].score


# --------------------------------------------------------------- hard gates


def test_supplier_without_the_method_is_not_ranked(
    suppliers: tuple[Supplier, ...], demo_requirement: ProductionRequirement
) -> None:
    """A partner that cannot do the job must not surface, however cheap or near.

    syn-005 is in Berlin, handles PVC, accepts customer goods and covers sports
    equipment - it fails only on the technique, and that alone must exclude it.
    """
    result = matching.score_supplier(
        _by_id(suppliers, "syn-005"),
        demo_requirement,
        ProductionMethod.HEAT_TRANSFER,
        TODAY,
    )
    assert result.eligible is False
    assert result.score == 0.0
    assert result.exclusion_reason is not None
    assert "heat transfer" in result.exclusion_reason

    outcome = matching.rank_matches(
        suppliers, demo_requirement, ProductionMethod.HEAT_TRANSFER, TODAY
    )
    assert "syn-005" not in [match.supplier_id for match in outcome.top]


def test_explicit_refusal_of_customer_goods_is_a_hard_gate(suppliers: tuple[Supplier, ...]) -> None:
    """syn-007 says False outright - it cannot be a match when we supply goods."""
    requirement = ProductionRequirement(
        product="steel bottles",
        product_category=ProductCategory.DRINKWARE,
        quantity=200,
        customer_owns_product=True,
        customization_description="engraved logo",
        material="stainless steel",
        location="Dresden",
    )
    result = matching.score_supplier(
        _by_id(suppliers, "syn-007"), requirement, ProductionMethod.LASER_ENGRAVING, TODAY
    )
    assert result.eligible is False
    assert result.exclusion_reason == "Does not accept customer-supplied goods."


def test_refusal_is_irrelevant_when_the_partner_sources_the_product(
    suppliers: tuple[Supplier, ...],
) -> None:
    """The same partner is fine when we are *not* supplying the goods.

    The gate is conditional on the sourcing model, not a blanket penalty.
    """
    requirement = ProductionRequirement(
        product="steel bottles",
        product_category=ProductCategory.DRINKWARE,
        quantity=200,
        customer_owns_product=False,
        customization_description="engraved logo",
        material="stainless steel",
        location="Dresden",
    )
    result = matching.score_supplier(
        _by_id(suppliers, "syn-007"), requirement, ProductionMethod.LASER_ENGRAVING, TODAY
    )
    assert result.eligible is True
    assert _factor(result, MatchFactor.CUSTOMER_OWNED).verdict is Verdict.MATCH


def test_excluded_suppliers_are_reported_with_reasons(
    suppliers: tuple[Supplier, ...], demo_requirement: ProductionRequirement
) -> None:
    """ "Why isn't my supplier here?" must be answerable by the UI."""
    outcome = matching.rank_matches(
        suppliers, demo_requirement, ProductionMethod.HEAT_TRANSFER, TODAY
    )
    assert outcome.excluded
    assert all(match.exclusion_reason for match in outcome.excluded)
    assert outcome.considered_count == len(suppliers)


# ------------------------------------------------------------ scored factors


def test_moq_above_order_quantity_zeroes_the_quantity_factor(
    suppliers: tuple[Supplier, ...], demo_requirement: ProductionRequirement
) -> None:
    """syn-010 has a 500 MOQ against an order of 100: eligible, but penalised."""
    result = matching.score_supplier(
        _by_id(suppliers, "syn-010"),
        demo_requirement,
        ProductionMethod.HEAT_TRANSFER,
        TODAY,
    )
    quantity = _factor(result, MatchFactor.QUANTITY)

    assert result.eligible is True, "MOQ is a scored factor, not a hard gate"
    assert quantity.awarded == 0.0
    assert quantity.verdict is Verdict.MISMATCH
    assert any("minimum" in flag for flag in result.risk_flags)
    assert result.score < 90.0


def test_unconfirmed_customer_goods_policy_scores_partially_with_a_flag(
    suppliers: tuple[Supplier, ...], demo_requirement: ProductionRequirement
) -> None:
    """null means unconfirmed, not refused: half credit plus a visible warning.

    This distinction is the whole reason the dataset stores None rather than False.
    """
    result = matching.score_supplier(
        _by_id(suppliers, "syn-019"),
        demo_requirement,
        ProductionMethod.HEAT_TRANSFER,
        TODAY,
    )
    owned = _factor(result, MatchFactor.CUSTOMER_OWNED)

    assert result.eligible is True
    assert owned.awarded == 7.5
    assert owned.verdict is Verdict.UNKNOWN
    assert any("customer-supplied" in flag for flag in result.risk_flags)


def test_confirmed_acceptance_outscores_unconfirmed(
    suppliers: tuple[Supplier, ...], demo_requirement: ProductionRequirement
) -> None:
    """Two Berlin partners, identical except for the policy field."""
    confirmed = matching.score_supplier(
        _by_id(suppliers, "syn-004"), demo_requirement, ProductionMethod.HEAT_TRANSFER, TODAY
    )
    unconfirmed = matching.score_supplier(
        _by_id(suppliers, "syn-019"), demo_requirement, ProductionMethod.HEAT_TRANSFER, TODAY
    )
    assert confirmed.score > unconfirmed.score


def test_material_mismatch_costs_points_without_excluding(
    suppliers: tuple[Supplier, ...], demo_requirement: ProductionRequirement
) -> None:
    """syn-013 works cork and wood, not PVC: penalised and flagged, still shown.

    Material is a judgement a human may want to override, so it is scored rather
    than gated - the partner might still take the job.
    """
    result = matching.score_supplier(
        _by_id(suppliers, "syn-013"),
        demo_requirement,
        ProductionMethod.HEAT_TRANSFER,
        TODAY,
    )
    material = _factor(result, MatchFactor.MATERIAL)

    assert result.eligible is True
    assert material.awarded == 0.0
    assert any("PVC" in flag for flag in result.risk_flags)


def test_unknown_material_scores_half_not_zero(
    suppliers: tuple[Supplier, ...], demo_requirement: ProductionRequirement
) -> None:
    """An unstated material must not be punished as if it were incompatible."""
    without_material = demo_requirement.model_copy(update={"material": None})
    result = matching.score_supplier(
        _by_id(suppliers, "syn-004"),
        without_material,
        ProductionMethod.HEAT_TRANSFER,
        TODAY,
    )
    material = _factor(result, MatchFactor.MATERIAL)

    assert material.awarded == 10.0
    assert material.verdict is Verdict.UNKNOWN
    assert any("Material not specified" in flag for flag in result.risk_flags)


def test_infeasible_deadline_is_penalised_and_flagged(
    suppliers: tuple[Supplier, ...], demo_requirement: ProductionRequirement
) -> None:
    """syn-018 needs 30 days plus buffer against a 25-day window."""
    requirement = demo_requirement.model_copy(
        update={
            "product_category": ProductCategory.DRINKWARE,
            "material": "stainless steel",
            "quantity": 300,
            "location": "Essen",
        }
    )
    result = matching.score_supplier(
        _by_id(suppliers, "syn-018"), requirement, ProductionMethod.LASER_ENGRAVING, TODAY
    )
    deadline = _factor(result, MatchFactor.DEADLINE)

    assert deadline.awarded < 10.0
    assert any("days" in flag.lower() for flag in result.risk_flags)


def test_unknown_lead_time_scores_half_with_a_flag(suppliers: tuple[Supplier, ...]) -> None:
    """syn-024 publishes neither lead time nor MOQ: partial credit, two flags."""
    requirement = ProductionRequirement(
        product="wooden coasters",
        product_category=ProductCategory.HOMEWARE,
        material="wood",
        quantity=150,
        customer_owns_product=True,
        customization_description="engraved logo",
        deadline=DEMO_DEADLINE,
        location="Erfurt",
    )
    result = matching.score_supplier(
        _by_id(suppliers, "syn-024"), requirement, ProductionMethod.LASER_ENGRAVING, TODAY
    )

    assert _factor(result, MatchFactor.DEADLINE).awarded == 5.0
    assert _factor(result, MatchFactor.QUANTITY).awarded == 7.5
    assert len(result.risk_flags) >= 2


def test_location_tiers_award_city_over_country_over_region(
    suppliers: tuple[Supplier, ...], demo_requirement: ProductionRequirement
) -> None:
    """Berlin > elsewhere in DE > elsewhere in the EU."""
    berlin = matching.score_supplier(
        _by_id(suppliers, "syn-004"), demo_requirement, ProductionMethod.HEAT_TRANSFER, TODAY
    )
    same_country = matching.score_supplier(
        _by_id(suppliers, "syn-003"), demo_requirement, ProductionMethod.HEAT_TRANSFER, TODAY
    )
    cross_border = matching.score_supplier(
        _by_id(suppliers, "syn-014"), demo_requirement, ProductionMethod.HEAT_TRANSFER, TODAY
    )

    assert _factor(berlin, MatchFactor.LOCATION).awarded == 10.0
    assert _factor(same_country, MatchFactor.LOCATION).awarded == 6.0
    assert _factor(cross_border, MatchFactor.LOCATION).awarded == 3.0


# -------------------------------------------------------------- score bounds


def test_scores_stay_within_bounds(
    suppliers: tuple[Supplier, ...], demo_requirement: ProductionRequirement
) -> None:
    outcome = matching.rank_matches(
        suppliers, demo_requirement, ProductionMethod.HEAT_TRANSFER, TODAY, top_n=99
    )
    for match in outcome.top:
        assert 0.0 <= match.score <= MAX_SCORE
        assert sum(factor.awarded for factor in match.factors) == pytest.approx(match.score)


def test_demo_scenario_produces_a_differentiated_top_three(
    suppliers: tuple[Supplier, ...], demo_requirement: ProductionRequirement
) -> None:
    """The demo must show a real ranking, not three identical scores.

    A flat top-three would make the weighting look decorative; this pins the
    scenario the reviewer will actually see.
    """
    outcome = matching.rank_matches(
        suppliers, demo_requirement, ProductionMethod.HEAT_TRANSFER, TODAY, top_n=3
    )
    scores = [match.score for match in outcome.top]

    assert len(outcome.top) == 3
    assert scores == sorted(scores, reverse=True)
    assert len(set(scores)) == 3, f"expected three distinct scores, got {scores}"
    assert outcome.top[0].supplier_id == "syn-004"


# ------------------------------------------------------------ normalisation


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PVC", "pvc"),
        ("polyvinyl chloride", "pvc"),
        ("black PVC", "pvc"),
        ("Natural Rubber", "natural_rubber"),
        ("anodized aluminum", "anodised_aluminium"),
        ("organic cotton", "cotton"),
        (None, None),
        ("  ", None),
    ],
)
def test_material_normalisation(raw: str | None, expected: str | None) -> None:
    assert matching.normalize_material(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Berlin", ("berlin", "DE")),
        ("Berlin, Germany", ("berlin", "DE")),
        ("Warsaw", ("warsaw", "PL")),
        ("Germany", (None, "DE")),
        (None, (None, None)),
    ],
)
def test_location_resolution(raw: str | None, expected: tuple[str | None, str | None]) -> None:
    assert matching.resolve_location(raw) == expected


# ------------------------------------------------------------------ search


def test_structural_search_filters_on_method_and_category(suppliers: tuple[Supplier, ...]) -> None:
    found = matching.search_suppliers(
        suppliers,
        SupplierQuery(
            method=ProductionMethod.HEAT_TRANSFER, category=ProductCategory.SPORTS_EQUIPMENT
        ),
    )
    assert found
    assert all(ProductionMethod.HEAT_TRANSFER in s.supported_methods for s in found)
    assert all(ProductCategory.SPORTS_EQUIPMENT in s.product_categories for s in found)
    assert [s.id for s in found] == sorted(s.id for s in found), "order must be stable"


def test_structural_search_can_filter_by_country(suppliers: tuple[Supplier, ...]) -> None:
    found = matching.search_suppliers(
        suppliers, SupplierQuery(method=ProductionMethod.LASER_ENGRAVING, country="CZ")
    )
    assert [s.id for s in found] == ["syn-015"]
