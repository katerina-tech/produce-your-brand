"""Project persistence - the system's long-term memory.

A user can create a project, close the browser, and come back to its confirmed
state. That works because this record is ours and does not depend on the internal
format of LangGraph's checkpointer.

``project_events`` is the human-in-the-loop audit trail: every approval is stored
with ``actor='human'``, so "who confirmed this method, and when" is answerable
after the fact rather than inferred from the final state.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime

from pydantic import TypeAdapter

from app.domain.matching import MatchResult
from app.domain.project import Project, ProjectEvent, ProjectSummary
from app.logging_config import Event, log_event

logger = logging.getLogger(__name__)

_MATCHES = TypeAdapter(list[MatchResult])


def _now() -> datetime:
    return datetime.now(UTC)


class ProjectRepository:
    """CRUD for projects and their audit events."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    # ------------------------------------------------------------- writing

    def save(self, project: Project) -> Project:
        """Insert or update. Returns the project with a refreshed ``updated_at``.

        An upsert rather than separate create/update paths: the graph persists at
        several points and should not have to know whether the row exists.
        """
        stored = project.model_copy(update={"updated_at": _now()})
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO projects (
                    id, thread_id, stage, raw_request, requirement_json,
                    brief_confirmed, recommendation_json, confirmed_method,
                    matches_json, selected_supplier_id, rfq_json,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    stage                = excluded.stage,
                    raw_request          = excluded.raw_request,
                    requirement_json     = excluded.requirement_json,
                    brief_confirmed      = excluded.brief_confirmed,
                    recommendation_json  = excluded.recommendation_json,
                    confirmed_method     = excluded.confirmed_method,
                    matches_json         = excluded.matches_json,
                    selected_supplier_id = excluded.selected_supplier_id,
                    rfq_json             = excluded.rfq_json,
                    updated_at           = excluded.updated_at
                """,
                (
                    stored.id,
                    stored.thread_id,
                    stored.stage.value,
                    stored.raw_request,
                    stored.requirement.model_dump_json() if stored.requirement else None,
                    int(stored.brief_confirmed),
                    stored.recommendation.model_dump_json() if stored.recommendation else None,
                    stored.confirmed_method.value if stored.confirmed_method else None,
                    _MATCHES.dump_json(stored.matches).decode() if stored.matches else None,
                    stored.selected_supplier_id,
                    stored.rfq.model_dump_json() if stored.rfq else None,
                    stored.created_at.isoformat(),
                    stored.updated_at.isoformat(),
                ),
            )
        log_event(
            logger,
            Event.PROJECT_PERSISTED,
            project_id=stored.id,
            stage=stored.stage.value,
        )
        return stored

    def add_event(
        self,
        project_id: str,
        event_type: str,
        actor: str,
        payload: dict[str, object] | None = None,
    ) -> ProjectEvent:
        """Append an audit entry. Used for every human approval."""
        created_at = _now()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO project_events (project_id, event_type, actor, payload_json, created_at)
                VALUES (?,?,?,?,?)
                """,
                (
                    project_id,
                    event_type,
                    actor,
                    json.dumps(payload, default=str) if payload else None,
                    created_at.isoformat(),
                ),
            )
        return ProjectEvent(
            event_type=event_type,
            actor=actor,
            payload=payload or {},
            created_at=created_at,
        )

    # ------------------------------------------------------------- reading

    def get(self, project_id: str) -> Project | None:
        row = self._connection.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return self._to_project(row) if row else None

    def get_by_thread(self, thread_id: str) -> Project | None:
        row = self._connection.execute(
            "SELECT * FROM projects WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        return self._to_project(row) if row else None

    def list_summaries(self, limit: int = 50) -> list[ProjectSummary]:
        """Dashboard rows, newest first."""
        rows = self._connection.execute(
            """
            SELECT id, stage, requirement_json, updated_at
            FROM projects ORDER BY updated_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()

        summaries: list[ProjectSummary] = []
        for row in rows:
            requirement = json.loads(row["requirement_json"]) if row["requirement_json"] else {}
            summaries.append(
                ProjectSummary.model_validate(
                    {
                        "id": row["id"],
                        "stage": row["stage"],
                        "product": requirement.get("product"),
                        "quantity": requirement.get("quantity"),
                        "updated_at": row["updated_at"],
                    }
                )
            )
        return summaries

    def events(self, project_id: str) -> list[ProjectEvent]:
        rows = self._connection.execute(
            """
            SELECT event_type, actor, payload_json, created_at
            FROM project_events WHERE project_id = ? ORDER BY id ASC
            """,
            (project_id,),
        ).fetchall()
        return [
            ProjectEvent.model_validate(
                {
                    "event_type": row["event_type"],
                    "actor": row["actor"],
                    "payload": json.loads(row["payload_json"]) if row["payload_json"] else {},
                    "created_at": row["created_at"],
                }
            )
            for row in rows
        ]

    # ------------------------------------------------------------ mapping

    @staticmethod
    def _to_project(row: sqlite3.Row) -> Project:
        """Row to aggregate. Pydantic does the parsing, so types stay enforced."""
        return Project.model_validate(
            {
                "id": row["id"],
                "thread_id": row["thread_id"],
                "stage": row["stage"],
                "raw_request": row["raw_request"],
                "requirement": json.loads(row["requirement_json"])
                if row["requirement_json"]
                else None,
                "brief_confirmed": bool(row["brief_confirmed"]),
                "recommendation": json.loads(row["recommendation_json"])
                if row["recommendation_json"]
                else None,
                "confirmed_method": row["confirmed_method"],
                "matches": json.loads(row["matches_json"]) if row["matches_json"] else [],
                "selected_supplier_id": row["selected_supplier_id"],
                "rfq": json.loads(row["rfq_json"]) if row["rfq_json"] else None,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
