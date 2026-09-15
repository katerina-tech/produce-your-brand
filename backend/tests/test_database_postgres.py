"""The repository layer, against a real PostgreSQL server.

Skipped unless ``PYS_TEST_DATABASE_URL`` points at one - and skipped *loudly*,
with a reason that says how to run it, because a migration nobody ever
exercised against the real database is a migration that has not been tested.
The rest of the suite passing does not mean this works.

    docker run -d --name pg -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:17-alpine
    PYS_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/postgres \\
        uv run python -m pytest tests/test_database_postgres.py

Every test builds its own schema in a private namespace and drops it afterwards,
so the file can be pointed at a shared server without eating anybody's data.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from app.domain.project import Project
from app.repositories import db
from app.repositories.database import Database, open_postgres
from app.repositories.project_repo import ProjectRepository
from app.repositories.user_repo import EmailAlreadyRegisteredError, UserRepository

DATABASE_URL = os.environ.get("PYS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason=(
        "no PostgreSQL server configured. Set PYS_TEST_DATABASE_URL to run these - "
        "without them the Postgres path is written but unverified."
    ),
)


@pytest.fixture
def database() -> Iterator[Database]:
    """A private schema on the configured server, dropped afterwards."""
    connection = open_postgres(DATABASE_URL)
    schema = f"pys_test_{uuid.uuid4().hex[:12]}"

    connection.execute(f'CREATE SCHEMA "{schema}"')
    connection.execute(f'SET search_path TO "{schema}"')
    connection.commit()

    db.initialize_schema(connection)
    yield connection

    connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
    connection.commit()
    connection.close()


def _project(project_id: str = "p1") -> Project:
    now = datetime.now(UTC)
    return Project(
        id=project_id,
        thread_id=f"thread-{project_id}",
        raw_request="100 yoga mats with a gold logo",
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------- the schema


def test_the_schema_builds_on_postgres(database: Database) -> None:
    """Including the one line the dialects spell differently."""
    tables = {
        row["table_name"]
        for row in database.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
        ).fetchall()
    }

    assert {"projects", "users", "project_events", "project_quotes"} <= tables


def test_applying_the_schema_twice_is_safe(database: Database) -> None:
    """A deployment runs it on every boot."""
    db.initialize_schema(database)

    assert "owner_id" in database.column_names("projects")


def test_the_migrations_find_their_columns(database: Database) -> None:
    """``column_names`` is the one question the dialects answer differently, and
    the migrations are the only caller. If it were wrong here, every boot would
    re-run an ALTER that had already happened."""
    assert {"owner_id", "design_upload_id"} <= database.column_names("projects")


# ----------------------------------------------------------- the repositories


def test_a_project_round_trips(database: Database) -> None:
    """The statements are written with ``?`` and translated on the way out. If
    the translation were wrong, this is where it would bind the wrong
    parameters."""
    repository = ProjectRepository(database)
    repository.save(_project())

    stored = repository.get("p1")

    assert stored is not None
    assert stored.raw_request == "100 yoga mats with a gold logo"


def test_saving_twice_updates_rather_than_duplicates(database: Database) -> None:
    """ON CONFLICT DO UPDATE is the same sentence in both databases, which is
    the sort of claim worth checking rather than assuming."""
    repository = ProjectRepository(database)
    repository.save(_project())
    repository.save(_project().model_copy(update={"raw_request": "changed"}))

    assert repository.get("p1") is not None
    assert repository.get("p1").raw_request == "changed"  # type: ignore[union-attr]
    assert len(repository.list_summaries()) == 1


def test_ownership_filters_the_way_it_does_on_sqlite(database: Database) -> None:
    repository = ProjectRepository(database)
    repository.save(_project("owned"))
    repository.save(_project("open"))
    repository.claim("owned", "anna")

    anonymous = {summary.id for summary in repository.list_summaries()}
    hers = {summary.id for summary in repository.list_summaries(viewer_id="anna")}

    assert anonymous == {"open"}
    assert hers == {"open", "owned"}


def test_a_duplicate_address_raises_the_same_error(database: Database) -> None:
    """The reason INTEGRITY_ERRORS is a tuple: psycopg's class is not sqlite3's,
    and the repository must not have to know which one it caught."""
    users = UserRepository(database)
    users.create("anna@example.de", "hash")

    with pytest.raises(EmailAlreadyRegisteredError):
        users.create("anna@example.de", "another hash")


# ---------------------------------------------------------------- behaviour


def test_a_failed_block_rolls_back_on_postgres_too(database: Database) -> None:
    """The wrapper promises this in both dialects. psycopg3's own ``with conn:``
    closes the connection instead, so the promise is the wrapper's to keep."""
    repository = ProjectRepository(database)

    with pytest.raises(RuntimeError), database:
        database.execute(
            "INSERT INTO projects (id, thread_id, stage, raw_request, brief_confirmed,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            ("rolled-back", "t", "draft", "x", 0, "2026-09-15", "2026-09-15"),
        )
        raise RuntimeError("half way through")

    assert repository.get("rolled-back") is None


def test_the_connection_still_works_after_a_rollback(database: Database) -> None:
    with pytest.raises(RuntimeError), database:
        raise RuntimeError("boom")

    ProjectRepository(database).save(_project("after"))

    assert ProjectRepository(database).get("after") is not None
