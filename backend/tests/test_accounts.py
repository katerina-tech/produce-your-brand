"""Accounts, and the one rule they buy: a project belongs to somebody.

Two properties are worth more than the rest of this file, and both are here
because getting them wrong is silent:

**A wrong password and an unknown address answer identically.** A different
answer for "no such account" would hand an attacker a list of registered
addresses, which is a free target list for credential stuffing on other sites.

**A project you do not own answers 404, not 403.** 403 confirms the id exists,
which turns the endpoint into a way of discovering other people's projects one
guess at a time.

The app is built for real, on a database under ``tmp_path``, with only the
workflow swapped for a scripted provider - so the routing, the cookies and the
SQL under test are production code while no model is ever called.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.graph.workflow import GraphDeps, checkpointer_for, compile_workflow
from app.main import create_app
from app.repositories import db
from app.repositories.project_repo import ProjectRepository
from app.repositories.supplier_repo import SupplierRepository
from app.services.auth import SESSION_COOKIE
from app.services.project_service import ProjectService
from app.tools.registry import ProductionTools
from tests.conftest import BACKEND_ROOT, TODAY
from tests.test_graph import DEMO_REQUEST, _scripted

PASSWORD = "a-long-enough-passphrase"


@pytest.fixture
def api(tmp_path: Path) -> Iterator[TestClient]:
    """A live app with its own database, so registering here never touches the
    developer's own - accounts and projects share one file, as in production."""
    settings = Settings(
        upload_dir=tmp_path / "uploads",
        app_db_path=tmp_path / "app.db",
        checkpoint_db_path=tmp_path / "checkpoints.db",
        session_secret=SecretStr("test-secret-not-a-real-one"),
    )

    deps = GraphDeps(
        provider=_scripted(),
        tools=ProductionTools(SupplierRepository(BACKEND_ROOT / "data" / "suppliers.json")),
        today=TODAY,
    )
    workflow = compile_workflow(deps, checkpointer_for(settings.checkpoint_db_path))

    with TestClient(create_app(settings)) as client:
        connection: sqlite3.Connection = db.connect(settings.app_db_path)
        client.app.state.project_service = ProjectService(  # type: ignore[attr-defined]
            workflow, ProjectRepository(connection), today=TODAY, settings=settings
        )
        yield client
        connection.close()


def _register(api: TestClient, email: str) -> str:
    """Create an account and return its session token, leaving the client
    signed out so each request in a test says plainly who is making it."""
    response = api.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    token = api.cookies.get(SESSION_COOKIE)
    assert token
    api.cookies.clear()
    return str(token)


def _as(token: str | None) -> dict[str, str]:
    """Request headers for a given signed-in user, or for nobody."""
    return {"cookie": f"{SESSION_COOKIE}={token}"} if token else {}


def _create(api: TestClient, token: str | None = None) -> str:
    response = api.post("/api/projects", json={"request_text": DEMO_REQUEST}, headers=_as(token))
    assert response.status_code == 201, response.text
    return str(response.json()["project_id"])


# ------------------------------------------------------------------ accounts


def test_registering_signs_you_in_immediately(api: TestClient) -> None:
    """Being asked to sign in right after registering is a pointless step - the
    credentials were just proven correct by definition."""
    response = api.post(
        "/api/auth/register", json={"email": "Anna@Example.de", "password": PASSWORD}
    )

    assert response.status_code == 201
    assert response.json()["email"] == "anna@example.de", "the address should be normalised"
    assert api.get("/api/auth/me").json()["email"] == "anna@example.de"


def test_nobody_signed_in_is_a_normal_answer(api: TestClient) -> None:
    """Not an error. An anonymous visitor must reach the same product a
    signed-in one does, so the header asks this on every page."""
    assert api.get("/api/auth/me").json() is None


def test_an_address_can_only_be_registered_once(api: TestClient) -> None:
    _register(api, "anna@example.de")

    response = api.post(
        "/api/auth/register", json={"email": "anna@example.de", "password": PASSWORD}
    )

    assert response.status_code == 409


