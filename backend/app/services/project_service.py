"""Orchestration between the API, the workflow and durable storage.

This is the only place that knows how the graph's pause/resume mechanics map onto
HTTP. Routes stay thin, and the graph stays unaware that a web frontend exists -
so a CLI or a queue worker could drive the same workflow.

Two stores are written here on purpose. The graph checkpoints its conversation
state; this service mirrors the confirmed business facts into the ``projects``
table and records each human decision in ``project_events``. The audit trail is
the evidence that a person, not the agent, made each call.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import UTC, date, datetime
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings, get_settings
from app.domain.enums import Stage
from app.domain.project import Project, ProjectSummary
from app.graph.state import ProductionState, initial_state
from app.logging_config import Event, log_event, redact_text
from app.repositories.project_repo import ProjectRepository
from app.security.uploads import get_upload

logger = logging.getLogger(__name__)


class DesignNotFoundError(ValueError):
    """A ``design_upload_id`` was given that does not point at a stored upload.

    Raised before the project or the graph is touched: neither the durable
    record nor checkpointed state must ever hold a reference to a file that does
    not exist, which is what would happen if a stale or fabricated id were
    trusted instead of verified.
    """

    def __init__(self, upload_id: str) -> None:
        super().__init__(f"No uploaded or generated design found for id '{upload_id}'.")
        self.upload_id = upload_id


# Which resume action each paused stage will accept. A mismatch is reported to
# the client rather than silently resuming into the wrong branch.
EXPECTED_ACTION: dict[Stage, str] = {
    Stage.CLARIFYING: "answer_clarification",
    Stage.BRIEF_REVIEW: "confirm_brief",
    Stage.METHOD_REVIEW: "confirm_method",
    Stage.SUPPLIER_SELECTION: "select_supplier",
    Stage.RFQ_REVIEW: "approve_rfq",
}

# Actions that are alternative ways of answering the same gate.
ACTION_ALIASES: dict[str, str] = {
    "edit_brief": "confirm_brief",
    "edit_rfq": "approve_rfq",
    "restart_request": "answer_clarification",
}


class StageMismatchError(RuntimeError):
    """The submitted action does not match the gate the workflow is waiting at."""

    def __init__(self, expected: str | None, received: str) -> None:
        super().__init__(f"expected '{expected}', received '{received}'")
        self.expected = expected
        self.received = received


class ProjectView(BaseModel):
    """What the frontend needs to render the current step.

    ``payload`` is whatever the paused node published. The frontend switches on
    ``stage`` and renders it - which is why no workflow logic lives client-side.
    """

    model_config = ConfigDict(extra="forbid")

    project_id: str
    stage: Stage
    product: str | None = Field(
        default=None,
        description="Product name from the durable record. Present at every "
        "stage so a client can title the project consistently - the interrupt "
        "payloads alone do not all carry it.",
    )
    design_upload_id: str | None = Field(
        default=None, description="Id of an attached design, if one was uploaded or generated."
    )
    payload: dict[str, Any] | None = None
    expected_action: str | None = None
    errors: list[str] = []
    is_complete: bool = False


class ProjectService:
    """Create and advance projects."""

    def __init__(
        self,
        workflow: CompiledStateGraph[ProductionState, None, Any, Any],
        projects: ProjectRepository,
        today: date | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._workflow = workflow
        self._projects = projects
        self._today = today or date.today()
        self._settings = settings or get_settings()

    # ------------------------------------------------------------- creating

    def create(self, raw_request: str, design_upload_id: str | None = None) -> ProjectView:
        """Start a project and run to the first human gate.

        A supplied ``design_upload_id`` is verified before anything else is
        touched. Neither the durable record nor the graph's checkpointed state
        may hold a reference to a file that does not exist.
        """
        if design_upload_id is not None and get_upload(design_upload_id, self._settings) is None:
            raise DesignNotFoundError(design_upload_id)

        project_id = str(uuid.uuid4())
        thread_id = f"thread-{project_id}"
        now = datetime.now(UTC)

        self._projects.save(
            Project(
                id=project_id,
                thread_id=thread_id,
                raw_request=raw_request,
                design_upload_id=design_upload_id,
                created_at=now,
                updated_at=now,
            )
        )
        log_event(
            logger,
            Event.PROJECT_CREATED,
            project_id=project_id,
            design_upload_id=design_upload_id,
            **redact_text(raw_request),
        )

        result = self._workflow.invoke(
            initial_state(
                project_id,
                raw_request,
                self._today.isoformat(),
                design_upload_id=design_upload_id,
            ),
            self._config(thread_id),
        )
        return self._sync(project_id, result)

    # ------------------------------------------------------------ resuming

    def resume(self, project_id: str, action: str, data: dict[str, Any]) -> ProjectView:
        """Answer the current gate and run to the next one.

        Rejects an action that does not match where the workflow is parked, so a
        stale browser tab cannot resume into the wrong branch.
        """
        project = self._projects.get(project_id)
        if project is None:
            raise KeyError(project_id)

        current = self._current_view(project)
        expected = current.expected_action
        normalised = ACTION_ALIASES.get(action, action)
        if expected is None or normalised != expected:
            raise StageMismatchError(expected, action)

        log_event(
            logger,
            Event.PROJECT_RESUMED,
            project_id=project_id,
            action=action,
            stage=current.stage.value,
        )
        self._projects.add_event(project_id, action, "human", data)

        result = self._workflow.invoke(
            Command(resume=self._resume_payload(action, data)),
            self._config(project.thread_id),
        )
        return self._sync(project_id, result)

    @staticmethod
    def _resume_payload(action: str, data: dict[str, Any]) -> Any:
        """Translate an API action into what the paused node expects."""
        if action == "answer_clarification":
            return str(data.get("answer", ""))
        if action == "restart_request":
            return {
                "restart_with_new_request": True,
                "raw_request": str(data.get("raw_request", "")),
            }
        if action == "confirm_brief":
            return {"confirmed": True}
        if action == "edit_brief":
            return {"requirement": data.get("requirement")}
        if action == "confirm_method":
            return {"method": data.get("method")}
        if action == "select_supplier":
            return {"supplier_id": data.get("supplier_id")}
        if action == "approve_rfq":
            return {"approved": bool(data.get("approved", True))}
        if action == "edit_rfq":
            return {"rfq": data.get("rfq"), "approved": bool(data.get("approved", False))}
        return data

    # ------------------------------------------------------------- reading

    def get(self, project_id: str) -> ProjectView | None:
        project = self._projects.get(project_id)
        if project is None:
            return None
        return self._current_view(project)

    def get_record(self, project_id: str) -> Project | None:
        """The durable record itself, for integrations that need fields (like
        ``requirement.location`` or ``confirmed_method``) that :class:`ProjectView`
        deliberately does not carry - it exists for the workflow, not as a
        general-purpose read model."""
        return self._projects.get(project_id)

    def list_summaries(self, limit: int = 50) -> list[ProjectSummary]:
        return self._projects.list_summaries(limit)

    def _current_view(self, project: Project) -> ProjectView:
        """Rebuild the view from the checkpoint, without advancing anything."""
        snapshot = self._workflow.get_state(self._config(project.thread_id))
        values: dict[str, Any] = snapshot.values or {}

        payload: dict[str, Any] | None = None
        for task in snapshot.tasks:
            for pending in task.interrupts:
                payload = pending.value
                break

        stage = self._stage_of(values, payload)
        return ProjectView(
            project_id=project.id,
            stage=stage,
            product=project.requirement.product if project.requirement else None,
            design_upload_id=project.design_upload_id,
            payload=payload,
            expected_action=EXPECTED_ACTION.get(stage) if payload else None,
            errors=list(values.get("errors") or []),
            is_complete=stage is Stage.COMPLETED,
        )

    # -------------------------------------------------------------- syncing

    def _sync(self, project_id: str, result: dict[str, Any]) -> ProjectView:
        """Mirror confirmed workflow facts into the durable record, then read back.

        The view is built by :meth:`_current_view` rather than assembled here.
        Two constructors for the same object is how a field ends up present on
        one response and missing from another - which is exactly what happened
        before this collapsed into one path.
        """
        payload = self._interrupt_payload(result)
        stage = self._stage_of(result, payload)

        project = self._projects.get(project_id)
        if project is None:
            raise KeyError(project_id)

        saved = self._projects.save(
            project.model_copy(
                update={
                    "stage": stage,
                    # Only ever differs from what's already stored after a
                    # restart_request rewrote the description mid-clarification;
                    # otherwise this is a no-op copy of the same value.
                    "raw_request": result.get("raw_request", project.raw_request),
                    "requirement": result.get("production_requirement"),
                    "brief_confirmed": stage
                    not in (Stage.DRAFT, Stage.CLARIFYING, Stage.BRIEF_REVIEW),
                    "recommendation": result.get("recommended_methods"),
                    "confirmed_method": result.get("confirmed_method"),
                    "matches": list(result.get("supplier_matches") or []),
                    "selected_supplier_id": result.get("selected_supplier"),
                    "rfq": result.get("rfq"),
                }
            )
        )
        if stage is Stage.COMPLETED:
            log_event(logger, Event.PROJECT_PERSISTED, "project completed", project_id=project_id)

        return self._current_view(saved)

    @staticmethod
    def _interrupt_payload(result: dict[str, Any]) -> dict[str, Any] | None:
        pending = result.get("__interrupt__")
        if not pending:
            return None
        value = pending[0].value
        return value if isinstance(value, dict) else {"value": value}

    @staticmethod
    def _stage_of(values: dict[str, Any], payload: dict[str, Any] | None) -> Stage:
        """Prefer the paused node's own stage; it is the most specific signal."""
        if payload and isinstance(payload.get("stage"), str):
            try:
                return Stage(payload["stage"])
            except ValueError:
                pass
        stage = values.get("current_stage")
        return stage if isinstance(stage, Stage) else Stage.DRAFT

    @staticmethod
    def _config(thread_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": thread_id}}


def build_service(
    workflow: CompiledStateGraph[ProductionState, None, Any, Any],
    connection: sqlite3.Connection,
    today: date | None = None,
) -> ProjectService:
    """Assemble the service from an open connection and a compiled workflow."""
    return ProjectService(workflow, ProjectRepository(connection), today)
