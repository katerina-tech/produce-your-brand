"""SQLite connection and schema.

All SQL in the application lives under ``app/repositories/``. That containment is
what makes the PostgreSQL swap a contained change: ``TEXT`` JSON columns become
``JSONB``, this module grows a driver branch, and no call site moves.

This database holds the durable business record only. LangGraph's conversation
checkpoints live in a separate file owned by ``langgraph-checkpoint-sqlite``; we
never write to that one.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id                   TEXT PRIMARY KEY,
    thread_id            TEXT NOT NULL UNIQUE,
    stage                TEXT NOT NULL,
    raw_request          TEXT NOT NULL,
    design_upload_id     TEXT,
    requirement_json     TEXT,
    brief_confirmed      INTEGER NOT NULL DEFAULT 0,
    recommendation_json  TEXT,
    confirmed_method     TEXT,
    matches_json         TEXT,
    selected_supplier_id TEXT,
    rfq_json             TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    event_type   TEXT NOT NULL,
    actor        TEXT NOT NULL,
    payload_json TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_project ON project_events(project_id);
CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at DESC);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a connection with the settings this application depends on.

    ``check_same_thread=False`` because FastAPI serves requests on a thread pool.
    Access is serialised by SQLite's own locking plus short-lived transactions,
    which is sufficient at MVP concurrency.
    """
    if isinstance(path, Path):
        path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


# Additive migrations for databases created before a column existed.
# ``CREATE TABLE IF NOT EXISTS`` does nothing once the table is already there,
# so a new column needs its own idempotent step - the same discipline already
# applied to LangGraph's checkpointed state, extended to this database.
# (table, column, full ALTER statement)
_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    (
        "projects",
        "design_upload_id",
        "ALTER TABLE projects ADD COLUMN design_upload_id TEXT",
    ),
)


def _apply_migrations(connection: sqlite3.Connection) -> None:
    for table, column, statement in _MIGRATIONS:
        existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column in existing:
            continue
        with connection:
            connection.execute(statement)
        logger.info(
            "applied schema migration",
            extra={"event": "schema_migrated", "table": table, "column": column},
        )


def initialize_schema(connection: sqlite3.Connection) -> None:
    """Create tables if absent, then apply any additive migrations. Idempotent."""
    with connection:
        connection.executescript(SCHEMA)
    _apply_migrations(connection)
    logger.debug("schema ready", extra={"event": "schema_initialised"})
