"""The persisted project aggregate - the system's long-term memory.

Deliberately separate from LangGraph's checkpointer. The checkpointer holds
conversation/thread state, which is an implementation detail of the graph; this
model is the durable business record a user returns to days later. Keeping them
apart is what makes "create a project, leave, come back" reliable rather than
dependent on a checkpoint format we do not own.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ProductionMethod, Stage
from app.domain.matching import MatchResult
from app.domain.method import MethodRecommendation
from app.domain.requirement import ProductionRequirement
from app.domain.rfq import RFQ


class ProjectEvent(BaseModel):
    """An audit entry. Human approvals are recorded here, not just implied.

    This is the evidence trail for human-in-the-loop: every confirmation the user
    gives is written as an event with ``actor='human'``.
    """

    model_config = ConfigDict(extra="forbid")

    event_type: str
    actor: str = Field(description="'human' or 'agent'.")
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class Project(BaseModel):
    """Full durable state of one production project."""

    model_config = ConfigDict(extra="forbid")

    id: str
    thread_id: str
    stage: Stage = Stage.DRAFT
    raw_request: str

    requirement: ProductionRequirement | None = None
    brief_confirmed: bool = False

    recommendation: MethodRecommendation | None = None
    confirmed_method: ProductionMethod | None = None

    matches: list[MatchResult] = Field(default_factory=list)
    selected_supplier_id: str | None = None

    rfq: RFQ | None = None

    created_at: datetime
    updated_at: datetime

    @property
    def is_complete(self) -> bool:
        """A project is only complete once a human approved the RFQ."""
        return self.stage is Stage.COMPLETED and self.rfq is not None and self.rfq.approved


class ProjectSummary(BaseModel):
    """Lightweight row for the dashboard list."""

    model_config = ConfigDict(extra="forbid")

    id: str
    stage: Stage
    product: str | None
    quantity: int | None
    updated_at: datetime
