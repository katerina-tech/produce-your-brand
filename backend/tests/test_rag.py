"""Agentic RAG: the routing decision, the one store, and the graph branch.

Two sprint requirements land here and they are a pair: a technical question must
route to the knowledge base, and a supplier lookup must not. Retrieval that fires
on every request is not agentic, so the branch has to demonstrably vary.

Retrieval itself runs offline against :class:`tests.fakes.HashingEmbedder`, whose
similarity is real term overlap rather than noise - so these assert ranking
behaviour, not just that the plumbing executes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.domain.enums import ProductionMethod, Stage
from app.domain.knowledge import RetrievalDecision
from app.domain.requirement import ProductionRequirement
from app.graph.state import ProductionState, initial_state
from app.graph.workflow import (
    GraphDeps,
    checkpointer_for,
    compile_workflow,
    route_after_knowledge_assessment,
)
from app.rag.retriever import KnowledgeRetriever, format_snippets
from app.rag.store import KnowledgeBaseError, KnowledgeStore, load_chunks
from app.repositories.supplier_repo import SupplierRepository
from app.tools.registry import ProductionTools
from tests.conftest import BACKEND_ROOT, TODAY
from tests.fakes import (
    CapturingProvider,
    FailingEmbedder,
    HashingEmbedder,
    ScriptedProvider,
)
from tests.test_graph import DEMO_REQUEST, _scripted

KNOWLEDGE_DIR = BACKEND_ROOT / "data" / "knowledge"

FEASIBILITY_QUESTION = "Is laser engraving appropriate for anodised aluminium?"
SUPPLIER_QUESTION = "Which suppliers in Berlin support laser engraving?"


@pytest.fixture
def store(tmp_path: Path) -> KnowledgeStore:
    """A store over the real knowledge base, indexed into a temp directory."""
    return KnowledgeStore(
        knowledge_dir=KNOWLEDGE_DIR,
        index_dir=tmp_path / "index",
        embeddings=HashingEmbedder(),
        embedding_model="hashing-test-embedder",
    )


@pytest.fixture
def retriever(store: KnowledgeStore) -> KnowledgeRetriever:
    return KnowledgeRetriever(store, ScriptedProvider(), k=4)


# ------------------------------------------------------ routing: the sprint pair


def test_technical_question_routes_to_the_knowledge_base(
    retriever: KnowledgeRetriever,
) -> None:
    """A feasibility question must consult production knowledge."""
    decision = retriever.should_retrieve(FEASIBILITY_QUESTION)

    assert decision.needs_retrieval is True
    assert decision.query == FEASIBILITY_QUESTION
    assert decision.reason


def test_supplier_lookup_does_not_route_to_the_knowledge_base(
    retriever: KnowledgeRetriever,
) -> None:
    """A partner-directory question is a database lookup, not a technical one."""
    decision = retriever.should_retrieve(SUPPLIER_QUESTION)

    assert decision.needs_retrieval is False
    assert decision.query is None


def test_supplier_lookup_does_not_even_call_the_model(store: KnowledgeStore) -> None:
    """The unambiguous case is settled deterministically, at zero cost.

    If this ever needed a model call, every directory question would be paying
    for a routing decision that plain code already knows.
    """
    provider = ScriptedProvider()
    decision = KnowledgeRetriever(store, provider).should_retrieve(SUPPLIER_QUESTION)

    assert decision.needs_retrieval is False
    assert provider.calls == [], "the fast path must not consult the model"


def test_feasibility_question_does_not_even_call_the_model(store: KnowledgeStore) -> None:
    provider = ScriptedProvider()
    decision = KnowledgeRetriever(store, provider).should_retrieve(FEASIBILITY_QUESTION)

    assert decision.needs_retrieval is True
    assert provider.calls == []


@pytest.mark.parametrize(
    "question",
    [
        "Which partner in Hamburg can produce embroidered caps?",
        "Who offers pad printing near Munich?",
        "Find a supplier for printed cartons.",
    ],
)
def test_more_directory_phrasings_stay_out_of_the_knowledge_base(
    store: KnowledgeStore, question: str
) -> None:
    assert (
        KnowledgeRetriever(store, ScriptedProvider()).should_retrieve(question).needs_retrieval
        is False
    )


@pytest.mark.parametrize(
    "question",
    [
        "Is it safe to laser cut PVC?",
        "What is the minimum line weight for weeded vinyl?",
        "Will foil work on a textured mat surface?",
    ],
)
def test_more_technical_phrasings_reach_the_knowledge_base(
    store: KnowledgeStore, question: str
) -> None:
    assert (
        KnowledgeRetriever(store, ScriptedProvider()).should_retrieve(question).needs_retrieval
        is True
    )


# ------------------------------------------------------------- routing: model


def test_ambiguous_question_is_delegated_to_the_model(store: KnowledgeStore) -> None:
    """Anything the fast paths cannot settle is a judgement call."""
    provider = ScriptedProvider(
        {RetrievalDecision: RetrievalDecision(needs_retrieval=False, reason="routine pairing")}
    )
    decision = KnowledgeRetriever(store, provider).should_retrieve(
        "We want our logo on 200 cotton tote bags."
    )

    assert decision.needs_retrieval is False
    assert ("RetrievalDecision", "classifier") in provider.calls, "routing uses the cheap model"


def test_router_failure_errs_toward_retrieving(store: KnowledgeStore) -> None:
    """An unnecessary lookup is cheap; a confident wrong claim is not."""
    provider = ScriptedProvider({RetrievalDecision: RuntimeError("router down")})
    decision = KnowledgeRetriever(store, provider).should_retrieve(
        "We want our logo on 200 cotton tote bags."
    )

    assert decision.needs_retrieval is True


def test_model_decision_without_a_query_still_gets_one(store: KnowledgeStore) -> None:
    """A True decision must always carry something searchable."""
    provider = ScriptedProvider(
        {RetrievalDecision: RetrievalDecision(needs_retrieval=True, reason="unusual substrate")}
    )
    decision = KnowledgeRetriever(store, provider).should_retrieve("Anodised bottle marking?")

    assert decision.needs_retrieval is True
    assert decision.query


# ---------------------------------------------------- routing: from the brief


def test_unconfirmed_material_always_retrieves(store: KnowledgeStore) -> None:
    """Feasibility cannot be assumed when the substrate is unknown."""
    provider = ScriptedProvider()
    requirement = ProductionRequirement(
        product="yoga mats", quantity=100, customization_description="gold logo", material=None
    )
    decision = KnowledgeRetriever(store, provider).assess_requirement(requirement)

    assert decision.needs_retrieval is True
    assert "material" in decision.reason.lower()
    assert provider.calls == [], "a deterministic rule needs no model"


def test_known_material_defers_to_the_model(store: KnowledgeStore) -> None:
    """With a stated material, whether to look it up is a judgement call."""
    provider = ScriptedProvider(
        {RetrievalDecision: RetrievalDecision(needs_retrieval=False, reason="routine")}
    )
    requirement = ProductionRequirement(
        product="tote bags", quantity=200, customization_description="logo", material="cotton"
    )
    decision = KnowledgeRetriever(store, provider).assess_requirement(requirement)

    assert decision.needs_retrieval is False
    assert provider.calls, "the model should have been consulted"


# ------------------------------------------------------------------- the store


def test_knowledge_base_loads_and_chunks() -> None:
    chunks = load_chunks(KNOWLEDGE_DIR, chunk_size=800, chunk_overlap=120)

    assert len(chunks) > 20, "13 documents should yield a useful number of passages"
    assert all(chunk.text.strip() for chunk in chunks)
    assert all(chunk.title for chunk in chunks)


def test_frontmatter_metadata_is_parsed() -> None:
    """Metadata must survive, or citations and filtering are impossible."""
    chunks = load_chunks(KNOWLEDGE_DIR, chunk_size=800, chunk_overlap=120)

    laser = [c for c in chunks if c.production_method is ProductionMethod.LASER_ENGRAVING]
    assert laser, "laser engraving documents should be scoped to that method"
    assert any("anodised_aluminium" in c.materials for c in laser)
    assert all(c.source for c in chunks), "every passage must be attributable"

    unscoped = [c for c in chunks if c.production_method is None]
    assert unscoped, "cross-cutting reference documents legitimately have no method"


def test_missing_frontmatter_is_rejected(tmp_path: Path) -> None:
    """A document with no metadata cannot be cited, so it fails loudly."""
    (tmp_path / "bad.md").write_text("# No frontmatter here\n", encoding="utf-8")

    with pytest.raises(KnowledgeBaseError, match="frontmatter"):
        load_chunks(tmp_path, chunk_size=800, chunk_overlap=120)


def test_empty_knowledge_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(KnowledgeBaseError):
        load_chunks(tmp_path, chunk_size=800, chunk_overlap=120)


def test_index_builds_and_persists(store: KnowledgeStore, tmp_path: Path) -> None:
    count = store.build()

    assert count > 20
    assert (tmp_path / "index" / "index.faiss").is_file()
    assert (tmp_path / "index" / "chunks.json").is_file()
    assert (tmp_path / "index" / "manifest.json").is_file()


def test_search_finds_the_relevant_document(store: KnowledgeStore) -> None:
    """The canonical technical question must surface the matching passage."""
    store.build()

    snippets = store.search("laser engraving anodised aluminium dye layer", k=3)

    assert snippets
    titles = " ".join(snippet.citation.title.lower() for snippet in snippets)
    assert "anodised" in titles
    assert snippets[0].score > snippets[-1].score or len(snippets) == 1


def test_search_surfaces_the_pvc_safety_warning(store: KnowledgeStore) -> None:
    """The genuinely useful case: laser plus PVC is a refusal, not a preference.

    A yoga-mat project asking for engraving should reach this passage, which is
    the whole point of having a knowledge base rather than trusting recall.
    """
    store.build()

    snippets = store.search("laser cut PVC chlorine hydrogen chloride safety", k=3)

    combined = " ".join(snippet.text.lower() for snippet in snippets)
    assert "pvc" in combined
    assert "chlorine" in combined or "hydrogen chloride" in combined


def test_method_filter_scopes_results(store: KnowledgeStore) -> None:
    """A method filter excludes other methods but keeps unscoped references."""
    store.build()

    snippets = store.search(
        "thread stitch count digitising", k=5, method=ProductionMethod.EMBROIDERY
    )

    for snippet in snippets:
        assert snippet.production_method in (ProductionMethod.EMBROIDERY, None)


def test_citations_carry_through_to_snippets(store: KnowledgeStore) -> None:
    store.build()

    snippet = store.search("screen printing setup cost per screen", k=1)[0]

    assert snippet.citation.title
    assert snippet.citation.source
    assert snippet.citation.updated_at is not None
    assert snippet.score > 0


def test_editing_a_document_makes_the_index_stale(store: KnowledgeStore, tmp_path: Path) -> None:
    """A stale index is worse than a missing one, so it must be detectable.

    The fingerprint covers document bytes and the embedding model name, so an
    edit or a model switch both force a rebuild instead of silently searching
    yesterday's corpus.
    """
    scratch = tmp_path / "kb"
    scratch.mkdir()
    doc = scratch / "note.md"
    frontmatter = "\n".join(
        [
            "---",
            "title: Note",
            "production_method: null",
            "materials: []",
            "source: test",
            "source_url: null",
            "updated_at: 2026-08-01",
            "---",
        ]
    )
    doc.write_text(f"{frontmatter}\n\n## Body\n\nOriginal text.\n", encoding="utf-8")
    local = KnowledgeStore(
        knowledge_dir=scratch,
        index_dir=tmp_path / "idx2",
        embeddings=HashingEmbedder(),
        embedding_model="hashing-test-embedder",
    )

    assert local.is_stale() is True
    local.build()
    assert local.is_stale() is False

    doc.write_text(doc.read_text(encoding="utf-8") + "\nAdded later.\n", encoding="utf-8")
    assert local.is_stale() is True


def test_switching_embedding_model_invalidates_the_index(
    store: KnowledgeStore, tmp_path: Path
) -> None:
    store.build()
    other = KnowledgeStore(
        knowledge_dir=KNOWLEDGE_DIR,
        index_dir=tmp_path / "index",
        embeddings=HashingEmbedder(),
        embedding_model="a-different-model",
    )
    assert other.is_stale() is True


def test_search_rebuilds_a_missing_index_automatically(store: KnowledgeStore) -> None:
    """The app should work on a fresh checkout without a manual build step."""
    assert store.is_stale() is True

    snippets = store.search("embroidery minimum letter height", k=2)

    assert snippets
    assert store.is_stale() is False


def test_format_snippets_labels_each_source(store: KnowledgeStore) -> None:
    store.build()
    rendered = format_snippets(store.search("foil transfer temperature", k=2))

    assert "[1]" in rendered and "[2]" in rendered
    assert "Produce Your Brand curated production note" in rendered


# ------------------------------------------------------------ graph integration


def _deps(provider: Any, retriever: KnowledgeRetriever | None, **kwargs: Any) -> GraphDeps:
    return GraphDeps(
        provider=provider,
        tools=ProductionTools(SupplierRepository(BACKEND_ROOT / "data" / "suppliers.json")),
        today=TODAY,
        retriever=retriever,
        **kwargs,
    )


def test_route_sends_a_needed_lookup_to_retrieval() -> None:
    state: ProductionState = {
        "retrieval_decision": RetrievalDecision(
            needs_retrieval=True, reason="heat-sensitive substrate", query="q"
        )
    }
    assert route_after_knowledge_assessment(state) == "retrieve_production_knowledge"


def test_route_skips_retrieval_when_not_needed() -> None:
    state: ProductionState = {
        "retrieval_decision": RetrievalDecision(needs_retrieval=False, reason="routine pairing")
    }
    assert route_after_knowledge_assessment(state) == "recommend_production_method"


def test_retrieved_knowledge_reaches_the_method_prompt(
    store: KnowledgeStore, tmp_path: Path
) -> None:
    """When retrieval fires, the passages must actually inform the recommendation.

    Otherwise the RAG is a side effect that changes nothing.
    """
    inner = _scripted(
        RetrievalDecision=RetrievalDecision(
            needs_retrieval=True, query="foil on PVC mats", reason="heat-sensitive substrate"
        )
    )
    provider = CapturingProvider(inner)
    retriever = KnowledgeRetriever(store, provider, k=3)
    app = compile_workflow(_deps(provider, retriever), checkpointer_for(tmp_path / "wf.db"))
    config: RunnableConfig = {"configurable": {"thread_id": "t-rag"}}

    app.invoke(initial_state("r1", DEMO_REQUEST, TODAY.isoformat()), config)
    app.invoke(Command(resume={"confirmed": True}), config)

    method_prompt = next(
        "\n".join(str(m.content) for m in messages if m.type == "human")
        for messages in provider.prompts
        if any("recommend the production method" in str(m.content).lower() for m in messages)
    )
    assert "<untrusted_knowledge_excerpts>" in method_prompt, "knowledge must arrive fenced"

    recommendation = app.get_state(config).values["recommended_methods"]
    assert recommendation.retrieval_used is True
    assert recommendation.sources, "citations must record what was actually retrieved"


def test_skipping_retrieval_leaves_the_recommendation_uncited(
    store: KnowledgeStore, tmp_path: Path
) -> None:
    """A recommendation made without sources must not claim any.

    This is the honesty half of the branch: retrieval_used is a fact about the
    run, set in code, not something the model may assert.
    """
    provider = _scripted(
        RetrievalDecision=RetrievalDecision(needs_retrieval=False, reason="routine pairing")
    )
    retriever = KnowledgeRetriever(store, provider, k=3)
    app = compile_workflow(_deps(provider, retriever), checkpointer_for(tmp_path / "wf2.db"))
    config: RunnableConfig = {"configurable": {"thread_id": "t-norag"}}

    app.invoke(initial_state("r2", DEMO_REQUEST, TODAY.isoformat()), config)
    app.invoke(Command(resume={"confirmed": True}), config)

    values = app.get_state(config).values
    assert values["retrieved_knowledge"] == []
    assert values["recommended_methods"].retrieval_used is False
    assert values["recommended_methods"].sources == []


def test_retrieval_outage_degrades_instead_of_failing(tmp_path: Path) -> None:
    """Losing the index must cost confidence, not the whole project."""
    broken = KnowledgeStore(
        knowledge_dir=KNOWLEDGE_DIR,
        index_dir=tmp_path / "broken",
        embeddings=FailingEmbedder(),
        embedding_model="failing",
    )
    provider = _scripted(
        RetrievalDecision=RetrievalDecision(needs_retrieval=True, query="anything", reason="needed")
    )
    retriever = KnowledgeRetriever(broken, provider, k=3)
    app = compile_workflow(_deps(provider, retriever), checkpointer_for(tmp_path / "wf3.db"))
    config: RunnableConfig = {"configurable": {"thread_id": "t-broken"}}

    app.invoke(initial_state("r3", DEMO_REQUEST, TODAY.isoformat()), config)
    result = app.invoke(Command(resume={"confirmed": True}), config)

    assert result["current_stage"] is not Stage.FAILED
    assert result["retrieved_knowledge"] == []
    assert result["recommended_methods"] is not None


def test_workflow_runs_without_any_retriever(tmp_path: Path) -> None:
    """The graph must stay runnable with no knowledge base configured at all."""
    provider = _scripted()
    app = compile_workflow(_deps(provider, None), checkpointer_for(tmp_path / "wf4.db"))
    config: RunnableConfig = {"configurable": {"thread_id": "t-noretriever"}}

    app.invoke(initial_state("r4", DEMO_REQUEST, TODAY.isoformat()), config)
    result = app.invoke(Command(resume={"confirmed": True}), config)

    assert result["current_stage"] is not Stage.FAILED
    assert result["recommended_methods"].retrieval_used is False
