"""HTTP contract.

The frontend depends on exactly this surface, so these tests pin it: six
endpoints, one error envelope, and a resume endpoint that refuses an action the
workflow is not waiting for.

The app is built for real (lifespan included) and then its service is swapped for
one driven by a scripted provider, so the routing, validation and error handling
under test are production code while no model is ever called.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.graph.workflow import GraphDeps, checkpointer_for, compile_workflow
from app.main import create_app
from app.repositories import db
from app.repositories.project_repo import ProjectRepository
from app.repositories.supplier_repo import SupplierRepository
from app.services.project_service import ProjectService
from app.tools.registry import ProductionTools
from tests.conftest import BACKEND_ROOT, TODAY
from tests.fakes import ScriptedImageProvider
from tests.test_graph import DEMO_REQUEST, _scripted
from tests.test_security import JPEG, PDF, PNG

SHORT_REQUEST = "too short"


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    """Isolated settings so uploads made in tests never touch a real directory."""
    return Settings(upload_dir=tmp_path / "uploads")


@pytest.fixture
def api(tmp_path: Path, test_settings: Settings) -> Iterator[TestClient]:
    """A live app whose workflow runs on a scripted provider."""
    connection: sqlite3.Connection = db.connect(tmp_path / "api.db")
    db.initialize_schema(connection)

    deps = GraphDeps(
        provider=_scripted(),
        tools=ProductionTools(SupplierRepository(BACKEND_ROOT / "data" / "suppliers.json")),
        today=TODAY,
    )
    workflow = compile_workflow(deps, checkpointer_for(tmp_path / "api_ckpt.db"))

    with TestClient(create_app(test_settings)) as client:
        client.app.state.project_service = ProjectService(  # type: ignore[attr-defined]
            workflow, ProjectRepository(connection), today=TODAY, settings=test_settings
        )
        client.app.state.image_provider = ScriptedImageProvider()  # type: ignore[attr-defined]
        yield client

    connection.close()


def _create(api: TestClient) -> str:
    response = api.post("/api/projects", json={"request_text": DEMO_REQUEST})
    assert response.status_code == 201, response.text
    project_id: str = response.json()["project_id"]
    return project_id


# ---------------------------------------------------------------------- system


def test_health_reports_readiness(api: TestClient) -> None:
    body = api.get("/api/health").json()

    assert body["status"] in {"ok", "degraded"}
    assert body["checks"]["supplier_count"] == 24
    assert body["checks"]["knowledge_doc_count"] == 13


def test_health_leaks_no_secret(api: TestClient) -> None:
    assert "sk-" not in api.get("/api/health").text


def test_openapi_exposes_exactly_the_intended_surface(api: TestClient) -> None:
    """A new endpoint should be a deliberate decision, not a surprise."""
    paths = set(api.get("/openapi.json").json()["paths"])

    assert paths == {
        "/api/health",
        "/api/projects",
        "/api/projects/{project_id}",
        "/api/projects/{project_id}/resume",
        "/api/uploads",
        "/api/designs/generate",
    }


# -------------------------------------------------------------------- creating


def test_create_returns_the_first_gate(api: TestClient) -> None:
    response = api.post("/api/projects", json={"request_text": DEMO_REQUEST})

    assert response.status_code == 201
    body = response.json()
    assert body["stage"] == "brief_review"
    assert body["expected_action"] == "confirm_brief"
    assert body["payload"]["requirement"]["quantity"] == 100
    assert body["is_complete"] is False


def test_too_short_request_is_rejected(api: TestClient) -> None:
    response = api.post("/api/projects", json={"request_text": SHORT_REQUEST})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert response.json()["error"]["recoverable"] is True


def test_unknown_field_is_rejected(api: TestClient) -> None:
    """extra="forbid" on the wire contract catches client drift early."""
    response = api.post("/api/projects", json={"request_text": DEMO_REQUEST, "surprise": "value"})

    assert response.status_code == 422


# --------------------------------------------------------------------- reading


def test_project_can_be_fetched_after_creation(api: TestClient) -> None:
    project_id = _create(api)

    body = api.get(f"/api/projects/{project_id}").json()

    assert body["project_id"] == project_id
    assert body["stage"] == "brief_review"
    assert body["expected_action"] == "confirm_brief"


def test_unknown_project_is_404_with_the_shared_envelope(api: TestClient) -> None:
    response = api.get("/api/projects/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_404"


def test_dashboard_lists_projects(api: TestClient) -> None:
    _create(api)
    _create(api)

    body = api.get("/api/projects").json()

    assert len(body["projects"]) == 2
    assert body["projects"][0]["product"] == "black yoga mats"
    assert body["projects"][0]["quantity"] == 100


def test_dashboard_is_empty_before_any_project(api: TestClient) -> None:
    assert api.get("/api/projects").json() == {"projects": []}


# -------------------------------------------------------------------- resuming


def test_full_journey_over_http(api: TestClient) -> None:
    """Every human gate, driven through the API exactly as the frontend will."""
    project_id = _create(api)

    stages = []

    response = api.post(f"/api/projects/{project_id}/resume", json={"action": "confirm_brief"})
    stages.append(response.json()["stage"])

    response = api.post(
        f"/api/projects/{project_id}/resume",
        json={"action": "confirm_method", "method": "heat_transfer"},
    )
    stages.append(response.json()["stage"])

    supplier_id = response.json()["payload"]["matches"][0]["supplier_id"]
    response = api.post(
        f"/api/projects/{project_id}/resume",
        json={"action": "select_supplier", "supplier_id": supplier_id},
    )
    stages.append(response.json()["stage"])

    response = api.post(
        f"/api/projects/{project_id}/resume",
        json={"action": "approve_rfq", "approved": True},
    )
    stages.append(response.json()["stage"])

    assert stages == ["method_review", "supplier_selection", "rfq_review", "completed"]
    assert response.json()["is_complete"] is True


def test_wrong_action_returns_409_naming_the_expected_one(api: TestClient) -> None:
    """A stale tab gets a correctable answer, not a silently wrong branch."""
    project_id = _create(api)

    response = api.post(
        f"/api/projects/{project_id}/resume", json={"action": "approve_rfq", "approved": True}
    )

    assert response.status_code == 409
    assert "confirm_brief" in response.json()["error"]["message"]


def test_gate_still_works_after_a_rejected_action(api: TestClient) -> None:
    project_id = _create(api)
    api.post(f"/api/projects/{project_id}/resume", json={"action": "select_supplier"})

    response = api.post(f"/api/projects/{project_id}/resume", json={"action": "confirm_brief"})

    assert response.status_code == 200
    assert response.json()["stage"] == "method_review"


def test_resume_on_unknown_project_is_404(api: TestClient) -> None:
    response = api.post("/api/projects/nope/resume", json={"action": "confirm_brief"})
    assert response.status_code == 404


def test_unknown_action_is_rejected_by_schema(api: TestClient) -> None:
    project_id = _create(api)

    response = api.post(f"/api/projects/{project_id}/resume", json={"action": "delete_everything"})

    assert response.status_code == 422


def test_rfq_declined_over_http_does_not_complete(api: TestClient) -> None:
    """The final gate has to be answerable with "no" and mean it."""
    project_id = _create(api)
    api.post(f"/api/projects/{project_id}/resume", json={"action": "confirm_brief"})
    response = api.post(
        f"/api/projects/{project_id}/resume",
        json={"action": "confirm_method", "method": "heat_transfer"},
    )
    supplier_id = response.json()["payload"]["matches"][0]["supplier_id"]
    api.post(
        f"/api/projects/{project_id}/resume",
        json={"action": "select_supplier", "supplier_id": supplier_id},
    )

    final = api.post(
        f"/api/projects/{project_id}/resume",
        json={"action": "approve_rfq", "approved": False},
    )

    assert final.json()["is_complete"] is False
    assert final.json()["stage"] == "failed"


# --------------------------------------------------------------------- uploads


def test_valid_png_is_accepted(api: TestClient) -> None:
    response = api.post("/api/uploads", files={"file": ("logo.png", PNG, "image/png")})

    assert response.status_code == 201
    body = response.json()
    assert body["mime_type"] == "image/png"
    assert body["filename"] == "logo.png"
    assert len(body["upload_id"]) == 32


def test_valid_pdf_and_jpeg_are_accepted(api: TestClient) -> None:
    for name, content, mime in (
        ("art.pdf", PDF, "application/pdf"),
        ("art.jpg", JPEG, "image/jpeg"),
    ):
        response = api.post("/api/uploads", files={"file": (name, content, mime)})
        assert response.status_code == 201, response.text
        assert response.json()["mime_type"] == mime


def test_svg_upload_is_refused_with_a_reason(api: TestClient) -> None:
    response = api.post("/api/uploads", files={"file": ("logo.svg", b"<svg/>", "image/svg+xml")})

    assert response.status_code == 415
    assert "SVG" in response.json()["error"]["message"]


def test_disguised_file_is_refused(api: TestClient) -> None:
    """A PDF named .png must not slip through on its declared type."""
    response = api.post("/api/uploads", files={"file": ("logo.png", PDF, "image/png")})

    assert response.status_code == 415


def test_upload_response_never_returns_the_body(api: TestClient) -> None:
    """Metadata only - the file content is not echoed back to any client."""
    response = api.post("/api/uploads", files={"file": ("logo.png", PNG, "image/png")})

    assert set(response.json()) == {"upload_id", "filename", "mime_type", "size_bytes"}


# ----------------------------------------------------------------- error shape


def test_all_errors_use_one_envelope(api: TestClient) -> None:
    """The frontend should need exactly one error-handling path."""
    project_id = _create(api)

    responses = [
        api.get("/api/projects/missing"),
        api.post("/api/projects", json={"request_text": SHORT_REQUEST}),
        api.post(
            f"/api/projects/{project_id}/resume",
            json={"action": "approve_rfq", "approved": True},
        ),
        api.post("/api/uploads", files={"file": ("x.svg", b"<svg/>", "image/svg+xml")}),
    ]

    for response in responses:
        body = response.json()
        assert "error" in body, response.text
        assert {"code", "message"} <= set(body["error"])
        assert "Traceback" not in response.text


def test_product_travels_on_create_and_resume(api: TestClient) -> None:
    """The client titles the project from this, so it must be on every response."""
    created = api.post("/api/projects", json={"request_text": DEMO_REQUEST}).json()
    assert created["product"] == "black yoga mats"

    resumed = api.post(
        f"/api/projects/{created['project_id']}/resume", json={"action": "confirm_brief"}
    ).json()
    assert resumed["product"] == "black yoga mats"


# --------------------------------------------------------------------- designs


def test_generate_design_returns_a_preview(api: TestClient) -> None:
    """The one deliberate exception to 'the file body is never returned'."""
    response = api.post("/api/designs/generate", json={"prompt": "a gold star logo"})

    assert response.status_code == 201
    body = response.json()
    assert body["mime_type"] == "image/png"
    assert body["preview_data_url"].startswith("data:image/png;base64,")
    assert len(body["upload_id"]) == 32


def test_generate_design_rejects_an_empty_prompt(api: TestClient) -> None:
    response = api.post("/api/designs/generate", json={"prompt": ""})
    assert response.status_code == 422


def test_generate_design_rejects_an_overlong_prompt(api: TestClient) -> None:
    response = api.post("/api/designs/generate", json={"prompt": "x" * 501})
    assert response.status_code == 422


def test_generate_design_provider_failure_returns_a_typed_error(
    api: TestClient,
) -> None:
    """A provider refusal or outage is the upstream's fault, not the caller's."""
    from app.llm.factory import LLMError

    api.app.state.image_provider = ScriptedImageProvider(LLMError("refused"))  # type: ignore[attr-defined]

    response = api.post("/api/designs/generate", json={"prompt": "anything"})

    assert response.status_code == 502
    assert "error" in response.json()


def test_project_created_with_a_generated_design_has_design_available_true(
    api: TestClient,
) -> None:
    """The whole point: an attached design is a fact the brief must reflect."""
    generated = api.post("/api/designs/generate", json={"prompt": "a gold star logo"}).json()

    response = api.post(
        "/api/projects",
        json={"request_text": DEMO_REQUEST, "design_upload_id": generated["upload_id"]},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["design_upload_id"] == generated["upload_id"]
    assert body["payload"]["requirement"]["design_available"] is True


def test_project_created_with_an_uploaded_design_has_design_available_true(
    api: TestClient,
) -> None:
    uploaded = api.post("/api/uploads", files={"file": ("logo.png", PNG, "image/png")}).json()

    response = api.post(
        "/api/projects",
        json={"request_text": DEMO_REQUEST, "design_upload_id": uploaded["upload_id"]},
    )

    assert response.status_code == 201
    assert response.json()["payload"]["requirement"]["design_available"] is True


def test_project_creation_rejects_an_unknown_design_id(api: TestClient) -> None:
    """A client cannot attach a file that was never uploaded or generated."""
    response = api.post(
        "/api/projects",
        json={"request_text": DEMO_REQUEST, "design_upload_id": "0" * 32},
    )

    assert response.status_code == 422
    assert "error" in response.json()


def test_project_without_a_design_has_no_design_upload_id(api: TestClient) -> None:
    response = api.post("/api/projects", json={"request_text": DEMO_REQUEST})
    assert response.json()["design_upload_id"] is None
