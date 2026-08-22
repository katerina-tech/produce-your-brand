"""Project orchestration: pause/resume across a service boundary, plus memory.

This is the layer the API will sit on, so it is tested without HTTP: create a
project, walk every gate, and confirm the durable record and audit trail agree
with what the workflow did.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.domain.enums import Stage
from app.graph.workflow import GraphDeps, checkpointer_for, compile_workflow
from app.repositories import db
from app.repositories.project_repo import ProjectRepository
from app.repositories.supplier_repo import SupplierRepository
from app.services.project_service import ProjectService, StageMismatchError
from app.tools.registry import ProductionTools
from tests.conftest import BACKEND_ROOT, TODAY
from tests.test_graph import DEMO_REQUEST, _scripted


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = db.connect(tmp_path / "app.db")
    db.initialize_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def service(connection: sqlite3.Connection, tmp_path: Path) -> ProjectService:
    deps = GraphDeps(
        provider=_scripted(),
        tools=ProductionTools(SupplierRepository(BACKEND_ROOT / "data" / "suppliers.json")),
        today=TODAY,
    )
    workflow = compile_workflow(deps, checkpointer_for(tmp_path / "ckpt.db"))
    return ProjectService(workflow, ProjectRepository(connection), today=TODAY)


def _walk_to_completion(service: ProjectService) -> tuple[str, list[Stage]]:
    """Drive the demo scenario through every gate, recording the stages seen."""
    view = service.create(DEMO_REQUEST)
    seen = [view.stage]

    view = service.resume(view.project_id, "confirm_brief", {})
    seen.append(view.stage)

    view = service.resume(view.project_id, "confirm_method", {"method": "heat_transfer"})
    seen.append(view.stage)

    assert view.payload is not None
    supplier_id = view.payload["matches"][0]["supplier_id"]
    view = service.resume(view.project_id, "select_supplier", {"supplier_id": supplier_id})
    seen.append(view.stage)

    view = service.resume(view.project_id, "approve_rfq", {"approved": True})
    seen.append(view.stage)
    return view.project_id, seen


# ------------------------------------------------------------------ creating


def test_create_runs_to_the_first_gate(service: ProjectService) -> None:
    view = service.create(DEMO_REQUEST)

    assert view.stage is Stage.BRIEF_REVIEW
    assert view.expected_action == "confirm_brief"
    assert view.payload is not None
    assert view.payload["requirement"]["quantity"] == 100
    assert view.is_complete is False


def test_create_persists_immediately(
    service: ProjectService, connection: sqlite3.Connection
) -> None:
    """The project must exist in storage before the first gate is answered.

    Otherwise a user who closes the tab at the review screen loses the work.
    """
    view = service.create(DEMO_REQUEST)

    stored = ProjectRepository(connection).get(view.project_id)
    assert stored is not None
    assert stored.raw_request == DEMO_REQUEST
    assert stored.requirement is not None


# ------------------------------------------------------------- full journey


def test_full_journey_reaches_completion(service: ProjectService) -> None:
    _, seen = _walk_to_completion(service)

    assert seen == [
        Stage.BRIEF_REVIEW,
        Stage.METHOD_REVIEW,
        Stage.SUPPLIER_SELECTION,
        Stage.RFQ_REVIEW,
        Stage.COMPLETED,
    ]


def test_completed_project_is_durable_and_approved(
    service: ProjectService, connection: sqlite3.Connection
) -> None:
    project_id, _ = _walk_to_completion(service)

    stored = ProjectRepository(connection).get(project_id)
    assert stored is not None
    assert stored.stage is Stage.COMPLETED
    assert stored.rfq is not None
    assert stored.rfq.approved is True
    assert stored.is_complete is True
    assert stored.selected_supplier_id == "syn-004"
    assert len(stored.matches) == 3


def test_every_human_decision_is_audited(
    service: ProjectService, connection: sqlite3.Connection
) -> None:
    """Four gates answered means four human events on the record."""
    project_id, _ = _walk_to_completion(service)

    events = ProjectRepository(connection).events(project_id)
    human = [event.event_type for event in events if event.actor == "human"]

    assert human == ["confirm_brief", "confirm_method", "select_supplier", "approve_rfq"]


# ----------------------------------------------------- long-term memory


def test_project_can_be_reloaded_mid_workflow(service: ProjectService) -> None:
    """ "Leave and come back": the pending gate is recoverable, not lost."""
    created = service.create(DEMO_REQUEST)

    reloaded = service.get(created.project_id)

    assert reloaded is not None
    assert reloaded.stage is Stage.BRIEF_REVIEW
    assert reloaded.expected_action == "confirm_brief"
    assert reloaded.payload is not None
    assert reloaded.payload["requirement"]["product"] == "black yoga mats"


def test_reloading_does_not_advance_the_workflow(service: ProjectService) -> None:
    """Reading state must have no side effects."""
    created = service.create(DEMO_REQUEST)

    first = service.get(created.project_id)
    second = service.get(created.project_id)

    assert first is not None and second is not None
    assert first.stage is second.stage is Stage.BRIEF_REVIEW


def test_dashboard_lists_created_projects(service: ProjectService) -> None:
    service.create(DEMO_REQUEST)
    service.create("I need 500 engraved steel bottles in Munich.")

    summaries = service.list_summaries()
    assert len(summaries) == 2
    assert all(summary.product for summary in summaries)


def test_unknown_project_reads_as_none(service: ProjectService) -> None:
    assert service.get("no-such-project") is None


def test_resuming_an_unknown_project_raises(service: ProjectService) -> None:
    with pytest.raises(KeyError):
        service.resume("no-such-project", "confirm_brief", {})


# ------------------------------------------------------------ gate discipline


def test_wrong_action_for_the_current_gate_is_refused(service: ProjectService) -> None:
    """A stale tab must not resume into the wrong branch."""
    view = service.create(DEMO_REQUEST)

    with pytest.raises(StageMismatchError) as raised:
        service.resume(view.project_id, "approve_rfq", {"approved": True})

    assert raised.value.expected == "confirm_brief"
    assert raised.value.received == "approve_rfq"


def test_gate_is_still_answerable_after_a_refused_action(service: ProjectService) -> None:
    """A rejected action must not corrupt the pending gate."""
    view = service.create(DEMO_REQUEST)
    with pytest.raises(StageMismatchError):
        service.resume(view.project_id, "select_supplier", {"supplier_id": "syn-004"})

    resumed = service.resume(view.project_id, "confirm_brief", {})
    assert resumed.stage is Stage.METHOD_REVIEW


def test_edit_actions_are_accepted_at_their_gate(service: ProjectService) -> None:
    """``edit_brief`` is an alternative answer to the brief gate, not a new one."""
    view = service.create(DEMO_REQUEST)
    assert view.payload is not None

    edited = {**view.payload["requirement"], "quantity": 250}
    resumed = service.resume(view.project_id, "edit_brief", {"requirement": edited})

    assert resumed.stage is Stage.METHOD_REVIEW


def test_declining_the_rfq_does_not_complete_the_project(
    service: ProjectService, connection: sqlite3.Connection
) -> None:
    view = service.create(DEMO_REQUEST)
    view = service.resume(view.project_id, "confirm_brief", {})
    view = service.resume(view.project_id, "confirm_method", {"method": "heat_transfer"})
    assert view.payload is not None
    supplier_id = view.payload["matches"][0]["supplier_id"]
    view = service.resume(view.project_id, "select_supplier", {"supplier_id": supplier_id})

    final = service.resume(view.project_id, "approve_rfq", {"approved": False})

    assert final.is_complete is False
    assert final.stage is Stage.FAILED
    stored = ProjectRepository(connection).get(view.project_id)
    assert stored is not None
    assert stored.is_complete is False
