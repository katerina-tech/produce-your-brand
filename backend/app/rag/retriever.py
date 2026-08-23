"""Retrieval and the routing decision that makes it agentic.

Retrieval does not fire on every request. Something has to decide whether
technical knowledge is actually needed, and that decision is what separates
"we bolted on a RAG" from "the agent consults references when the question calls
for it".

The routing is layered, cheapest first:

1. **Deterministic fast paths.** Two intents are unambiguous and settled without
   a model call. A partner-directory question ("which suppliers in Berlin do
   engraving?") is a database lookup and must never hit the knowledge base. A
   feasibility question ("is laser engraving appropriate for anodised
   aluminium?") always should.
2. **A deterministic rule on the brief.** An unconfirmed material means
   feasibility genuinely cannot be assumed, so retrieve.
3. **The model**, for everything genuinely ambiguous - is this pairing routine
   enough to answer from general knowledge, or does it need looking up?

There is one retrieval implementation underneath, in :mod:`app.rag.store`.
"""

from __future__ import annotations

import logging
import unicodedata

from app.domain.enums import ProductionMethod
from app.domain.knowledge import KnowledgeSnippet, RetrievalDecision
from app.domain.requirement import ProductionRequirement
from app.llm import prompts
from app.llm.factory import LLMError, LLMProvider
from app.logging_config import Event, log_event
from app.rag.store import KnowledgeStore

logger = logging.getLogger(__name__)

# Phrasing that identifies a partner-directory question. These route to the
# supplier repository, never to the knowledge base.
SUPPLIER_LOOKUP_SIGNALS: tuple[str, ...] = (
    "which supplier",
    "which partner",
    "which company",
    "which manufacturer",
    "who can produce",
    "who can make",
    "who can do",
    "who offers",
    "who does",
    "suppliers in",
    "partners in",
    "manufacturers in",
    "companies in",
    "vendors in",
    "find a supplier",
    "find a partner",
    "list suppliers",
    "list partners",
    "recommend a supplier",
    "recommend a partner",
    "show me suppliers",
)

# Phrasing that identifies a technical-feasibility question.
FEASIBILITY_SIGNALS: tuple[str, ...] = (
    "appropriate for",
    "suitable for",
    "compatible with",
    "safe to",
    "is it safe",
    "work on",
    "can you engrave",
    "can you print",
    "can i engrave",
    "can i print",
    "is it possible to",
    "what happens if",
    "minimum size",
    "minimum line",
    "artwork requirement",
    "file format",
    "durability of",
    "how durable",
    "adhesion",
    "heat sensitive",
    "temperature",
)


def _normalise(text: str) -> str:
    """Fold to a comparable form before pattern checks.

    NFKC plus whitespace collapsing, so full-width or oddly spaced text cannot
    slip past the signal lists.
    """
    folded = unicodedata.normalize("NFKC", text).lower()
    return " ".join(folded.split())


class KnowledgeRetriever:
    """Decides whether to retrieve, then retrieves."""

    def __init__(
        self,
        store: KnowledgeStore,
        provider: LLMProvider,
        k: int = 4,
    ) -> None:
        self._store = store
        self._provider = provider
        self._k = k

    # ------------------------------------------------------------- routing

    def should_retrieve(self, question: str) -> RetrievalDecision:
        """Route a free-form question. Fast paths first, model only if needed."""
        normalised = _normalise(question)
        is_lookup = any(signal in normalised for signal in SUPPLIER_LOOKUP_SIGNALS)
        is_feasibility = any(signal in normalised for signal in FEASIBILITY_SIGNALS)

        if is_lookup and not is_feasibility:
            return self._logged(
                RetrievalDecision(
                    needs_retrieval=False,
                    query=None,
                    reason="Partner-directory question - answered from supplier data.",
                ),
                route="deterministic",
            )

        if is_feasibility and not is_lookup:
            return self._logged(
                RetrievalDecision(
                    needs_retrieval=True,
                    query=question,
                    reason="Technical feasibility question - consult production knowledge.",
                ),
                route="deterministic",
            )

        try:
            decision = self._provider.structured(
                RetrievalDecision,
                prompts.retrieval_router_messages(question),
                purpose="classifier",
            )
        except LLMError:
            # Retrieving unnecessarily costs a little; skipping when it was
            # needed costs correctness. Fail toward retrieval.
            return self._logged(
                RetrievalDecision(
                    needs_retrieval=True,
                    query=question,
                    reason="Router unavailable - retrieving as the safer default.",
                ),
                route="fallback",
            )

        if decision.needs_retrieval and not decision.query:
            decision = decision.model_copy(update={"query": question})
        return self._logged(decision, route="model")

    def assess_requirement(self, requirement: ProductionRequirement) -> RetrievalDecision:
        """Route from the brief, as the workflow does.

        One deterministic rule applies before the model is consulted: an
        unconfirmed material means feasibility cannot be assumed, so retrieve.
        """
        if requirement.material is None:
            return self._logged(
                RetrievalDecision(
                    needs_retrieval=True,
                    query=self._question_for(requirement),
                    reason="Material is unconfirmed, so feasibility cannot be assumed.",
                ),
                route="deterministic",
            )
        return self.should_retrieve(self._question_for(requirement))

    @staticmethod
    def _question_for(requirement: ProductionRequirement) -> str:
        """Build a neutral retrieval query from the brief.

        Deliberately free of the feasibility phrasing above, so the fast paths do
        not pre-empt the model on every single project.
        """
        parts = [
            f"Production method for applying {requirement.customization_description or 'branding'}",
            f"to {requirement.product or 'a product'}",
        ]
        if requirement.material:
            parts.append(f"made of {requirement.material}")
        if requirement.preferred_finish:
            parts.append(f"with a {requirement.preferred_finish} finish")
        return " ".join(parts) + "."

    def _logged(self, decision: RetrievalDecision, route: str) -> RetrievalDecision:
        log_event(
            logger,
            Event.RETRIEVAL_DECISION,
            needs_retrieval=decision.needs_retrieval,
            route=route,
            reason=decision.reason,
        )
        return decision

    # ---------------------------------------------------------- retrieving

    def search_production_knowledge(
        self, query: str, method: ProductionMethod | None = None, k: int | None = None
    ) -> list[KnowledgeSnippet]:
        """Retrieve passages for a technical question."""
        log_event(
            logger, Event.RAG_CALLED, query_len=len(query), method=method.value if method else None
        )
        return self._store.search(query, k=k or self._k, method=method)


def format_snippets(snippets: list[KnowledgeSnippet]) -> str:
    """Render retrieved passages for the prompt.

    Each passage is labelled with its source so the model can attribute claims,
    and the caller wraps the whole block in an untrusted-data fence.
    """
    blocks: list[str] = []
    for index, snippet in enumerate(snippets, 1):
        citation = snippet.citation
        header = f"[{index}] {citation.title}"
        if citation.source:
            header += f" - {citation.source}"
        blocks.append(f"{header}\n{snippet.text}")
    return "\n\n".join(blocks)
