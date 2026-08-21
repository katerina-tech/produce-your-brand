"""Persistence and RFQ assembly.

Two sprint requirements land here: long-term memory (create a project, leave,
return to its confirmed state) and that an RFQ requires explicit human approval.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.domain.enums import ProductCategory, ProductionMethod, Stage
from app.domain.project import Project
from app.domain.requirement import ProductionRequirement
from app.domain.supplier import Supplier
from app.repositories import db
from app.repositories.project_repo import ProjectRepository
from app.repositories.supplier_repo import SupplierRepository
from app.services import matching, rfq_builder
from tests.conftest import BACKEND_ROOT, DEMO_DEADLINE, TODAY


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = db.connect(tmp_path / "test.db")
    db.initialize_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def repo(connection: sqlite3.Connection) -> ProjectRepository:
    return ProjectRepository(connection)


@pytest.fixture
def demo_requirement() -> ProductionRequirement:
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


def _new_project() -> Project:
    now = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
    return Project(
        id="proj-1",
        thread_id="thread-1",
        raw_request="I have 100 black yoga mats and want my gold logo added.",
        created_at=now,
        updated_at=now,
    )


# ------------------------------------------------------------------ schema


def test_schema_is_idempotent(connection: sqlite3.Connection) -> None:
    """Startup runs this every time, so a second call must be harmless."""
    db.initialize_schema(connection)
    tables = {
        row["name"]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"projects", "project_events"} <= tables


# ----------------------------------------------------------- long-term memory


def test_project_round_trips_through_the_database(repo: ProjectRepository) -> None:
    saved = repo.save(_new_project())
    loaded = repo.get("proj-1")

    assert loaded is not None
    assert loaded.id == saved.id
    assert loaded.raw_request == saved.raw_request
    assert loaded.stage is Stage.DRAFT


def test_confirmed_state_survives_a_reconnect(
    tmp_path: Path, demo_requirement: ProductionRequirement
) -> None:
    """The 'leave and come back' guarantee, tested across two connections.

    A fresh connection stands in for a restarted process, which is the case that
    matters: the durable record must not depend on anything held in memory.
    """
    path = tmp_path / "memory.db"

    first = db.connect(path)
    db.initialize_schema(first)
    project = _new_project().model_copy(
        update={
            "requirement": demo_requirement,
            "brief_confirmed": True,
            "confirmed_method": ProductionMethod.HEAT_TRANSFER,
            "stage": Stage.SUPPLIER_SELECTION,
        }
    )
    ProjectRepository(first).save(project)
    first.close()

    second = db.connect(path)
    reloaded = ProjectRepository(second).get("proj-1")
    second.close()

    assert reloaded is not None
    assert reloaded.brief_confirmed is True
    assert reloaded.confirmed_method is ProductionMethod.HEAT_TRANSFER
    assert reloaded.stage is Stage.SUPPLIER_SELECTION
    assert reloaded.requirement is not None
    assert reloaded.requirement.quantity == 100
    assert reloaded.requirement.deadline == DEMO_DEADLINE


def test_save_is_an_upsert(repo: ProjectRepository) -> None:
    """The graph persists at several points; it should not track row existence."""
    repo.save(_new_project())
    repo.save(_new_project().model_copy(update={"stage": Stage.BRIEF_REVIEW}))

    loaded = repo.get("proj-1")
    assert loaded is not None
    assert loaded.stage is Stage.BRIEF_REVIEW


def test_save_refreshes_updated_at(repo: ProjectRepository) -> None:
    original = _new_project()
    stored = repo.save(original)
    assert stored.updated_at > original.updated_at


def test_matches_round_trip_with_their_factor_breakdown(
    repo: ProjectRepository,
    suppliers: tuple[Supplier, ...],
    demo_requirement: ProductionRequirement,
) -> None:
    """Score breakdowns must survive persistence, or the UI loses its reasoning."""
    outcome = matching.rank_matches(
        suppliers, demo_requirement, ProductionMethod.HEAT_TRANSFER, TODAY
    )
    repo.save(_new_project().model_copy(update={"matches": outcome.top}))

    loaded = repo.get("proj-1")
    assert loaded is not None
    assert len(loaded.matches) == 3
    assert loaded.matches[0].score == outcome.top[0].score
    assert len(loaded.matches[0].factors) == 6


def test_unknown_project_returns_none(repo: ProjectRepository) -> None:
    assert repo.get("does-not-exist") is None


def test_lookup_by_thread_id(repo: ProjectRepository) -> None:
    repo.save(_new_project())
    assert repo.get_by_thread("thread-1") is not None
    assert repo.get_by_thread("other") is None


def test_dashboard_summaries_are_newest_first(
    repo: ProjectRepository, demo_requirement: ProductionRequirement
) -> None:
    repo.save(_new_project().model_copy(update={"requirement": demo_requirement}))
    repo.save(
        _new_project().model_copy(
            update={"id": "proj-2", "thread_id": "thread-2", "requirement": demo_requirement}
        )
    )

    summaries = repo.list_summaries()
    assert len(summaries) == 2
    assert summaries[0].updated_at >= summaries[1].updated_at
    assert summaries[0].product == "black yoga mats"
    assert summaries[0].quantity == 100


def test_summary_tolerates_a_project_with_no_requirement_yet(repo: ProjectRepository) -> None:
    repo.save(_new_project())
    summary = repo.list_summaries()[0]
    assert summary.product is None
    assert summary.quantity is None


# ------------------------------------------------------- human-in-the-loop audit


def test_human_approvals_are_recorded_as_events(repo: ProjectRepository) -> None:
    """Approvals must be auditable after the fact, not inferred from end state."""
    repo.save(_new_project())
    repo.add_event("proj-1", "brief_confirmed", "human", {"edited": False})
    repo.add_event("proj-1", "method_confirmed", "human", {"method": "heat_transfer"})
    repo.add_event("proj-1", "supplier_matching_completed", "agent", {"candidates": 7})

    events = repo.events("proj-1")
    assert [event.event_type for event in events] == [
        "brief_confirmed",
        "method_confirmed",
        "supplier_matching_completed",
    ]
    human = [event for event in events if event.actor == "human"]
    assert len(human) == 2
    assert human[1].payload["method"] == "heat_transfer"


def test_events_are_scoped_to_their_project(repo: ProjectRepository) -> None:
    repo.save(_new_project())
    repo.save(_new_project().model_copy(update={"id": "proj-2", "thread_id": "thread-2"}))
    repo.add_event("proj-1", "brief_confirmed", "human")

    assert len(repo.events("proj-1")) == 1
    assert repo.events("proj-2") == []


# ------------------------------------------------------------ supplier repo


def test_supplier_repository_loads_and_indexes_the_dataset() -> None:
    repo = SupplierRepository(BACKEND_ROOT / "data" / "suppliers.json")
    assert repo.count() == 24
    assert repo.get("syn-004") is not None
    assert repo.get("syn-004").name == "Neukoelln Foil and Finish"  # type: ignore[union-attr]


def test_unknown_supplier_id_returns_none_rather_than_raising() -> None:
    """This is the check that makes an invented supplier id harmless.

    An LLM that names a partner we do not have is resolved to None and dropped,
    rather than propagating a fabricated capability into a match.
    """
    repo = SupplierRepository(BACKEND_ROOT / "data" / "suppliers.json")
    assert repo.get("syn-999-fabricated") is None
    assert repo.exists("syn-999-fabricated") is False


def test_supplier_repository_rejects_duplicate_ids(tmp_path: Path) -> None:
    duplicated = tmp_path / "dupes.json"
    duplicated.write_text(
        """
        {"suppliers": [
          {"id": "a", "name": "A", "location": {"city": "Berlin", "country": "DE"},
           "supported_methods": ["embroidery"], "product_categories": ["apparel"]},
          {"id": "a", "name": "B", "location": {"city": "Berlin", "country": "DE"},
           "supported_methods": ["embroidery"], "product_categories": ["apparel"]}
        ]}
        """,
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        SupplierRepository(duplicated).all()


# -------------------------------------------------------------------- rfq


def test_rfq_is_generated_unapproved(
    suppliers: tuple[Supplier, ...], demo_requirement: ProductionRequirement
) -> None:
    """Generation is not approval. The workflow cannot complete on this alone."""
    supplier = next(s for s in suppliers if s.id == "syn-004")
    rfq = rfq_builder.build_rfq(demo_requirement, ProductionMethod.HEAT_TRANSFER, supplier)

    assert rfq.approved is False
    assert rfq.supplier_id == "syn-004"
    assert rfq.quantity == 100
    assert rfq.customer_supplies_product is True


def test_rfq_asks_the_questions_that_matter(
    suppliers: tuple[Supplier, ...], demo_requirement: ProductionRequirement
) -> None:
    """The checklist is code, so it cannot be silently dropped by a model."""
    supplier = next(s for s in suppliers if s.id == "syn-004")
    rfq = rfq_builder.build_rfq(demo_requirement, ProductionMethod.HEAT_TRANSFER, supplier)
    checklist = " ".join(rfq.confirmations_requested).lower()

    for topic in ("feasibility", "price", "setup", "minimum order", "sample", "artwork"):
        assert topic in checklist
    assert "customer-owned" in checklist


def test_rfq_marks_unknowns_explicitly_rather_than_inventing(
    suppliers: tuple[Supplier, ...],
) -> None:
    """An unknown field must read as unspecified, never be quietly filled in."""
    sparse = ProductionRequirement(
        product="tote bags", quantity=200, customization_description="logo print"
    )
    supplier = next(s for s in suppliers if s.id == "syn-002")
    rfq = rfq_builder.build_rfq(sparse, ProductionMethod.SCREEN_PRINTING, supplier)
    rendered = rfq_builder.render_markdown(rfq)

    assert rfq.deadline is None
    assert rfq.customer_supplies_product is None
    assert rfq_builder.NOT_SPECIFIED in rendered
    assert "Material has not been confirmed" in " ".join(rfq.additional_notes)


def test_rfq_accepts_llm_polished_prose_without_changing_facts(
    suppliers: tuple[Supplier, ...], demo_requirement: ProductionRequirement
) -> None:
    """The model may rewrite tone; the factual fields stay builder-owned."""
    supplier = next(s for s in suppliers if s.id == "syn-004")
    default = rfq_builder.build_rfq(demo_requirement, ProductionMethod.HEAT_TRANSFER, supplier)
    polished = rfq_builder.build_rfq(
        demo_requirement,
        ProductionMethod.HEAT_TRANSFER,
        supplier,
        intro="Custom intro.",
        closing="Custom closing.",
    )

    assert polished.intro == "Custom intro."
    assert polished.product_summary == default.product_summary
    assert polished.confirmations_requested == default.confirmations_requested


def test_rendered_rfq_contains_the_key_facts(
    suppliers: tuple[Supplier, ...], demo_requirement: ProductionRequirement
) -> None:
    supplier = next(s for s in suppliers if s.id == "syn-004")
    rendered = rfq_builder.render_markdown(
        rfq_builder.build_rfq(demo_requirement, ProductionMethod.HEAT_TRANSFER, supplier)
    )

    assert "Neukoelln Foil and Finish" in rendered
    assert "100 x black yoga mats (PVC)" in rendered
    assert "2026-09-15" in rendered
    assert "Berlin" in rendered
    assert "heat transfer" in rendered
