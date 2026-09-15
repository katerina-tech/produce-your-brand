"""Schema, in both dialects.

All SQL in the application lives under ``app/repositories/``, and that
containment turned out to be true: the PostgreSQL swap touched twenty-three
statements' placeholders and exactly one line of schema, and moved no call site.

Connections come from :mod:`app.repositories.database`, which hides the
differences the application does not want to know about. What remains here is
the schema itself, and the one place the two dialects genuinely disagree: an
auto-incrementing integer key.

This database holds the durable business record only. LangGraph's conversation
checkpoints live in their own store, owned by the checkpoint library; we never
write to that one.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.repositories.database import Database, Dialect, open_database, open_sqlite

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id                   TEXT PRIMARY KEY,
    thread_id            TEXT NOT NULL UNIQUE,
    stage                TEXT NOT NULL,
    raw_request          TEXT NOT NULL,
    design_upload_id     TEXT,
    owner_id             TEXT,
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

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_events (
    id           {autoincrement},
    project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    event_type   TEXT NOT NULL,
    actor        TEXT NOT NULL,
    payload_json TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_quotes (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    quote_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS partners (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    source         TEXT NOT NULL,
    verified       INTEGER NOT NULL DEFAULT 0,
    address        TEXT,
    city           TEXT NOT NULL,
    district       TEXT,
    borough        TEXT,
    category       TEXT,
    category_label TEXT,
    lat            REAL,
    lon            REAL,
    website        TEXT,
    email          TEXT,
    phone          TEXT,
    implied_method TEXT,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS partner_capabilities (
    partner_id    TEXT PRIMARY KEY REFERENCES partners(id) ON DELETE CASCADE,
    partner_name  TEXT NOT NULL,
    source_urls   TEXT NOT NULL,
    extracted_on  TEXT NOT NULL,
    dropped_count INTEGER NOT NULL DEFAULT 0,
    blocked       INTEGER NOT NULL DEFAULT 0,
    model_failed  INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS partner_claims (
    partner_id TEXT NOT NULL REFERENCES partner_capabilities(partner_id) ON DELETE CASCADE,
    position   INTEGER NOT NULL,
    text       TEXT NOT NULL,
    quote      TEXT NOT NULL,
    kind       TEXT NOT NULL,
    method     TEXT,
    PRIMARY KEY (partner_id, position)
);

CREATE INDEX IF NOT EXISTS idx_events_project ON project_events(project_id);
CREATE INDEX IF NOT EXISTS idx_quotes_project ON project_quotes(project_id);
CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_partners_name ON partners(name);
"""

# The only line the two dialects spell differently. Everything else - TEXT,
# INTEGER, REFERENCES, CREATE TABLE IF NOT EXISTS, ON CONFLICT DO UPDATE - is
# the same sentence in both.
_AUTOINCREMENT: dict[Dialect, str] = {
    "sqlite": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "postgres": "INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY",
}


def schema_for(dialect: Dialect) -> str:
    return SCHEMA.format(autoincrement=_AUTOINCREMENT[dialect])


def connect(path: Path | str, *, url: str | None = None) -> Database:
    """Open the application database.

    ``url`` wins when it is set, which is how a deployment moves to Postgres
    without a code change: Railway injects DATABASE_URL the moment a Postgres
    service exists. Without one, a local file - which is right for development
    and for a test suite that must not need a server.
    """
    if url:
        return open_database(url, path)
    return open_sqlite(path)


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
    # Nullable on purpose. Projects created before accounts existed, and every
    # project created anonymously afterwards, simply have no owner - signing in
    # is optional, so ownership has to be too.
    (
        "projects",
        "owner_id",
        "ALTER TABLE projects ADD COLUMN owner_id TEXT",
    ),
    # Where in Berlin, for a table seeded before anybody asked. Two columns
    # rather than one because they answer different questions: the Ortsteil is
    # what a person says out loud - "a printer in Kreuzberg" - and the Bezirk is
    # the dozen official divisions, which is the only one of the two that makes
    # a usable filter.
    (
        "partners",
        "district",
        "ALTER TABLE partners ADD COLUMN district TEXT",
    ),
    (
        "partners",
        "borough",
        "ALTER TABLE partners ADD COLUMN borough TEXT",
    ),
    # What kind of business this is, in the words its owners would use. The
    # derived production method could not answer this: three of the survey's
    # seven tags mean "digital printing", so filtering by method showed 134 of
    # 135 companies and told nobody anything.
    (
        "partners",
        "category",
        "ALTER TABLE partners ADD COLUMN category TEXT",
    ),
    (
        "partners",
        "category_label",
        "ALTER TABLE partners ADD COLUMN category_label TEXT",
    ),
)


def _apply_migrations(connection: Database) -> None:
    for table, column, statement in _MIGRATIONS:
        if column in connection.column_names(table):
            continue
        with connection:
            connection.execute(statement)
        logger.info(
            "applied schema migration",
            extra={"event": "schema_migrated", "table": table, "column": column},
        )


def initialize_schema(connection: Database) -> None:
    """Create tables if absent, then apply any additive migrations. Idempotent."""
    connection.executescript(schema_for(connection.dialect))
    _apply_migrations(connection)
    # Indexes over migrated columns come last: on a database created before the
    # column existed, the column is only there once migrations have run.
    with connection:
        connection.execute("CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_partners_borough ON partners(borough)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_partners_category ON partners(category)")
    logger.debug("schema ready", extra={"event": "schema_initialised"})
