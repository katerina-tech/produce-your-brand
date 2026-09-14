"""Account storage. Small on purpose.

Four operations and no more: create, find by email, find by id, count. Every
question this product asks about a person is one of those, and a repository that
offered more would invite code that needed more.

The password hash is written and read here but never compared here - comparison
belongs to :mod:`app.services.auth`, so there is exactly one place in the
codebase that knows what a correct password looks like.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from app.logging_config import Event, log_event

logger = logging.getLogger(__name__)


class User(BaseModel):
    """A person with an account. Deliberately holds nothing else.

    The address is a plain str: shape is checked once in app.services.auth, and
    pulling in an email-validation package to restate that here would add a
    dependency for a rule this product already owns.

    No name, no company, no phone. Every additional field would be personal data
    this product would then have to justify holding, and none of it is needed to
    show somebody their own projects.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    email: str
    created_at: str


class EmailAlreadyRegisteredError(Exception):
    """That address already has an account."""


class UserRepository:
    """Accounts, in the same SQLite database as the projects they own."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(self, email: str, password_hash: str) -> User:
        """Register an account, or raise if the address is taken.

        The uniqueness check is the database's, not a prior SELECT: two
        simultaneous registrations of the same address must not both succeed,
        and only the constraint can promise that.
        """
        user_id = str(uuid.uuid4())
        created_at = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO users (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                    (user_id, email, password_hash, created_at),
                )
        except sqlite3.IntegrityError as clash:
            raise EmailAlreadyRegisteredError(email) from clash

        log_event(logger, Event.PROJECT_PERSISTED, "account created", user_id=user_id)
        return User(id=user_id, email=email, created_at=created_at)

    def password_hash_for(self, email: str) -> tuple[str, str] | None:
        """Return ``(user_id, password_hash)`` for an address, or ``None``.

        Returning the hash rather than performing the check keeps the comparison
        in one place, and returning ``None`` for an unknown address lets the
        caller give the same answer for "no such account" and "wrong password".
        """
        row = self._connection.execute(
            "SELECT id, password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
        return (row["id"], row["password_hash"]) if row else None

    def get(self, user_id: str) -> User | None:
        row = self._connection.execute(
            "SELECT id, email, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None:
            return None
        return User(id=row["id"], email=row["email"], created_at=row["created_at"])

    def count(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        return int(row["n"])
