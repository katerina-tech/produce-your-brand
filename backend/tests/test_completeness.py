"""Deterministic completeness checking.

Covers the sprint requirement that missing critical information triggers a
clarification, and the product requirement that we ask as little as possible.
"""

from __future__ import annotations

from app.domain.enums import ProductCategory
from app.domain.requirement import ProductionRequirement
from app.services import completeness
from tests.conftest import DEMO_DEADLINE


def test_missing_quantity_triggers_clarification() -> None:
    """The canonical case from the spec: quantity is critical."""
    requirement = ProductionRequirement(
        product="yoga mats",
        customization_description="gold logo",
        customer_owns_product=True,
        material="PVC",
    )
    report = completeness.check(requirement)

    assert report.is_ready_for_review is False
    assert "quantity" in report.missing_critical
    assert report.next_field == "quantity"
    assert report.blocking_reason is not None


def test_missing_ownership_is_asked_about() -> None:
    """ "I want my logo on 100 yoga mats" must produce the ownership question.

    This is the exact exchange in the product spec, so it is pinned here.
    """
    requirement = ProductionRequirement(
        product="yoga mats", quantity=100, customization_description="my logo", material="PVC"
    )
    report = completeness.check(requirement)

    assert report.next_field == "customer_owns_product"
    reason = str(report.blocking_reason).lower()
    assert "supply" in reason or "source" in reason, (
        "the reason must explain the sourcing question to the user"
    )


def test_only_one_question_is_asked_at_a_time() -> None:
    """Even with everything missing, exactly one field is nominated next.

    The alternative - dumping a twelve-field form on the user - is the workflow
    this product exists to replace.
    """
    report = completeness.check(ProductionRequirement())

    assert len(report.missing_critical) == len(completeness.CRITICAL_FIELD_ORDER)
    assert report.next_field == "product", "highest-priority field first"


def test_question_priority_follows_the_declared_order() -> None:
    """Fields are asked in the order that unblocks the most work."""
    requirement = ProductionRequirement(product="yoga mats")
    assert completeness.check(requirement).next_field == "quantity"

    requirement = requirement.model_copy(update={"quantity": 100})
    assert completeness.check(requirement).next_field == "customization_description"


def test_optional_gaps_do_not_block_review() -> None:
    """A missing deadline or location must not interrogate the user.

    Those degrade gracefully in matching - partial score plus a risk flag - which
    is a better trade than another round of questions.
    """
    requirement = ProductionRequirement(
        product="yoga mats",
        quantity=100,
        customization_description="gold logo",
        customer_owns_product=True,
        material="PVC",
    )
    report = completeness.check(requirement)

    assert report.is_ready_for_review is True
    assert report.next_field is None
    assert "deadline" in report.missing_optional
    assert "location" in report.missing_optional


def test_complete_requirement_reports_nothing_missing() -> None:
    requirement = ProductionRequirement(
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
        priority=None,
    )
    report = completeness.check(requirement)

    assert report.is_ready_for_review is True
    assert report.missing_critical == ()


def test_check_is_a_pure_function() -> None:
    """Same input, same output - no accumulated state between calls."""
    requirement = ProductionRequirement(product="mats")
    assert completeness.check(requirement) == completeness.check(requirement)


def test_every_critical_field_has_a_label_and_a_reason() -> None:
    """A nominated field must always be explainable to the user."""
    for field in completeness.CRITICAL_FIELD_ORDER:
        assert field in completeness.FIELD_LABELS
        assert field in completeness.BLOCKING_REASONS


def test_labels_cover_every_requirement_field() -> None:
    """Adding a field to the requirement must not silently lose its UI label."""
    assert set(completeness.FIELD_LABELS) == set(ProductionRequirement.model_fields)


def test_describe_missing_returns_human_labels() -> None:
    report = completeness.check(ProductionRequirement(product="mats"))
    assert "Quantity" in completeness.describe_missing(report)