def test_a_short_password_is_refused_with_a_reason(api: TestClient) -> None:
    response = api.post("/api/auth/register", json={"email": "anna@example.de", "password": "xy"})

    assert response.status_code == 422
    assert "10 characters" in response.text


def test_a_wrong_password_and_an_unknown_address_are_indistinguishable(
    api: TestClient,
) -> None:
    """The property that keeps this from leaking who has an account."""
    _register(api, "anna@example.de")

    wrong = api.post("/api/auth/login", json={"email": "anna@example.de", "password": "nope-nope"})
    unknown = api.post("/api/auth/login", json={"email": "nobody@example.de", "password": PASSWORD})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json(), "the two answers must be identical, not merely similar"


def test_signing_out_and_back_in(api: TestClient) -> None:
    _register(api, "anna@example.de")

    api.post("/api/auth/login", json={"email": "anna@example.de", "password": PASSWORD})
    assert api.get("/api/auth/me").json() is not None

    api.post("/api/auth/logout")
    assert api.get("/api/auth/me").json() is None


def test_a_tampered_session_is_simply_signed_out(api: TestClient) -> None:
    """Forged, truncated and expired cookies are all just "not signed in".
    A caller that could tell them apart would be a caller that could leak which."""
    token = _register(api, "anna@example.de")
    forged = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")

    assert api.get("/api/auth/me", headers=_as(forged)).json() is None
    assert api.get("/api/auth/me", headers=_as("garbage")).json() is None


# ----------------------------------------------------------------- ownership


def test_an_anonymous_project_stays_open_to_everyone(api: TestClient) -> None:
    """The demo link in the funding application depends on exactly this: work
    started without an account is reachable by anyone holding the link."""
    project_id = _create(api)
    anna = _register(api, "anna@example.de")

    assert api.get(f"/api/projects/{project_id}").status_code == 200
    assert api.get(f"/api/projects/{project_id}", headers=_as(anna)).status_code == 200


def test_a_project_started_signed_in_is_invisible_to_everyone_else(api: TestClient) -> None:
    anna = _register(api, "anna@example.de")
    bruno = _register(api, "bruno@example.de")
    project_id = _create(api, anna)

    assert api.get(f"/api/projects/{project_id}", headers=_as(anna)).status_code == 200
    assert api.get(f"/api/projects/{project_id}", headers=_as(bruno)).status_code == 404
    assert api.get(f"/api/projects/{project_id}").status_code == 404


def test_a_stranger_is_refused_by_every_project_endpoint(api: TestClient) -> None:
    """One guarded route is not enough - a project is only private if reading,
    resuming, searching and answering are all closed."""
    anna = _register(api, "anna@example.de")
    bruno = _register(api, "bruno@example.de")
    project_id = _create(api, anna)

    stranger = _as(bruno)
    assert api.get(f"/api/projects/{project_id}", headers=stranger).status_code == 404
    nearby = api.get(f"/api/projects/{project_id}/nearby-studios", headers=stranger)
    assert nearby.status_code == 404
    assert (
        api.post(
            f"/api/projects/{project_id}/resume",
            json={"action": "confirm_brief"},
            headers=stranger,
        ).status_code
        == 404
    )
    assert (
        api.post(
            f"/api/projects/{project_id}/feedback",
            json={
                "found_useful": "yes",
                "would_contact_supplier": True,
                "alternative_approach": "chatgpt",
            },
            headers=stranger,
        ).status_code
        == 404
    )


def test_the_dashboard_shows_your_own_projects_and_the_unowned_ones(api: TestClient) -> None:
    """Signing in adds a private shelf without removing the shared one.

    Every project created before accounts existed is unowned, and a rule of
    "signed in means only mine" would have made all of them disappear the first
    time somebody registered.
    """
    shared = _create(api)
    anna = _register(api, "anna@example.de")
    bruno = _register(api, "bruno@example.de")
    hers = _create(api, anna)
    his = _create(api, bruno)

    listed = api.get("/api/projects", headers=_as(anna)).json()["projects"]
    rows = {row["id"]: row for row in listed}

    assert set(rows) == {shared, hers}
    assert his not in rows, "Bruno's project has no business being here"
    assert rows[hers]["mine"] is True
    assert rows[shared]["mine"] is False, "unowned is not the same as mine"


