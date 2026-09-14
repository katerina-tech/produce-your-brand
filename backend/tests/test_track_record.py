"""Track records: what they promise, and what they must never do.

Two groups of tests here. The first is ordinary validation - the model refuses
the combinations that would let a number read as stronger evidence than it is.
The second is the one that matters: proof that attaching a track record cannot
change a ranking. That is a design decision, and a decision nobody tested is
just a comment.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.domain.enums import ProductCategory, ProductionMethod
from app.domain.requirement import ProductionRequirement
from app.domain.track_record import TrackRecord
from app.repositories.supplier_repo import SupplierRepository
from app.repositories.track_record_repo import TrackRecordRepository
from app.tools.registry import ProductionTools

DATA = Path(__file__).resolve().parent.parent / "data"


# ------------------------------------------------------------------ the model


def test_a_rating_must_rest_on_counted_ratings() -> None:
    """An average with no ratings behind it is a number with no evidence."""
    with pytest.raises(ValueError, match="zero ratings"):
        TrackRecord(supplier_id="s1", average_rating=4.5, rating_count=0)


def test_counted_ratings_must_produce_an_average() -> None:
    with pytest.raises(ValueError, match="no average"):
        TrackRecord(supplier_id="s1", rating_count=7)


def test_a_completion_date_implies_a_completed_order() -> None:
    with pytest.raises(ValueError, match="at least one completed order"):
        TrackRecord(supplier_id="s1", last_completed_on=date(2026, 1, 1))


def test_a_new_partner_is_empty_rather_than_zero_rated() -> None:
    """The distinction the whole module exists for: unrated is not badly rated."""
    record = TrackRecord(supplier_id="s1")

    assert record.is_empty is True
    assert record.has_ratings is False
    assert record.average_rating is None, "an absent rating must stay absent, never become 0"
    assert record.summary() == "No completed orders yet"


def test_summary_always_states_what_the_average_rests_on() -> None:
    record = TrackRecord(supplier_id="s1", average_rating=4.9, rating_count=2, completed_orders=3)

    summary = record.summary()

    assert "4.9/5" in summary
    assert "2 ratings" in summary, "a rating without its count overstates the evidence"
    assert "3 completed orders" in summary


def test_singular_and_plural_are_not_mangled() -> None:
    record = TrackRecord(supplier_id="s1", average_rating=5.0, rating_count=1, completed_orders=1)

    assert "1 rating" in record.summary()
    assert "1 completed order" in record.summary()


def test_demo_is_the_default_so_trust_must_be_granted_deliberately() -> None:
    assert TrackRecord(supplier_id="s1").is_demo is True


# ------------------------------------------------------------- the repository


def test_a_missing_dataset_is_not_an_error(tmp_path: Path) -> None:
    """A deployment without the newest dataset simply has no histories."""
    repo = TrackRecordRepository(tmp_path / "absent.json")

    assert repo.all() == ()
    assert repo.for_supplier("syn-001") is None


def test_duplicate_supplier_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "track_records.json"
    path.write_text(
        json.dumps(
            {
                "track_records": [
                    {"supplier_id": "syn-001"},
                    {"supplier_id": "syn-001"},
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate"):
        TrackRecordRepository(path).all()


def test_the_shipped_dataset_is_entirely_demo_data() -> None:
    """No real customer has rated anyone. If that ever changes it should be a
    deliberate edit that breaks this test, not a silent one."""
    records = TrackRecordRepository(DATA / "track_records.json").all()

    assert records, "the shipped dataset should not be empty"
    assert all(record.is_demo for record in records)


def test_the_shipped_dataset_includes_partners_without_history() -> None:
    """The empty state has to exist in the data, or the interface path that
    renders it is never exercised by anyone looking at the demo."""
    records = TrackRecordRepository(DATA / "track_records.json").all()

    assert any(record.is_empty for record in records)
    assert any(record.has_ratings for record in records)


# ------------------------------------------- the decision: shown, never scored


def _tools(with_records: bool) -> ProductionTools:
    return ProductionTools(
        SupplierRepository(DATA / "suppliers.json"),
        None,
        TrackRecordRepository(DATA / "track_records.json") if with_records else None,
    )


def test_track_records_do_not_change_scores_or_order() -> None:
    """The load-bearing test for this feature.

    The ranking's credibility rests on being explainable from six stated
    capability factors. If a rating could move it, that claim would quietly
    become false - so the same request is scored with and without the dataset
    and the scores and the order must be identical.
    """
    requirement = ProductionRequirement(
        product="tote bag", quantity=100, product_category=ProductCategory.TEXTILES
    )
    args = (requirement, ProductionMethod.SCREEN_PRINTING, date(2026, 9, 13))

    without = _tools(with_records=False).calculate_supplier_matches(*args, top_n=5)
    with_records = _tools(with_records=True).calculate_supplier_matches(*args, top_n=5)

    assert [m.supplier_id for m in without.matches] == [
        m.supplier_id for m in with_records.matches
    ], "attaching histories reordered the ranking"
    assert [m.score for m in without.matches] == [m.score for m in with_records.matches], (
        "attaching histories changed a score"
    )
    assert [m.factors for m in without.matches] == [m.factors for m in with_records.matches], (
        "attaching histories changed a factor breakdown"
    )


def test_matches_carry_the_history_when_the_dataset_is_present() -> None:
    requirement = ProductionRequirement(
        product="tote bag", quantity=100, product_category=ProductCategory.TEXTILES
    )
    result = _tools(with_records=True).calculate_supplier_matches(
        requirement, ProductionMethod.SCREEN_PRINTING, date(2026, 9, 13), top_n=5
    )

    assert result.matches, "the fixture request should match somebody"
    assert any(match.track_record is not None for match in result.matches)


def test_matches_are_unchanged_when_no_dataset_is_configured() -> None:
    """The repository is optional, and its absence must be invisible."""
    requirement = ProductionRequirement(
        product="tote bag", quantity=100, product_category=ProductCategory.TEXTILES
    )
    result = _tools(with_records=False).calculate_supplier_matches(
        requirement, ProductionMethod.SCREEN_PRINTING, date(2026, 9, 13), top_n=5
    )

    assert all(match.track_record is None for match in result.matches)
