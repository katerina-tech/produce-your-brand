"""THE LangGraph workflow. There is exactly one, and this is it.

``scripts/audit_architecture.py`` fails the build if a second ``StateGraph``
appears anywhere. The predecessor project's competing agent implementations are
the reason that check exists.

Dependencies are injected via :class:`GraphDeps` rather than imported inside
nodes. That is what lets the entire workflow - including all five human
interrupts - run in tests against a fake provider, with no API key and no
network, while production wiring stays in one place.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from functools import partial
from pathlib import Path
from typing import Any, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.config import Settings, get_settings
from app.domain.enums import Stage
from app.graph import nodes
from app.graph.state import CHECKPOINTED_TYPES, ProductionState
from app.llm.factory import LLMProvider, get_embedding_provider, get_provider
from app.rag.retriever import KnowledgeRetriever
from app.rag.store import KnowledgeStore
from app.repositories.supplier_repo import SupplierRepository
from app.tools.registry import ProductionTools

logger = logging.getLogger(__name__)


class BoundNode(Protocol):
    """A node with its dependencies already bound.

    LangGraph's node protocol names its first parameter ``state``, so a bare
    ``Callable[[ProductionState], ...]`` does not satisfy it. Declaring the
    protocol explicitly keeps ``add_node`` type-checked instead of silenced.
    """

    def __call__(self, state: ProductionState) -> dict[str, Any]: ...


def _passthrough_screen(text: str, _label: str) -> str:
    """Default screening: identity.

    Phase 4 replaces this with the layered injection guard. It is a seam rather
    than a stub - nodes already route all untrusted text through it, so enabling
    the guard is a wiring change, not a refactor of every node.
    """
    return text


@dataclass(frozen=True)
class GraphDeps:
    """Everything the nodes need, supplied from outside.

    ``today`` is here rather than read from a clock inside scoring, which is what
    keeps match results reproducible.
    """

    provider: LLMProvider
    tools: ProductionTools
    today: date
    retriever: KnowledgeRetriever | None = None
    top_matches: int = 3
    deadline_buffer_days: int = 5
    max_clarification_rounds: int = 3
    screen_untrusted: Callable[[str, str], str] = field(default=_passthrough_screen)


# ------------------------------------------------------------------- routing


def _has_failed(state: ProductionState) -> bool:
    return state.get("current_stage") is Stage.FAILED or bool(state.get("errors"))


def route_after_extraction(state: ProductionState) -> str:
    """Stop cleanly on failure rather than validating a requirement we lack."""
    return "failed" if _has_failed(state) else "validate_requirement"


def route_after_validation(state: ProductionState, max_rounds: int) -> str:
    """Ask about a missing critical field, or move to human review.

    The round cap matters: a model that keeps failing to resolve a field must not
    trap the user in a question loop. On exhaustion we proceed to review with the
    gap visible, which is the honest outcome.
    """
    if _has_failed(state):
        return "failed"
    if not state.get("missing_fields"):
        return "human_review_requirement"
    if state.get("clarification_rounds", 0) >= max_rounds:
        logger.info(
            "clarification budget exhausted; proceeding with gaps",
            extra={
                "event": "clarification_budget_exhausted",
                "missing_fields": state.get("missing_fields"),
            },
        )
        return "human_review_requirement"
    return "ask_clarifying_question"


def route_after_knowledge_assessment(state: ProductionState) -> str:
    """The conditional edge that makes retrieval optional.

    A feasibility question earns a lookup; a routine pairing does not. This is
    the branch that has to actually vary, or the RAG is decorative.
    """
    if _has_failed(state):
        return "failed"
    decision = state.get("retrieval_decision")
    if decision is not None and decision.needs_retrieval:
        return "retrieve_production_knowledge"
    return "recommend_production_method"


def route_after_method_recommendation(state: ProductionState) -> str:
    return "failed" if _has_failed(state) else "human_review_method"


def route_after_rfq_review(state: ProductionState) -> str:
    """An unapproved RFQ ends the run without persisting completion."""
    return "failed" if _has_failed(state) else "persist"


# -------------------------------------------------------------------- building


def build_graph(deps: GraphDeps) -> StateGraph[ProductionState, None, Any, Any]:
    """Assemble the workflow. One graph, thin nodes, five human interrupts."""
    graph: StateGraph[ProductionState, None, Any, Any] = StateGraph(ProductionState)

    def bind(fn: Callable[..., dict[str, Any]]) -> BoundNode:
        bound: BoundNode = partial(fn, deps=deps)
        return bound

    graph.add_node("extract_requirement", bind(nodes.extract_requirement))
    graph.add_node("validate_requirement", bind(nodes.validate_requirement))
    graph.add_node("ask_clarifying_question", bind(nodes.ask_clarifying_question))
    graph.add_node("update_requirement", bind(nodes.update_requirement))
    graph.add_node("human_review_requirement", bind(nodes.human_review_requirement))
    graph.add_node("assess_knowledge_need", bind(nodes.assess_knowledge_need))
    graph.add_node("retrieve_production_knowledge", bind(nodes.retrieve_production_knowledge))
    graph.add_node("recommend_production_method", bind(nodes.recommend_production_method))
    graph.add_node("human_review_method", bind(nodes.human_review_method))
    graph.add_node("search_suppliers", bind(nodes.search_suppliers))
    graph.add_node("calculate_matches", bind(nodes.calculate_matches))
    graph.add_node("human_select_supplier", bind(nodes.human_select_supplier))
    graph.add_node("generate_rfq", bind(nodes.generate_rfq))
    graph.add_node("human_review_rfq", bind(nodes.human_review_rfq))

    graph.add_edge(START, "extract_requirement")
    graph.add_conditional_edges(
        "extract_requirement",
        route_after_extraction,
        {"validate_requirement": "validate_requirement", "failed": END},
    )
    graph.add_conditional_edges(
        "validate_requirement",
        partial(route_after_validation, max_rounds=deps.max_clarification_rounds),
        {
            "ask_clarifying_question": "ask_clarifying_question",
            "human_review_requirement": "human_review_requirement",
            "failed": END,
        },
    )

    # The clarification loop: ask, merge, re-validate.
    graph.add_edge("ask_clarifying_question", "update_requirement")
    graph.add_edge("update_requirement", "validate_requirement")

    graph.add_edge("human_review_requirement", "assess_knowledge_need")
    graph.add_conditional_edges(
        "assess_knowledge_need",
        route_after_knowledge_assessment,
        {
            "retrieve_production_knowledge": "retrieve_production_knowledge",
            "recommend_production_method": "recommend_production_method",
            "failed": END,
        },
    )
    graph.add_edge("retrieve_production_knowledge", "recommend_production_method")
    graph.add_conditional_edges(
        "recommend_production_method",
        route_after_method_recommendation,
        {"human_review_method": "human_review_method", "failed": END},
    )

    graph.add_edge("human_review_method", "search_suppliers")
    graph.add_edge("search_suppliers", "calculate_matches")
    graph.add_edge("calculate_matches", "human_select_supplier")
    graph.add_edge("human_select_supplier", "generate_rfq")
    graph.add_edge("generate_rfq", "human_review_rfq")

    # Persistence of the completed project is the caller's job (the API service
    # owns the durable record), so an approved RFQ simply ends the run.
    graph.add_conditional_edges(
        "human_review_rfq", route_after_rfq_review, {"persist": END, "failed": END}
    )

    return graph


def _serializer() -> JsonPlusSerializer:
    """Serializer that knows exactly which domain types may cross the checkpoint.

    Without an explicit allowlist LangGraph warns on every load and will refuse
    outright in a future version, so this is what keeps typed state working
    across upgrades.
    """
    return JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINTED_TYPES)


def checkpointer_for(path: Path | str) -> BaseCheckpointSaver[str]:
    """Build a SQLite checkpointer for a long-lived process.

    ``SqliteSaver.from_conn_string`` is a context manager and closes the
    connection on exit, which is wrong for a server that must keep it open, so we
    construct the connection ourselves. ``check_same_thread=False`` because
    FastAPI serves requests on a thread pool.
    """
    if isinstance(path, Path):
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), check_same_thread=False)
    return SqliteSaver(connection, serde=_serializer())


def compile_workflow(
    deps: GraphDeps, checkpointer: BaseCheckpointSaver[str] | None = None
) -> CompiledStateGraph[ProductionState, None, Any, Any]:
    """Compile with a checkpointer. Required: interrupts cannot resume without one."""
    return build_graph(deps).compile(checkpointer=checkpointer)


def production_deps(settings: Settings | None = None, today: date | None = None) -> GraphDeps:
    """Wire the real provider, tools and settings. The single production seam."""
    settings = settings or get_settings()
    store = KnowledgeStore(
        knowledge_dir=settings.knowledge_dir,
        index_dir=settings.index_dir,
        embeddings=get_embedding_provider(settings),
        embedding_model=settings.embedding_model,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    provider = get_provider(settings)
    return GraphDeps(
        provider=provider,
        tools=ProductionTools(SupplierRepository(settings.suppliers_file)),
        retriever=KnowledgeRetriever(store, provider, k=settings.retrieval_k),
        today=today or date.today(),
        top_matches=settings.top_matches,
        deadline_buffer_days=settings.deadline_buffer_days,
        max_clarification_rounds=settings.max_clarification_rounds,
    )
