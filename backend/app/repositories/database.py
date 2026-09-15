"""One connection interface over SQLite and PostgreSQL.

The reason this exists is not that Postgres is nicer. It is that a SQLite file
on a Railway volume has already cost this project real data twice: once when
the volume was recreated and every project vanished, and once when a
``checkpoints.db`` outlived the library that wrote it and the deployment
answered 500 to every request. A managed database with backups removes both.

The shape is deliberate: this quacks like a ``sqlite3.Connection``, because
twenty-three ``execute`` calls already spoke that dialect and rewriting them
all would have been twenty-three chances to introduce a bug in code that works.

Two differences are handled here so no caller has to know about them:

* **Placeholders.** SQLite wants ``?``; psycopg wants ``%s``. The SQL is
  written once, with ``?``, and translated on the way out - skipping anything
  inside a quoted string, so a literal question mark survives.
* **Transactions.** ``with connection:`` commits on success and rolls back on
  failure in both, which psycopg3 does not do on its own - there, ``with
  conn:`` closes the connection, which would be a surprising thing to inherit.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Protocol

logger = logging.getLogger(__name__)

Dialect = Literal["sqlite", "postgres"]

# Both drivers raise a PEP 249 IntegrityError for a violated constraint, but
# they are different classes. Catching the tuple is what lets a repository say
# "that address is taken" without knowing which database it is talking to.
try:  # pragma: no cover - exercised by whichever driver is installed
    import psycopg as _psycopg

    _DRIVER_INTEGRITY: tuple[type[Exception], ...] = (_psycopg.IntegrityError,)
except ImportError:  # pragma: no cover - a SQLite-only install is still valid
    _DRIVER_INTEGRITY = ()

INTEGRITY_ERRORS: tuple[type[Exception], ...] = (sqlite3.IntegrityError, *_DRIVER_INTEGRITY)

# A container starts before the database it depends on is reachable. On Railway
# the private hostname takes a few seconds to resolve after the container comes
# up, so connecting once and giving up turns an ordinary startup race into a
# crash loop - which is exactly what it did. Roughly fifteen seconds in total,
# which is longer than that race and far shorter than a human noticing.
CONNECT_ATTEMPTS = 5
CONNECT_BACKOFF_SECONDS = 1.5


class Cursor(Protocol):
    """What the repositories use from a cursor. Deliberately small."""

    rowcount: int

    def fetchone(self) -> Any: ...
    def fetchall(self) -> Any: ...
    def __iter__(self) -> Any: ...


# A ``?`` that is not inside a single- or double-quoted string. Written as one
# pattern rather than a parser because the SQL in this codebase is a fixed,
# reviewed set of statements, not arbitrary input.
_PLACEHOLDER = re.compile(r"'[^']*'|\"[^\"]*\"|(\?)")


def to_postgres_params(sql: str) -> str:
    """Translate ``?`` placeholders to ``%s``, leaving quoted text alone."""

    def replace(match: re.Match[str]) -> str:
        return "%s" if match.group(1) else match.group(0)

    # ``%`` is psycopg's own escape, so any literal one has to be doubled or it
    # will be read as the start of a placeholder.
    return _PLACEHOLDER.sub(replace, sql.replace("%", "%%")).replace("%%s", "%s")


class Database:
    """A connection, plus the small amount of dialect knowledge the app needs."""

    def __init__(self, raw: Any, dialect: Dialect) -> None:
        self._raw = raw
        self.dialect: Dialect = dialect

    # ------------------------------------------------------------ statements

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> Cursor:
        if self.dialect == "postgres":
            return self._raw.execute(to_postgres_params(sql), params)  # type: ignore[no-any-return]
        return self._raw.execute(sql, params)  # type: ignore[no-any-return]

    def executescript(self, sql: str) -> None:
        """Run several statements. Both drivers can, by different names."""
        if self.dialect == "postgres":
            self._raw.execute(sql)
            self._raw.commit()
            return
        self._raw.executescript(sql)

    def column_names(self, table: str) -> set[str]:
        """The columns a table currently has.

        Needed by the migrations, and the one question the two dialects answer
        in genuinely different ways rather than merely different syntax.
        """
        if self.dialect == "postgres":
            rows = self.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
                (table,),
            ).fetchall()
            return {row["column_name"] for row in rows}
        return {row["name"] for row in self._raw.execute(f"PRAGMA table_info({table})")}

    # ---------------------------------------------------------- transactions

    def __enter__(self) -> Database:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        """Commit on success, roll back on failure - in both dialects.

        Spelled out rather than delegated: sqlite3 does exactly this, and
        psycopg3 closes the connection instead, which would turn one failed
        write into a dead application.
        """
        if kind is None:
            self._raw.commit()
        else:
            self._raw.rollback()
        return False

    def commit(self) -> None:
        self._raw.commit()

    def close(self) -> None:
        self._raw.close()

    @property
    def raw(self) -> Any:
        """The underlying driver connection, for the few callers that need it -
        LangGraph's checkpointer takes its own."""
        return self._raw


def open_sqlite(path: Path | str) -> Database:
    """A local file database. The default for development and for the tests."""
    if isinstance(path, Path):
        path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    # check_same_thread=False because FastAPI serves requests on a thread pool.
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return Database(connection, "sqlite")


def open_postgres(url: str) -> Database:
    """A managed database. What a deployment uses when DATABASE_URL is set."""
    import psycopg
    from psycopg.rows import dict_row

    # dict_row so ``row["column"]`` works exactly as sqlite3.Row does, which is
    # what lets the repositories stay unchanged.
    connection = psycopg.connect(url, row_factory=dict_row, autocommit=False)
    return Database(connection, "postgres")


class DatabaseUnreachableError(RuntimeError):
    """DATABASE_URL is set but cannot be used, and the reason is worth reading."""


def open_database(url: str | None, sqlite_path: Path | str) -> Database:
    """Postgres when a URL is configured, otherwise the local file.

    A configured URL that does not work raises rather than falling back. The
    fallback would be worse than the crash: the application would come up
    looking healthy and write every project to a file nobody is backing up,
    and the first anybody would know is when the volume is next recreated.

    The message says what is wrong in words, because the alternative is a
    psycopg traceback in a deploy log - and the most likely cause is a typo in
    a variable, which is thirty seconds to fix once somebody knows that is what
    it is.
    """
    if not url:
        return open_sqlite(sqlite_path)

    trimmed = url.strip()
    if trimmed.count("://") > 1:
        # Two references pasted into one variable concatenate into this.
        raise DatabaseUnreachableError(
            "DATABASE_URL looks like two connection strings joined together. "
            "A Railway variable holding ${{Postgres.DATABASE_URL}} twice produces "
            "exactly this - it should appear once."
        )

    last: Exception | None = None
    for attempt in range(1, CONNECT_ATTEMPTS + 1):
        try:
            database = open_postgres(trimmed)
        except Exception as failure:
            last = failure
            if attempt < CONNECT_ATTEMPTS:
                logger.warning(
                    "database not ready yet, retrying",
                    extra={
                        "event": "api_started",
                        "attempt": attempt,
                        "error_type": type(failure).__name__,
                    },
                )
                time.sleep(CONNECT_BACKOFF_SECONDS * attempt)
            continue
        logger.info("using postgres", extra={"event": "api_started"})
        return database

    raise DatabaseUnreachableError(
        f"DATABASE_URL is set but the database could not be reached after "
        f"{CONNECT_ATTEMPTS} attempts: {type(last).__name__}: {last}. Check that "
        f"the Postgres service is running and that the variable resolves to one "
        f"connection string."
    ) from last
