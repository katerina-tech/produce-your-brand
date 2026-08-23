"""Graph nodes.

Every node is thin by design: read state, call one service or one model, return a
partial state delta. Business rules live in ``app.services``; prompt text lives in
``app.llm.prompts``. A node that starts making decisions of its own is a bug.

Error policy: a model or tool failure never propagates as an exception. It is
logged, recorded in ``errors``, and the stage becomes FAILED so the graph can
route to a controlled stop. The user gets a typed error, not a stack trace.

Human review is implemented with ``interrupt()``. The five interrupts are the
product's core guarantee: the agent recommends, a person decides.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from app.domain.enums import ProductionMethod, Stage
from app.domain.knowledge import KnowledgeCitation, KnowledgeSnippet, RetrievalDecision
from app.domain.method import MethodRecommendation
from app.domain.requirement import ProductionRequirement
from app.graph.state import (
    ClarifyingQuestion,
    MatchExplanation,
    ProductionState,
    RFQProse,
)
from app.llm import prompts
from app.llm.factory import LLMError
from app.logging_config import Event, log_event, redact_text
from app.rag.retriever import format_snippets
from app.services import completeness, rfq_builder
from app.tools.registry import ToolError

if TYPE_CHECKING:
    from app.graph.workflow import GraphDeps

logger = logging.getLogger(__name__)


def _fail(stage: Stage, message: str) -> dict[str, Any]:
    """Controlled failure delta. Never raises past the node boundary."""
    return {"current_stage": Stage.FAILED, "errors": [f"{stage.value}: {message}"]}


def _reference_date(state: ProductionState) -> str:
    return state.get("reference_date") or date.today().isoformat()


# ------------------------------------------------------------------ extraction


def extract_requirement(state: ProductionState, deps: GraphDeps) -> dict[str, Any]:
    """Natural language to a typed brief. Unknown fields stay null."""
    raw_request = state["raw_request"]
    log_event(
        logger,
        Event.REQUIREMENT_EXTRACTION_STARTED,
        project_id=state.get("project_id"),
        **redact_text(raw_request),
    )

    screened = deps.screen_untrusted(raw_request, "customer_request")

    try:
        requirement = deps.provider.structured(
            ProductionRequirement,
            prompts.extraction_messages(screened, _reference_date(state)),
        )
    except LLMError as error:
        return _fail(Stage.DRAFT, str(error))

    log_event(
        logger,
        Event.REQUIREMENT_EXTRACTION_COMPLETED,
        project_id=state.get("project_id"),
        known_fields=sorted(requirement.known_fields()),
    )
    return {"production_requirement": requirement, "current_stage": Stage.DRAFT}


def validate_requirement(state: ProductionState, deps: GraphDeps) -> dict[str, Any]:
    """Deterministic completeness check. No model involved."""
    requirement = state.get("production_requirement")
    if requirement is None:
        return _fail(Stage.DRAFT, "no requirement to validate")

    report = completeness.check(requirement)
    return {
        "missing_fields": list(report.missing_critical),
        "current_stage": Stage.CLARIFYING if report.next_field else Stage.BRIEF_REVIEW,
    }


# --------------------------------------------------------------- clarification


def ask_clarifying_question(state: ProductionState, deps: GraphDeps) -> dict[str, Any]:
    """Ask about exactly one field, then pause for the answer.

    The field is chosen deterministically; the model only phrases the question.
    """
    requirement = state.get("production_requirement")
    missing = state.get("missing_fields") or []
    if requirement is None or not missing:
        return _fail(Stage.CLARIFYING, "nothing to clarify")

    field = missing[0]
    try:
        asked = deps.provider.structured(
            ClarifyingQuestion,
            prompts.clarification_messages(requirement, field, _reference_date(state)),
            purpose="classifier",
        )
        question = asked.question
    except LLMError:
        # A phrasing failure must not stall the workflow: fall back to the
        # deterministic label, which is always answerable.
        question = f"Could you tell us the {completeness.FIELD_LABELS.get(field, field)}?"

    rounds = state.get("clarification_rounds", 0) + 1
    log_event(
        logger,
        Event.CLARIFICATION_REQUESTED,
        project_id=state.get("project_id"),
        field=field,
        round=rounds,
    )

    answer = interrupt(
        {
            "stage": Stage.CLARIFYING.value,
            "question": question,
            "field": field,
            "reason": completeness.BLOCKING_REASONS.get(field),
            "requirement": requirement.model_dump(mode="json"),
        }
    )

    return {
        "clarifying_question": question,
        "clarification_rounds": rounds,
        "messages": [AIMessage(content=question), HumanMessage(content=str(answer))],
    }


def update_requirement(state: ProductionState, deps: GraphDeps) -> dict[str, Any]:
    """Merge the answer in. Fill-only: an answer may add, never overwrite."""
    requirement = state.get("production_requirement")
    question = state.get("clarifying_question") or ""
    messages = state.get("messages") or []
    answer = str(messages[-1].content) if messages else ""

    if requirement is None:
        return _fail(Stage.CLARIFYING, "no requirement to update")

    screened = deps.screen_untrusted(answer, "customer_answer")

    try:
        proposed = deps.provider.structured(
            ProductionRequirement,
            prompts.update_messages(requirement, question, screened, _reference_date(state)),
        )
    except LLMError as error:
        return _fail(Stage.CLARIFYING, str(error))

    # The merge is enforced here, not trusted to the prompt: even if the model
    # rewrites a field the customer already gave us, the original wins.
    merged = requirement.merge(proposed)

    log_event(
        logger,
        Event.CLARIFICATION_ANSWERED,
        project_id=state.get("project_id"),
        gained_fields=sorted(merged.known_fields() - requirement.known_fields()),
    )
    return {"production_requirement": merged, "clarifying_question": None}


# -------------------------------------------------------------- human review


def human_review_requirement(state: ProductionState, deps: GraphDeps) -> dict[str, Any]:
    """Show the brief and wait. The customer may confirm or submit edits."""
    requirement = state.get("production_requirement")
    if requirement is None:
        return _fail(Stage.BRIEF_REVIEW, "no requirement to review")

    report = completeness.check(requirement)
    decision = interrupt(
        {
            "stage": Stage.BRIEF_REVIEW.value,
            "requirement": requirement.model_dump(mode="json"),
            "field_labels": completeness.FIELD_LABELS,
            "still_unknown": list(report.missing_critical + report.missing_optional),
        }
    )

    edited = _requirement_from_decision(decision)
    confirmed = edited or requirement

    log_event(
        logger,
        Event.BRIEF_CONFIRMED,
        project_id=state.get("project_id"),
        was_edited=edited is not None,
    )
    return {
        "production_requirement": confirmed,
        "current_stage": Stage.METHOD_REVIEW,
        "requires_human_review": False,
    }


def _requirement_from_decision(decision: object) -> ProductionRequirement | None:
    """Parse an edited requirement out of a resume payload, if one was sent.

    Validation happens here so a malformed edit cannot enter state; on failure we
    keep the previous requirement rather than accepting partial data.
    """
    if not isinstance(decision, dict):
        return None
    payload = decision.get("requirement")
    if not payload:
        return None
    try:
        return ProductionRequirement.model_validate(payload)
    except ValueError:
        logger.warning(
            "discarded an invalid requirement edit",
            extra={"event": Event.VALIDATION_ERROR.value},
        )
        return None


# ------------------------------------------------------------- agentic rag


def assess_knowledge_need(state: ProductionState, deps: GraphDeps) -> dict[str, Any]:
    """Decide whether this project needs the production knowledge base.

    This is the node that makes the RAG agentic. It does not retrieve; it only
    decides. When no retriever is configured the answer is trivially "no", which
    keeps the graph runnable without an index.
    """
    requirement = state.get("production_requirement")
    if requirement is None:
        return _fail(Stage.METHOD_REVIEW, "no requirement to assess")

    if deps.retriever is None:
        return {
            "retrieval_decision": RetrievalDecision(
                needs_retrieval=False,
                reason="No knowledge base configured.",
            )
        }

    decision = deps.retriever.assess_requirement(requirement)
    return {"retrieval_decision": decision}


def retrieve_production_knowledge(state: ProductionState, deps: GraphDeps) -> dict[str, Any]:
    """Fetch supporting passages. Failure degrades to no knowledge, not an error.

    A retrieval outage should cost confidence in the recommendation, not the
    whole project, so this never fails the workflow.
    """
    decision = state.get("retrieval_decision")
    requirement = state.get("production_requirement")
    if deps.retriever is None or decision is None or not decision.query or requirement is None:
        return {"retrieved_knowledge": []}

    try:
        snippets = deps.retriever.search_production_knowledge(decision.query)
    except Exception as error:  # index missing, embedding outage, corrupt file
        log_event(
            logger,
            Event.TOOL_ERROR,
            "retrieval failed; continuing without knowledge",
            level=logging.WARNING,
            error_type=type(error).__name__,
        )
        return {"retrieved_knowledge": []}

    # Retrieved documents are untrusted input, exactly like customer text.
    screened = [
        snippet.model_copy(
            update={"text": deps.screen_untrusted(snippet.text, "knowledge_excerpt")}
        )
        for snippet in snippets
    ]
    log_event(
        logger,
        Event.RAG_COMPLETED,
        project_id=state.get("project_id"),
        snippets=len(screened),
        titles=[snippet.citation.title for snippet in screened],
    )
    return {"retrieved_knowledge": screened}


# ------------------------------------------------------ method recommendation


def recommend_production_method(state: ProductionState, deps: GraphDeps) -> dict[str, Any]:
    """Recommend a technique, with explicit uncertainty."""
    requirement = state.get("production_requirement")
    if requirement is None:
        return _fail(Stage.METHOD_REVIEW, "no requirement to reason about")

    snippets = state.get("retrieved_knowledge") or []
    knowledge = format_snippets(snippets) if snippets else None

    try:
        recommendation = deps.provider.structured(
            MethodRecommendation,
            prompts.method_messages(
                requirement,
                [method.value for method in ProductionMethod],
                _reference_date(state),
                knowledge=knowledge,
            ),
        )
    except LLMError as error:
        return _fail(Stage.METHOD_REVIEW, str(error))

    # Citations and the retrieval flag are set here, not by the model: what was
    # actually retrieved is a fact about this run, not something to be claimed.
    recommendation = recommendation.model_copy(
        update={
            "retrieval_used": bool(snippets),
            "sources": _dedupe_citations(snippets),
        }
    )

    log_event(
        logger,
        Event.METHOD_RECOMMENDED,
        project_id=state.get("project_id"),
        primary=recommendation.primary.value,
        alternative=recommendation.alternative.value if recommendation.alternative else None,
        confidence=recommendation.confidence.value,
        open_questions=len(recommendation.open_questions),
        retrieval_used=recommendation.retrieval_used,
        sources=len(recommendation.sources),
    )
    return {"recommended_methods": recommendation, "current_stage": Stage.METHOD_REVIEW}


def _dedupe_citations(snippets: list[KnowledgeSnippet]) -> list[KnowledgeCitation]:
    """One citation per source document, in retrieval order."""
    seen: set[str] = set()
    citations: list[KnowledgeCitation] = []
    for snippet in snippets:
        if snippet.citation.title in seen:
            continue
        seen.add(snippet.citation.title)
        citations.append(snippet.citation)
    return citations


def human_review_method(state: ProductionState, deps: GraphDeps) -> dict[str, Any]:
    """A person confirms the technique before any supplier work happens."""
    recommendation = state.get("recommended_methods")
    if recommendation is None:
        return _fail(Stage.METHOD_REVIEW, "no recommendation to review")

    decision = interrupt(
        {
            "stage": Stage.METHOD_REVIEW.value,
            "recommendation": recommendation.model_dump(mode="json"),
            "selectable_methods": [method.value for method in ProductionMethod],
        }
    )

    chosen = recommendation.primary
    if isinstance(decision, dict) and decision.get("method"):
        try:
            chosen = ProductionMethod(decision["method"])
        except ValueError:
            logger.warning(
                "ignored an unknown method selection",
                extra={"event": Event.VALIDATION_ERROR.value},
            )

    log_event(
        logger,
        Event.METHOD_CONFIRMED,
        project_id=state.get("project_id"),
        method=chosen.value,
        overrode_recommendation=chosen is not recommendation.primary,
    )
    return {"confirmed_method": chosen, "current_stage": Stage.SUPPLIER_SELECTION}


# ------------------------------------------------------------ supplier matching


def search_suppliers(state: ProductionState, deps: GraphDeps) -> dict[str, Any]:
    """Structural candidate search. Deterministic, no model."""
    requirement = state.get("production_requirement")
    method = state.get("confirmed_method")
    if requirement is None or method is None:
        return _fail(Stage.SUPPLIER_SELECTION, "no confirmed method to search on")

    try:
        found = deps.tools.search_suppliers(method, requirement.product_category)
    except ToolError as error:
        return _fail(Stage.SUPPLIER_SELECTION, str(error))

    return {"supplier_candidates": found.supplier_ids}


def calculate_matches(state: ProductionState, deps: GraphDeps) -> dict[str, Any]:
    """Score deterministically, then ask the model only to phrase the result.

    The scores exist before the model is called, and are unchanged after. If the
    explanation call fails, matches still render with their Python-generated
    per-factor reasons - degraded prose, not a broken feature.
    """
    requirement = state.get("production_requirement")
    method = state.get("confirmed_method")
    if requirement is None or method is None:
        return _fail(Stage.SUPPLIER_SELECTION, "cannot score without a confirmed method")

    try:
        calculation = deps.tools.calculate_supplier_matches(
            requirement,
            method,
            deps.today,
            top_n=deps.top_matches,
            buffer_days=deps.deadline_buffer_days,
        )
    except ToolError as error:
        return _fail(Stage.SUPPLIER_SELECTION, str(error))

    for match in calculation.matches:
        supplier = deps.tools.resolve_supplier(match.supplier_id)
        if supplier is None:
            continue
        try:
            prose = deps.provider.structured(
                MatchExplanation,
                prompts.match_explanation_messages(match, supplier, requirement),
                purpose="classifier",
            )
            match.ai_explanation = prose.explanation
        except LLMError:
            logger.warning(
                "match explanation unavailable; using computed factors only",
                extra={"event": Event.LLM_ERROR.value, "supplier_id": match.supplier_id},
            )

    return {
        "supplier_matches": calculation.matches,
        "current_stage": Stage.SUPPLIER_SELECTION,
    }


def human_select_supplier(state: ProductionState, deps: GraphDeps) -> dict[str, Any]:
    """A person picks the partner. An unknown id is refused, not guessed at."""
    matches = state.get("supplier_matches") or []
    if not matches:
        return _fail(Stage.SUPPLIER_SELECTION, "no eligible partners to choose from")

    decision = interrupt(
        {
            "stage": Stage.SUPPLIER_SELECTION.value,
            "matches": [match.model_dump(mode="json") for match in matches],
        }
    )

    chosen_id: str | None = None
    if isinstance(decision, dict):
        candidate = decision.get("supplier_id")
        # Only an id that is both offered and real is accepted.
        if candidate in {match.supplier_id for match in matches} and deps.tools.resolve_supplier(
            str(candidate)
        ):
            chosen_id = str(candidate)

    if chosen_id is None:
        return _fail(Stage.SUPPLIER_SELECTION, "no valid partner was selected")

    log_event(
        logger,
        Event.SUPPLIER_SELECTED,
        project_id=state.get("project_id"),
        supplier_id=chosen_id,
    )
    return {"selected_supplier": chosen_id, "current_stage": Stage.RFQ_REVIEW}


# ------------------------------------------------------------------------ rfq


def generate_rfq(state: ProductionState, deps: GraphDeps) -> dict[str, Any]:
    """Assemble the RFQ in Python; the model contributes tone only."""
    requirement = state.get("production_requirement")
    recommendation = state.get("recommended_methods")
    method = state.get("confirmed_method")
    supplier_id = state.get("selected_supplier")

    if requirement is None or method is None or supplier_id is None:
        return _fail(Stage.RFQ_REVIEW, "missing inputs for RFQ generation")

    supplier = deps.tools.resolve_supplier(supplier_id)
    if supplier is None:
        return _fail(Stage.RFQ_REVIEW, "selected partner is not in the dataset")

    intro: str | None = None
    closing: str | None = None
    if recommendation is not None:
        try:
            prose = deps.provider.structured(
                RFQProse,
                prompts.rfq_prose_messages(requirement, recommendation, supplier),
                purpose="classifier",
            )
            intro, closing = prose.intro, prose.closing
        except LLMError:
            logger.warning(
                "RFQ prose unavailable; using deterministic wording",
                extra={"event": Event.LLM_ERROR.value},
            )

    rfq = rfq_builder.build_rfq(requirement, method, supplier, intro=intro, closing=closing)
    return {"rfq": rfq, "current_stage": Stage.RFQ_REVIEW}


def human_review_rfq(state: ProductionState, deps: GraphDeps) -> dict[str, Any]:
    """The final gate. Nothing completes without an explicit approval."""
    rfq = state.get("rfq")
    if rfq is None:
        return _fail(Stage.RFQ_REVIEW, "no RFQ to review")

    decision = interrupt(
        {
            "stage": Stage.RFQ_REVIEW.value,
            "rfq": rfq.model_dump(mode="json"),
            "rendered": rfq_builder.render_markdown(rfq),
        }
    )

    edited = rfq
    if isinstance(decision, dict) and isinstance(decision.get("rfq"), dict):
        try:
            # Approval is never taken from the payload - it is set below, only on
            # an explicit approve action.
            edited = type(rfq).model_validate({**decision["rfq"], "approved": False})
        except ValueError:
            logger.warning(
                "discarded an invalid RFQ edit",
                extra={"event": Event.VALIDATION_ERROR.value},
            )

    approved = isinstance(decision, dict) and decision.get("approved") is True
    if not approved:
        return _fail(Stage.RFQ_REVIEW, "RFQ was not approved")

    log_event(
        logger,
        Event.RFQ_APPROVED,
        project_id=state.get("project_id"),
        supplier_id=edited.supplier_id,
    )
    return {
        "rfq": edited.model_copy(update={"approved": True}),
        "current_stage": Stage.COMPLETED,
    }