def test_an_anonymous_dashboard_shows_only_unowned_projects(api: TestClient) -> None:
    shared = _create(api)
    anna = _register(api, "anna@example.de")
    _create(api, anna)

    rows = api.get("/api/projects").json()["projects"]

    assert [row["id"] for row in rows] == [shared]


# --------------------------------------------------------------------- claim


def test_claiming_takes_an_unowned_project(api: TestClient) -> None:
    """How work started before signing in, or on another device, comes home."""
    project_id = _create(api)
    anna = _register(api, "anna@example.de")

    assert api.post(f"/api/projects/{project_id}/claim", headers=_as(anna)).status_code == 200

    assert api.get(f"/api/projects/{project_id}").status_code == 404, "it is private now"
    rows = api.get("/api/projects", headers=_as(anna)).json()["projects"]
    assert rows[0]["mine"] is True


def test_a_project_that_has_an_owner_cannot_be_taken(api: TestClient) -> None:
    """``owner_id IS NULL`` in the UPDATE is the whole safety property: claiming
    gives an unowned project an owner, and never changes one."""
    anna = _register(api, "anna@example.de")
    bruno = _register(api, "bruno@example.de")
    project_id = _create(api, anna)

    assert api.post(f"/api/projects/{project_id}/claim", headers=_as(bruno)).status_code == 404
    assert api.get(f"/api/projects/{project_id}", headers=_as(anna)).status_code == 200


def test_claiming_needs_an_account(api: TestClient) -> None:
    project_id = _create(api)

    assert api.post(f"/api/projects/{project_id}/claim").status_code == 401


def test_claiming_a_project_that_does_not_exist(api: TestClient) -> None:
    anna = _register(api, "anna@example.de")

    assert api.post("/api/projects/does-not-exist/claim", headers=_as(anna)).status_code == 404


def test_the_detail_endpoint_says_whether_a_project_is_yours(api: TestClient) -> None:
    """What the Keep button on the project screen is rendered from. ``False``
    can only mean unowned - somebody else's project never gets this far."""
    anna = _register(api, "anna@example.de")
    unowned = _create(api)
    hers = _create(api, anna)

    assert api.get(f"/api/projects/{hers}", headers=_as(anna)).json()["mine"] is True
    assert api.get(f"/api/projects/{unowned}", headers=_as(anna)).json()["mine"] is False
    assert api.get(f"/api/projects/{unowned}").json()["mine"] is False


# ------------------------------------------------- a deployment without a secret


@pytest.fixture
def unconfigured(tmp_path: Path) -> Iterator[TestClient]:
    """The same app with no session secret - which is how a deployment looks
    before somebody sets the environment variable."""
    settings = Settings(
        upload_dir=tmp_path / "uploads",
        app_db_path=tmp_path / "app.db",
        checkpoint_db_path=tmp_path / "checkpoints.db",
        session_secret=SecretStr(""),
    )
    with TestClient(create_app(settings)) as client:
        yield client


def test_without_a_secret_the_product_still_works(unconfigured: TestClient) -> None:
    """The property worth protecting. Sign-in is optional, so a missing secret
    must cost sign-in and nothing else - not every page a stale cookie touches.
    """
    assert unconfigured.get("/api/projects").status_code == 200
    assert unconfigured.get("/api/auth/me", headers=_as("a.stale.cookie")).json() is None
    assert unconfigured.get("/api/health").json()["checks"]["sign_in_configured"] is False


def test_without_a_secret_registering_says_so(unconfigured: TestClient) -> None:
    """503, not 500: the request was fine, the feature is not available here."""
    response = unconfigured.post(
        "/api/auth/register", json={"email": "anna@example.de", "password": PASSWORD}
    )

    assert response.status_code == 503
    assert "not configured" in response.text


def test_with_a_secret_health_says_so(api: TestClient) -> None:
    assert api.get("/api/health").json()["checks"]["sign_in_configured"] is True
