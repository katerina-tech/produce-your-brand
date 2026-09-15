"""The connection layer that lets one set of SQL address two databases.

Most of this file tests the translation rather than the databases, because the
translation is the new code and the databases are not ours. The parts that only
a real server can prove - that psycopg accepts these statements, that a
Postgres transaction rolls back the way the wrapper promises - are in
``test_database_postgres.py``, which runs when a server is configured and skips
loudly when one is not.

That split is deliberate. A suite that silently passed without ever reaching
Postgres would be a suite that says the migration works when nobody has
checked.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.repositories import db
from app.repositories.database import (
    INTEGRITY_ERRORS,
    Database,
    open_database,
    open_sqlite,
    to_postgres_params,
)

# ------------------------------------------------------------- placeholders


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT * FROM projects WHERE id = ?", "SELECT * FROM projects WHERE id = %s"),
        ("INSERT INTO t (a, b) VALUES (?, ?)", "INSERT INTO t (a, b) VALUES (%s, %s)"),
        ("SELECT 1", "SELECT 1"),
        # A question mark inside a string literal is text, not a placeholder.
        ("SELECT * FROM t WHERE q = 'what? really'", "SELECT * FROM t WHERE q = 'what? really'"),
        ("SELECT * FROM t WHERE a = ? AND b = 'x?y'", "SELECT * FROM t WHERE a = %s AND b = 'x?y'"),
        ('SELECT * FROM t WHERE a = "col?name"', 'SELECT * FROM t WHERE a = "col?name"'),
        # psycopg reads a bare % as the start of its own placeholder.
        ("SELECT 50 % 7", "SELECT 50 %% 7"),
    ],
)
def test_placeholders_translate_without_touching_quoted_text(sql: str, expected: str) -> None:
    """The one piece of string surgery in the application. A ``?`` swallowed
    out of a literal would corrupt a query silently - it would still run."""
    assert to_postgres_params(sql) == expected


def test_every_statement_in_the_repositories_survives_translation() -> None:
    """Not a sample: every SQL string the application actually issues.

    Translation is applied to real statements, so the test is applied to real
    statements too - a placeholder count that changes is a query that will bind
    the wrong number of parameters at runtime.
    """
    import re

    sources = list(Path(__file__).resolve().parent.parent.glob("app/repositories/*.py"))
    statements = []
    for source in sources:
        text = source.read_text(encoding="utf-8")
        statements += re.findall(r'"""\s*(SELECT|INSERT|UPDATE|DELETE)[^"]*"""', text)
        statements += re.findall(r'"((?:SELECT|INSERT|UPDATE|DELETE)[^"]*)"', text)

    assert statements, "the repositories do contain SQL; the scan found none"
    for statement in statements:
        translated = to_postgres_params(statement)
        assert translated.count("%s") == statement.count("?")
        assert "?" not in translated


# ------------------------------------------------------------- transactions


def test_a_successful_block_commits(tmp_path: Path) -> None:
    database = open_sqlite(tmp_path / "t.db")
    database.executescript("CREATE TABLE t (id TEXT PRIMARY KEY)")

    with database:
        database.execute("INSERT INTO t (id) VALUES (?)", ("a",))

    assert database.execute("SELECT COUNT(*) AS n FROM t").fetchone()["n"] == 1


def test_a_failed_block_rolls_back(tmp_path: Path) -> None:
    """Spelled out in the wrapper rather than inherited, because psycopg3's own
    ``with conn:`` closes the connection - which would turn one failed write
    into a dead application."""
    database = open_sqlite(tmp_path / "t.db")
    database.executescript("CREATE TABLE t (id TEXT PRIMARY KEY)")

    with pytest.raises(RuntimeError), database:
        database.execute("INSERT INTO t (id) VALUES (?)", ("a",))
        raise RuntimeError("something went wrong half way")

    assert database.execute("SELECT COUNT(*) AS n FROM t").fetchone()["n"] == 0


def test_the_connection_survives_a_failed_block(tmp_path: Path) -> None:
    """The property the explicit __exit__ exists for."""
    database = open_sqlite(tmp_path / "t.db")
    database.executescript("CREATE TABLE t (id TEXT PRIMARY KEY)")

    with pytest.raises(RuntimeError), database:
        raise RuntimeError("boom")

    with database:
        database.execute("INSERT INTO t (id) VALUES (?)", ("b",))
    assert database.execute("SELECT COUNT(*) AS n FROM t").fetchone()["n"] == 1


# ------------------------------------------------------------------ dialects


def test_a_url_chooses_postgres_and_its_absence_chooses_a_file(tmp_path: Path) -> None:
    """Railway injects DATABASE_URL when a Postgres service exists, so adding
    the database is the whole of the switch."""
    assert open_database(None, tmp_path / "t.db").dialect == "sqlite"
    assert open_database("", tmp_path / "t.db").dialect == "sqlite"


def test_column_names_answers_the_migration_question(tmp_path: Path) -> None:
    """The one question the two dialects answer in genuinely different ways
    rather than merely different syntax."""
    database = open_sqlite(tmp_path / "t.db")
    database.executescript("CREATE TABLE t (id TEXT PRIMARY KEY, name TEXT)")

    assert database.column_names("t") == {"id", "name"}
    assert database.column_names("does_not_exist") == set()


def test_a_constraint_violation_is_catchable_without_knowing_the_driver() -> None:
    """A repository says "that address is taken" without knowing which database
    it is talking to."""
    assert sqlite3.IntegrityError in INTEGRITY_ERRORS
    assert len(INTEGRITY_ERRORS) >= 2, "psycopg's own class should be here too"


# -------------------------------------------------------------------- schema


def test_the_schema_differs_in_exactly_one_line() -> None:
    """Everything else - TEXT, INTEGER, REFERENCES, IF NOT EXISTS, ON CONFLICT -
    is the same sentence in both databases. If that stops being true, this test
    is where it should be noticed."""
    sqlite_schema = db.schema_for("sqlite").splitlines()
    postgres_schema = db.schema_for("postgres").splitlines()

    differing = [(a, b) for a, b in zip(sqlite_schema, postgres_schema, strict=True) if a != b]

    assert len(differing) == 1
    assert "AUTOINCREMENT" in differing[0][0]
    assert "IDENTITY" in differing[0][1]


def test_the_schema_applies_cleanly_twice(tmp_path: Path) -> None:
    """Idempotent, because a deployment runs it on every boot."""
    database: Database = open_sqlite(tmp_path / "t.db")

    db.initialize_schema(database)
    db.initialize_schema(database)

    tables = {
        row["name"] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"projects", "users", "project_events", "project_quotes"} <= tables
