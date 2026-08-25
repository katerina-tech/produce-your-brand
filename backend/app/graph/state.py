"""The LangGraph working state - short-term memory for one project thread.

Distinct from :class:`app.domain.project.Project`, which is the durable business
record. This holds only what the workflow needs while it runs, and is checkpointed
by ``langgraph-checkpoint-sqlite``.

Nothing derivable is stored twice. Suppliers appear as ids rather than full
records (the repository is the source of truth), and the completeness report is
reduced to ``missing_fields`` because the rest can be recomputed from the
requirement at any time.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    Confidence,
    Priority,
    ProductCategory,
    ProductionMethod,
    Stage,
)
from app.domain.knowledge import KnowledgeCitation, KnowledgeSnippet, RetrievalDecision
from app.domain.matching import FactorScore, MatchFactor, MatchResult, Verdict
from app.domain.method import MethodRecommendation
from app.domain.requirement import ProductionRequirement
from app.domain.rfq import RFQ


class ProductionState(TypedDict, total=False):
    """State passed between nodes. ``total=False`` so nodes return partial deltas."""

    # Conversation trace: the clarification exchange, kept so the UI and the
    # audit trail can show what was actually asked and answered.
    messages: Annotated[list[AnyMessage], add_messages]

    project_id: str
    raw_request: str
    reference_date: str
    # Id of an uploaded or generated design, verified to exist before the graph
    # ever starts. Its only effect is forcing design_available=True in
    # extract_requirement - the correction has to happen inside the graph,
    # against checkpointed state, or a later resume would still see whatever
    # the LLM guessed from text alone.
    design_upload_id: str | None

    production_requirement: ProductionRequirement | None
    missing_fields: list[str]
    clarification_rounds: int
    clarifying_question: str | None
    # Transient: true for exactly one tick, set by ask_clarifying_question when
    # the customer chose to rewrite their original description instead of
    # answering. The conditional edge right after that node reads it once to
    # route back to extract_requirement instead of the normal merge step, then
    # every path that would otherwise leave it stale explicitly resets it to
    # False - see the comment at its two call sites in graph/nodes.py.
    restarted_with_new_request: bool

    retrieval_decision: RetrievalDecision | None
    retrieved_knowledge: list[KnowledgeSnippet]

    recommended_methods: MethodRecommendation | None
    confirmed_method: ProductionMethod | None

    # Ids that structurally could do the job, before scoring. Kept because the
    # UI reports the funnel ("7 of 24 partners offer this method"), which is what
    # makes an empty or surprising result explainable.
    supplier_candidates: list[str]
    supplier_matches: list[MatchResult]
    selected_supplier: str | None

    rfq: RFQ | None

    current_stage: Stage
    errors: list[str]


# ------------------------------------------------- small LLM output schemas
# These exist because every model call in this system returns a validated
# Pydantic object. There is no free-text path out of the provider.


class ClarifyingQuestion(BaseModel):
    """One question about one field."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(description="The single question to ask the customer.")


class MatchExplanation(BaseModel):
    """Prose about an already-computed score."""

    model_config = ConfigDict(extra="forbid")

    explanation: str = Field(description="Two or three sentences for the buyer.")


class RFQProse(BaseModel):
    """Tone-only contribution to the RFQ document."""

    model_config = ConfigDict(extra="forbid")

    intro: str
    closing: str


# Domain types that legitimately appear in checkpointed state.
#
# LangGraph will refuse to deserialize unregistered types in a future release, so
# declaring these keeps the workflow working across upgrades instead of failing
# on a warning we ignored. It is also a hardening measure: an explicit allowlist
# means a checkpoint database cannot be used to instantiate arbitrary classes.
# Nested types need listing too: each enum and sub-model is encoded separately,
# so omitting one silently degrades that field on reload.
CHECKPOINTED_TYPES: tuple[type, ...] = (
    # models
    ProductionRequirement,
    MethodRecommendation,
    MatchResult,
    FactorScore,
    KnowledgeCitation,
    KnowledgeSnippet,
    RetrievalDecision,
    RFQ,
    # enums
    ProductionMethod,
    ProductCategory,
    Priority,
    Confidence,
    Stage,
    MatchFactor,
    Verdict,
)


def initial_state(
    project_id: str,
    raw_request: str,
    reference_date: str,
    design_upload_id: str | None = None,
) -> ProductionState:
    """Starting state for a new project."""
    return ProductionState(
        messages=[],
        project_id=project_id,
        raw_request=raw_request,
        reference_date=reference_date,
        design_upload_id=design_upload_id,
        production_requirement=None,
        missing_fields=[],
        clarification_rounds=0,
        clarifying_question=None,
        restarted_with_new_request=False,
        retrieval_decision=None,
        retrieved_knowledge=[],
        recommended_methods=None,
        confirmed_method=None,
        supplier_candidates=[],
        supplier_matches=[],
        selected_supplier=None,
        rfq=None,
        current_stage=Stage.DRAFT,
        errors=[],
    )
